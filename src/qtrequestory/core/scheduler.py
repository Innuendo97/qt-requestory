"""Windows Task Scheduler integration: the scheduled task is what keeps the mirror complete.

The server keeps roughly one day of logs, so a missed day is lost for good.
The task therefore mirrors the legacy ``NginxLogSync`` PowerShell task
semantics exactly: every day at ``start_time``, repeated hourly for
``repeat_for_h`` hours (each run exits early when today is already synced),
``StartWhenAvailable`` so a PC switched on after 09:00 still catches up, plus a
logon trigger, all under the interactive token (no stored password, and the
per-user VPN is available).

Everything goes through ``schtasks.exe`` with an XML definition: unlike the
PowerShell cmdlets it needs no elevation, no module and no console window.
A ``CommandRunner`` is injected so tests never touch the real scheduler.

Pitfalls handled here:
- never derive the exe path from ``argv[0]``/cwd — under Task Scheduler both
  are unreliable (the legacy script needed ``$PSScriptRoot`` for the same reason);
- ``schtasks`` speaks the OEM code page and localises everything, so the
  verbose CSV is parsed by column POSITION, and "not found" is detected by
  re-querying the task rather than by matching localised error text.
"""
from __future__ import annotations

import csv
import io
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Callable

from qtrequestory.core.config import ScheduleSettings, parse_hhmm
from qtrequestory.core.paths import executable_path

TASK_NAME = "qtRequestory Sync"
LEGACY_TASK_NAME = "NginxLogSync"

TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
TASK_XML_VERSION = "1.2"
XML_DECLARATION = '<?xml version="1.0" encoding="UTF-16"?>\n'

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


class SchedulerError(Exception):
    """schtasks failed; the message carries its (localised) output."""


#: Used when ``ScheduleSettings.start_time`` cannot be parsed (a hand-edited
#: config): the task must still be registered, or the mirror silently stops.
DEFAULT_START_TIME = time(9, 0)


@dataclass(frozen=True)
class TaskSpec:
    """What to register. Defaults reproduce the legacy task: 09:00 daily, hourly for 9 h (until 18:00)."""

    exe: Path
    args: str = "--sync"
    start_time: time = DEFAULT_START_TIME
    repeat_every_h: int = 1
    #: ``0`` = no repetition at all: one run a day (no ``Repetition`` element).
    repeat_for_h: int = 9
    run_at_logon: bool = True
    exec_limit_h: int = 3


def spec_from_config(schedule: ScheduleSettings, exe: Path) -> TaskSpec:
    """The task to register for the schedule saved in ``config.json``.

    The one place that turns the four stored values into a ``TaskSpec``, so the
    scheduled task and what Impostazioni shows can never describe different
    things. An unparsable ``start_time`` falls back to :data:`DEFAULT_START_TIME`
    rather than raising: ``config.validate`` is what tells the user about it,
    and a task that refuses to register would cost whole days of logs.
    """
    return TaskSpec(
        exe=exe,
        start_time=parse_hhmm(schedule.start_time) or DEFAULT_START_TIME,
        repeat_every_h=schedule.repeat_every_h,
        repeat_for_h=schedule.repeat_for_h,
        run_at_logon=schedule.run_at_logon,
    )


@dataclass(frozen=True)
class TaskStatus:
    """Snapshot of the registered task; ``state``/``next_run``/``last_run`` are the localised strings schtasks prints."""

    registered: bool
    command: Path | None
    args: str | None
    exe_matches: bool
    state: str | None
    next_run: str | None
    last_run: str | None
    last_result: int | None


NOT_REGISTERED = TaskStatus(
    registered=False, command=None, args=None, exe_matches=False,
    state=None, next_run=None, last_run=None, last_result=None,
)


# ----------------------------------------------------------------- runner


def run_schtasks(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``schtasks`` hidden (the GUI is a windowed exe) and decode its OEM output leniently."""
    return subprocess.run(
        ["schtasks", *args],
        capture_output=True,
        encoding="oem",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _output(result: subprocess.CompletedProcess) -> str:
    return ((result.stderr or "") + (result.stdout or "")).strip()


def _check(result: subprocess.CompletedProcess, what: str) -> None:
    if result.returncode != 0:
        raise SchedulerError(f"schtasks {what} fallito (codice {result.returncode}): {_output(result)}")


# ------------------------------------------------------------------- XML


def default_description(spec: TaskSpec) -> str:
    """What the Task Scheduler console shows about this task.

    Deliberately NOT the sentence Impostazioni shows: this one lives in the
    Windows console, is written once at registration time and must stay in the
    core (the UI wording is in ``ui/strings``).
    """
    start = spec.start_time.strftime("%H:%M")
    preamble = "qtRequestory: scarica i log giornalieri delle richieste nginx nel mirror locale. "
    if spec.repeat_for_h <= 0:
        return preamble + f"Ogni giorno alle {start}."
    end_h = (spec.start_time.hour + spec.repeat_for_h) % 24
    return (
        preamble + f"Ogni giorno dalle {start}, "
        f"ritenta ogni {spec.repeat_every_h} h fino alle {end_h:02d}:{spec.start_time.minute:02d}."
    )


def build_task_xml(spec: TaskSpec, user_id: str, description: str, today: date | None = None) -> str:
    """Task Scheduler 1.2 XML for ``spec``, built with ElementTree so paths with ``&``/``<`` are escaped."""
    ET.register_namespace("", TASK_NS)

    def el(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
        child = ET.SubElement(parent, f"{{{TASK_NS}}}{tag}", attrs)
        if text is not None:
            child.text = text
        return child

    start = datetime.combine(today or date.today(), spec.start_time).strftime("%Y-%m-%dT%H:%M:%S")

    root = ET.Element(f"{{{TASK_NS}}}Task", {"version": TASK_XML_VERSION})
    el(el(root, "RegistrationInfo"), "Description", description)

    triggers = el(root, "Triggers")
    cal = el(triggers, "CalendarTrigger")
    # repeat_for_h == 0 means "once a day": Task Scheduler rejects a Repetition
    # with Duration=PT0H, so the element must be left out entirely.
    if spec.repeat_for_h > 0:
        rep = el(cal, "Repetition")
        el(rep, "Interval", f"PT{spec.repeat_every_h}H")
        el(rep, "Duration", f"PT{spec.repeat_for_h}H")
        el(rep, "StopAtDurationEnd", "false")
    el(cal, "StartBoundary", start)
    el(cal, "Enabled", "true")
    el(el(cal, "ScheduleByDay"), "DaysInterval", "1")
    if spec.run_at_logon:
        logon = el(triggers, "LogonTrigger")
        el(logon, "Enabled", "true")
        el(logon, "UserId", user_id)

    principal = el(el(root, "Principals"), "Principal", id="Author")
    el(principal, "UserId", user_id)
    el(principal, "LogonType", "InteractiveToken")
    el(principal, "RunLevel", "LeastPrivilege")

    settings = el(root, "Settings")
    el(settings, "MultipleInstancesPolicy", "IgnoreNew")
    el(settings, "DisallowStartIfOnBatteries", "false")
    el(settings, "StopIfGoingOnBatteries", "false")
    el(settings, "AllowHardTerminate", "true")
    el(settings, "StartWhenAvailable", "true")
    el(settings, "ExecutionTimeLimit", f"PT{spec.exec_limit_h}H")
    el(settings, "Enabled", "true")
    el(settings, "Hidden", "false")

    exec_ = el(el(root, "Actions", Context="Author"), "Exec")
    el(exec_, "Command", str(spec.exe))
    el(exec_, "Arguments", spec.args)
    el(exec_, "WorkingDirectory", str(spec.exe.parent))

    ET.indent(root)
    return XML_DECLARATION + ET.tostring(root, encoding="unicode") + "\n"


def _parse_task_xml(text: str) -> ET.Element:
    # schtasks prints the definition with an ``encoding="UTF-16"`` declaration
    # that no longer applies once we hold a str; drop it (and any BOM) first.
    body = text.lstrip("﻿ \r\n\t")
    if body.startswith("<?xml"):
        body = body.split("?>", 1)[1]
    return ET.fromstring(body)


# ------------------------------------------------------------- operations


def _default_user_id() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def register(
    spec: TaskSpec,
    *,
    runner: CommandRunner = run_schtasks,
    user_id: str | None = None,
    description: str | None = None,
    task_name: str = TASK_NAME,
) -> None:
    """Create or overwrite the task (``/F``) from a UTF-16 XML temp file — the encoding schtasks expects."""
    xml = build_task_xml(spec, user_id or _default_user_id(), description or default_description(spec))
    fd, tmp = tempfile.mkstemp(prefix="qtrequestory-task-", suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16", newline="") as f:  # "utf-16" writes the BOM
            f.write(xml)
        _check(runner(["/Create", "/TN", task_name, "/XML", tmp, "/F"]), "/Create")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _exists(task_name: str, runner: CommandRunner) -> bool:
    return runner(["/Query", "/TN", task_name]).returncode == 0


def _delete(task_name: str, runner: CommandRunner) -> None:
    """``/Delete /F``; a missing task is fine. Locale-proof: instead of matching the
    localised "cannot find the file" text, re-query and only raise if the task is still there."""
    result = runner(["/Delete", "/TN", task_name, "/F"])
    if result.returncode != 0 and _exists(task_name, runner):
        _check(result, "/Delete")


def unregister(*, runner: CommandRunner = run_schtasks, task_name: str = TASK_NAME) -> None:
    _delete(task_name, runner)


def run_now(*, runner: CommandRunner = run_schtasks, task_name: str = TASK_NAME) -> None:
    _check(runner(["/Run", "/TN", task_name]), "/Run")


def detect_legacy_task(*, runner: CommandRunner = run_schtasks) -> bool:
    return _exists(LEGACY_TASK_NAME, runner)


def remove_legacy_task(*, runner: CommandRunner = run_schtasks) -> None:
    _delete(LEGACY_TASK_NAME, runner)


# ------------------------------------------------------------------ status

# ``schtasks /Query /V /FO CSV /NH`` columns (headers are localised, positions are not):
# 0 HostName, 1 TaskName, 2 Next Run Time, 3 Status, 4 Logon Mode, 5 Last Run Time, 6 Last Result, ...
_COL_NEXT_RUN, _COL_STATUS, _COL_LAST_RUN, _COL_LAST_RESULT = 2, 3, 5, 6


def _parse_verbose_csv(text: str) -> tuple[str | None, str | None, str | None, int | None]:
    """(next_run, state, last_run, last_result) from the first CSV row (one row per trigger)."""
    for row in csv.reader(io.StringIO(text)):
        if len(row) > _COL_LAST_RESULT:
            last = row[_COL_LAST_RESULT].strip()
            try:
                last_result: int | None = int(last)
            except ValueError:
                last_result = None
            return row[_COL_NEXT_RUN], row[_COL_STATUS], row[_COL_LAST_RUN], last_result
    return None, None, None, None


def _same_file(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def status(current_exe: Path | None, *, runner: CommandRunner = run_schtasks, task_name: str = TASK_NAME) -> TaskStatus:
    """Registered? Pointing at *this* exe? Plus the runtime info schtasks reports."""
    result = runner(["/Query", "/TN", task_name, "/XML", "ONE"])
    if result.returncode != 0:
        return NOT_REGISTERED

    root = _parse_task_xml(result.stdout or "")
    command_el = root.find(f".//{{{TASK_NS}}}Exec/{{{TASK_NS}}}Command")
    args_el = root.find(f".//{{{TASK_NS}}}Exec/{{{TASK_NS}}}Arguments")
    command_text = (command_el.text or "").strip().strip('"') if command_el is not None else ""
    command = Path(command_text) if command_text else None
    args = (args_el.text or "") if args_el is not None else None

    verbose = runner(["/Query", "/TN", task_name, "/V", "/FO", "CSV", "/NH"])
    next_run, state, last_run, last_result = (
        _parse_verbose_csv(verbose.stdout or "") if verbose.returncode == 0 else (None, None, None, None)
    )

    return TaskStatus(
        registered=True,
        command=command,
        args=args,
        exe_matches=command is not None and current_exe is not None and _same_file(command, current_exe),
        state=state,
        next_run=next_run,
        last_run=last_run,
        last_result=last_result,
    )


# ------------------------------------------------------------- exe location


def current_exe_for_task() -> Path | None:
    """The packaged exe to point the task at; None from source (``python -m qtrequestory`` is not schedulable)."""
    return executable_path()


def _is_under(path: Path, base: str | None) -> bool:
    if not base:
        return False
    p = os.path.normcase(str(path))
    b = os.path.normcase(str(Path(base))).rstrip("\\/")
    return p == b or p.startswith(b + os.sep) or p.startswith(b + "/")


def is_unstable_location(exe: Path) -> str | None:
    """Why scheduling this exe is a bad idea (Italian, for the UI), or None when the folder looks permanent.

    A task pointing at a file that gets cleaned up, moved or is only reachable
    through the network silently stops syncing — and lost days cannot be recovered.
    """
    raw = str(exe)
    if raw.startswith("\\\\") or raw.startswith("//"):
        return "L'eseguibile si trova su un percorso di rete (UNC): il task fallisce quando la rete non è raggiungibile."
    for base in (os.environ.get("TEMP"), os.environ.get("TMP"), tempfile.gettempdir()):
        if _is_under(exe, base):
            return "L'eseguibile si trova in una cartella temporanea (%TEMP%): potrebbe essere cancellato."
    parts = [p.lower() for p in exe.parts]
    if "downloads" in parts:
        return "L'eseguibile si trova in Downloads: spostalo in una cartella stabile prima di pianificare il task."
    if any(p.startswith("onedrive") for p in parts):
        return "L'eseguibile si trova in OneDrive: la sincronizzazione cloud può spostarlo o bloccarlo."
    return None
