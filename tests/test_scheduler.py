"""core/scheduler.py — Task Scheduler integration, exercised with a fake schtasks.

No real task is registered unless ``QTREQ_INTEGRATION`` is set: every test
drives the module through a recording ``FakeRunner`` that returns canned
``CompletedProcess`` results, so the suite is safe on any machine (and on CI
boxes without Task Scheduler at all).
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import date, time
from pathlib import Path

import pytest

from qtrequestory.core import scheduler
from qtrequestory.core.config import ScheduleSettings
from qtrequestory.core.scheduler import (
    LEGACY_TASK_NAME,
    TASK_NAME,
    SchedulerError,
    NOT_REGISTERED,
    TaskSpec,
    TaskStatus,
    build_task_xml,
    default_description,
    detect_legacy_task,
    is_unstable_location,
    register,
    remove_legacy_task,
    run_now,
    spec_from_config,
    status,
    unregister,
)

NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
USER = "DOMAIN\\someone"


def _ok(stdout: str = "", args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["schtasks", *(args or [])], 0, stdout=stdout, stderr="")


def _fail(stderr: str = "ERRORE: qualcosa", code: int = 1, args: list[str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["schtasks", *(args or [])], code, stdout="", stderr=stderr)


class FakeRunner:
    """Records every schtasks invocation and answers by the first argument (/Create, /Query, ...).

    ``responses`` maps a verb to a CompletedProcess, or to a callable taking the
    argument list (so a test can inspect the XML file while it still exists).
    """

    def __init__(self, **responses):
        self.responses = {"/" + verb.lower(): resp for verb, resp in responses.items()}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        resp = self.responses.get(args[0].lower())
        if resp is None:
            raise AssertionError(f"unexpected schtasks call: {args}")
        return resp(args) if callable(resp) else resp

    def calls_for(self, verb: str) -> list[list[str]]:
        return [c for c in self.calls if c[0].lower() == "/" + verb.lower()]


def _spec(exe: Path | None = None, **kw) -> TaskSpec:
    return TaskSpec(exe=exe or Path(r"C:\Tools\qtRequestory\qtRequestory.exe"), **kw)


def _find(root: ET.Element, path: str) -> ET.Element:
    """XPath with the task namespace applied to every step."""
    qualified = "/".join(f"{{{NS}}}{step}" if step not in ("", ".") else step for step in path.split("/"))
    el = root.find(qualified)
    assert el is not None, f"missing element {path}"
    return el


def _text(root: ET.Element, path: str) -> str:
    return _find(root, path).text or ""


# ------------------------------------------------------------- build_task_xml


class TestBuildTaskXml:
    def test_document_shape_and_values(self):
        xml = build_task_xml(_spec(), USER, "descr", today=date(2026, 9, 22))
        root = ET.fromstring(xml)
        assert root.tag == f"{{{NS}}}Task"
        assert root.get("version") == "1.2"
        assert "ns0:" not in xml
        assert _text(root, "RegistrationInfo/Description") == "descr"

        trig = _find(root, "Triggers/CalendarTrigger")
        assert _text(trig, "StartBoundary") == "2026-09-22T09:00:00"
        assert _text(trig, "Enabled") == "true"
        assert _text(trig, "ScheduleByDay/DaysInterval") == "1"
        assert _text(trig, "Repetition/Interval") == "PT1H"
        assert _text(trig, "Repetition/Duration") == "PT9H"
        assert _text(trig, "Repetition/StopAtDurationEnd") == "false"

        logon = _find(root, "Triggers/LogonTrigger")
        assert _text(logon, "UserId") == USER
        assert _text(logon, "Enabled") == "true"

        principal = _find(root, "Principals/Principal")
        assert principal.get("id") == "Author"
        assert _text(principal, "UserId") == USER
        assert _text(principal, "LogonType") == "InteractiveToken"
        assert _text(principal, "RunLevel") == "LeastPrivilege"

        s = _find(root, "Settings")
        assert _text(s, "MultipleInstancesPolicy") == "IgnoreNew"
        assert _text(s, "DisallowStartIfOnBatteries") == "false"
        assert _text(s, "StopIfGoingOnBatteries") == "false"
        assert _text(s, "StartWhenAvailable") == "true"
        assert _text(s, "ExecutionTimeLimit") == "PT3H"
        assert _text(s, "Enabled") == "true"
        assert _text(s, "Hidden") == "false"
        assert _text(s, "AllowHardTerminate") == "true"

        actions = _find(root, "Actions")
        assert actions.get("Context") == "Author"
        exec_ = _find(actions, "Exec")
        assert _text(exec_, "Command") == r"C:\Tools\qtRequestory\qtRequestory.exe"
        assert _text(exec_, "Arguments") == "--sync"
        assert _text(exec_, "WorkingDirectory") == r"C:\Tools\qtRequestory"

    def test_custom_spec_values(self):
        spec = _spec(start_time=time(7, 30), repeat_every_h=2, repeat_for_h=11, exec_limit_h=1, args="--sync --force")
        root = ET.fromstring(build_task_xml(spec, USER, "d", today=date(2026, 1, 5)))
        assert _text(root, "Triggers/CalendarTrigger/StartBoundary") == "2026-01-05T07:30:00"
        assert _text(root, "Triggers/CalendarTrigger/Repetition/Interval") == "PT2H"
        assert _text(root, "Triggers/CalendarTrigger/Repetition/Duration") == "PT11H"
        assert _text(root, "Settings/ExecutionTimeLimit") == "PT1H"
        assert _text(root, "Actions/Exec/Arguments") == "--sync --force"

    def test_today_defaults_to_current_date(self):
        root = ET.fromstring(build_task_xml(_spec(), USER, "d"))
        assert _text(root, "Triggers/CalendarTrigger/StartBoundary").startswith(date.today().isoformat())

    def test_no_logon_trigger_when_disabled(self):
        root = ET.fromstring(build_task_xml(_spec(run_at_logon=False), USER, "d"))
        assert root.find(f"{{{NS}}}Triggers/{{{NS}}}LogonTrigger") is None
        assert root.find(f"{{{NS}}}Triggers/{{{NS}}}CalendarTrigger") is not None

    def test_no_repetition_element_at_all_when_the_window_is_zero(self):
        """``repeat_for_h = 0`` is "once a day", and Task Scheduler rejects a
        ``Repetition`` with ``Duration=PT0H`` — the element must be absent."""
        root = ET.fromstring(build_task_xml(_spec(repeat_for_h=0), USER, "d"))
        trigger = _find(root, "Triggers/CalendarTrigger")
        assert trigger.find(f"{{{NS}}}Repetition") is None
        assert _text(trigger, "ScheduleByDay/DaysInterval") == "1"
        assert _text(trigger, "StartBoundary").endswith("T09:00:00")

    def test_the_repetition_element_is_there_as_soon_as_the_window_is_not(self):
        root = ET.fromstring(build_task_xml(_spec(repeat_for_h=1), USER, "d"))
        assert _text(root, "Triggers/CalendarTrigger/Repetition/Duration") == "PT1H"

    def test_special_characters_are_escaped(self):
        exe = Path(r"C:\Program Files\Tools & Co\<odd>\qtRequestory.exe")
        xml = build_task_xml(_spec(exe), USER, 'Desc with "quotes" & <tags>')
        assert "Tools &amp; Co" in xml
        assert "&lt;odd&gt;" in xml
        root = ET.fromstring(xml)
        assert _text(root, "Actions/Exec/Command") == str(exe)
        assert _text(root, "Actions/Exec/WorkingDirectory") == str(exe.parent)
        assert _text(root, "RegistrationInfo/Description") == 'Desc with "quotes" & <tags>'

    def test_declares_utf16_so_the_file_matches_what_register_writes(self):
        xml = build_task_xml(_spec(), USER, "d")
        assert xml.lstrip().startswith("<?xml")
        assert "UTF-16" in xml.split("?>", 1)[0].upper()


# ------------------------------------------------------------ spec_from_config


class TestSpecFromConfig:
    """The schedule the user saved in Impostazioni is what gets registered."""

    def test_every_field_of_the_block_reaches_the_spec(self):
        exe = Path(r"C:\Tools\qtRequestory\qtRequestory.exe")
        spec = spec_from_config(
            ScheduleSettings(start_time="07:30", repeat_every_h=2, repeat_for_h=6,
                             run_at_logon=False),
            exe,
        )
        assert spec == TaskSpec(exe=exe, start_time=time(7, 30), repeat_every_h=2,
                                repeat_for_h=6, run_at_logon=False)
        assert spec.args == "--sync"

    def test_the_defaults_reproduce_the_previously_hard_coded_task(self):
        exe = Path(r"C:\Tools\qtRequestory\qtRequestory.exe")
        assert spec_from_config(ScheduleSettings(), exe) == TaskSpec(exe=exe)

    def test_a_hand_edited_start_time_falls_back_instead_of_raising(self):
        """``validate`` reports it in the UI; here the task must still register:
        refusing to schedule anything would silently stop the mirror."""
        spec = spec_from_config(ScheduleSettings(start_time="mezzogiorno"), Path("q.exe"))
        assert spec.start_time == TaskSpec(exe=Path("q.exe")).start_time

    @pytest.mark.parametrize(
        "stored, expected",
        [
            (ScheduleSettings(repeat_every_h=0), (1, 9)),      # PT0H: schtasks refuses the XML
            (ScheduleSettings(repeat_every_h=99), (12, 9)),
            (ScheduleSettings(repeat_every_h=-3), (1, 9)),
            (ScheduleSettings(repeat_for_h=99), (1, 23)),
            (ScheduleSettings(repeat_for_h=-1), (1, 0)),
        ],
    )
    def test_hand_edited_counts_are_clamped_to_the_validated_range(self, stored, expected):
        """Same story as the start time: the file can hold anything, and an
        ``<Interval>PT0H</Interval>`` would make ``register`` raise instead of
        scheduling a slightly different — but working — task."""
        spec = spec_from_config(stored, Path("q.exe"))
        assert (spec.repeat_every_h, spec.repeat_for_h) == expected

    def test_a_clamped_schedule_still_produces_XML_schtasks_can_parse(self):
        spec = spec_from_config(ScheduleSettings(repeat_every_h=0), Path("q.exe"))
        root = ET.fromstring(build_task_xml(spec, USER, "d"))
        assert _text(root, "Triggers/CalendarTrigger/Repetition/Interval") == "PT1H"

    def test_the_xml_of_a_single_daily_run_has_no_repetition_and_no_logon(self):
        schedule = ScheduleSettings(start_time="06:15", repeat_for_h=0, run_at_logon=False)
        root = ET.fromstring(
            build_task_xml(spec_from_config(schedule, Path("q.exe")), USER, "d",
                           today=date(2026, 9, 22))
        )
        trigger = _find(root, "Triggers/CalendarTrigger")
        assert _text(trigger, "StartBoundary") == "2026-09-22T06:15:00"
        assert trigger.find(f"{{{NS}}}Repetition") is None
        assert root.find(f"{{{NS}}}Triggers/{{{NS}}}LogonTrigger") is None

    def test_the_description_does_not_promise_retries_it_will_not_make(self):
        every_hour = default_description(spec_from_config(ScheduleSettings(), Path("q.exe")))
        assert "09:00" in every_hour and "18:00" in every_hour
        once = default_description(
            spec_from_config(ScheduleSettings(repeat_for_h=0), Path("q.exe"))
        )
        assert "09:00" in once and "ritenta" not in once


# -------------------------------------------------------------------- register


class TestRegister:
    def test_creates_from_utf16_bom_temp_file_and_cleans_up(self):
        seen: dict = {}

        def create(args: list[str]) -> subprocess.CompletedProcess:
            path = Path(args[args.index("/XML") + 1])
            raw = path.read_bytes()
            seen["bom"] = raw[:2]
            seen["text"] = raw.decode("utf-16")
            seen["path"] = path
            return _ok(args=args)

        runner = FakeRunner(create=create)
        register(_spec(), runner=runner, user_id=USER, description="d")

        (call,) = runner.calls
        assert call[:3] == ["/Create", "/TN", TASK_NAME]
        assert call[3] == "/XML"
        assert call[5:] == ["/F"]
        assert len(call) == 6
        assert seen["bom"] in (b"\xff\xfe", b"\xfe\xff")
        assert seen["text"].lstrip("\ufeff").startswith("<?xml")
        ET.fromstring(seen["text"].lstrip("\ufeff"))
        assert not seen["path"].exists()

    def test_task_name_parameter(self):
        runner = FakeRunner(create=_ok())
        register(_spec(), runner=runner, user_id=USER, task_name="Other Task")
        assert runner.calls[0][2] == "Other Task"

    def test_user_id_defaults_to_domain_and_username(self, monkeypatch):
        monkeypatch.setenv("USERDOMAIN", "CORP")
        monkeypatch.setenv("USERNAME", "mario")
        captured: dict = {}

        def create(args: list[str]) -> subprocess.CompletedProcess:
            captured["xml"] = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            return _ok(args=args)

        register(_spec(), runner=FakeRunner(create=create))
        root = ET.fromstring(captured["xml"].lstrip("\ufeff"))
        assert _text(root, "Principals/Principal/UserId") == "CORP\\mario"
        assert _text(root, "RegistrationInfo/Description")  # a default description exists

    def test_failure_raises_with_output_and_removes_file(self):
        paths: list[Path] = []

        def create(args: list[str]) -> subprocess.CompletedProcess:
            paths.append(Path(args[args.index("/XML") + 1]))
            return subprocess.CompletedProcess(args, 1, stdout="dettagli", stderr="ERRORE: accesso negato")

        with pytest.raises(SchedulerError) as info:
            register(_spec(), runner=FakeRunner(create=create), user_id=USER)
        assert "accesso negato" in str(info.value)
        assert "dettagli" in str(info.value)
        assert not paths[0].exists()


# ---------------------------------------------------------------------- status

TASK_XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-16"?>\r\n'
    f'<Task version="1.2" xmlns="{NS}">\r\n'
    "  <Actions Context=\"Author\">\r\n"
    "    <Exec>\r\n"
    "      <Command>{command}</Command>\r\n"
    "      <Arguments>--sync</Arguments>\r\n"
    "    </Exec>\r\n"
    "  </Actions>\r\n"
    "</Task>\r\n"
)

# Italian-looking verbose CSV: the headers are localised but the columns are positional.
CSV_IT = (
    '"PC-01","\\qtRequestory Sync","23/09/2026 09:00:00","Pronto","Solo interattivo",'
    '"22/09/2026 15:00:01","267009","DOMAIN\\someone","C:\\Tools\\qtRequestory\\qtRequestory.exe --sync",'
    '"N/D","Sincronizza i log","Abilitato","Disabilitato","Arresta il task","01:00:00","Pianificazione dati non disponibile in questo formato.",'
    '"Giornaliero","09:00:00","22/09/2026","N/D","Ogni giorno","N/D","N/D","N/D"\r\n'
)


def _status_runner(command: str, csv_text: str = CSV_IT) -> FakeRunner:
    def query(args: list[str]) -> subprocess.CompletedProcess:
        if "/XML" in args:
            return _ok(TASK_XML_TEMPLATE.format(command=command), args)
        assert args[-4:] == ["/V", "/FO", "CSV", "/NH"], args
        return _ok(csv_text, args)

    return FakeRunner(query=query)


class TestStatus:
    def test_query_failure_means_not_registered(self):
        runner = FakeRunner(query=_fail("ERRORE: Impossibile trovare il file specificato."))
        st = status(Path(r"C:\x\qtRequestory.exe"), runner=runner)
        assert st == TaskStatus(
            registered=False, command=None, args=None, exe_matches=False,
            state=None, next_run=None, last_run=None, last_result=None,
        )
        assert runner.calls == [["/Query", "/TN", TASK_NAME, "/XML", "ONE"]]

    def test_registered_with_matching_exe(self, tmp_path):
        exe = tmp_path / "qtRequestory.exe"
        exe.write_bytes(b"MZ")
        runner = _status_runner(str(exe))
        st = status(exe, runner=runner)
        assert st.registered is True
        assert st.command == exe
        assert st.args == "--sync"
        assert st.exe_matches is True
        assert st.next_run == "23/09/2026 09:00:00"
        assert st.state == "Pronto"
        assert st.last_run == "22/09/2026 15:00:01"
        assert st.last_result == 267009
        assert [c[:3] for c in runner.calls] == [["/Query", "/TN", TASK_NAME]] * 2
        assert runner.calls[1] == ["/Query", "/TN", TASK_NAME, "/V", "/FO", "CSV", "/NH"]

    def test_matching_is_case_and_form_insensitive(self, tmp_path):
        exe = tmp_path / "qtRequestory.exe"
        exe.write_bytes(b"MZ")
        st = status(Path(str(exe).upper()), runner=_status_runner(f'"{exe}"'))
        assert st.exe_matches is True

    def test_mismatching_exe(self, tmp_path):
        st = status(tmp_path / "other.exe", runner=_status_runner(str(tmp_path / "qtRequestory.exe")))
        assert st.registered is True
        assert st.exe_matches is False

    def test_no_current_exe(self, tmp_path):
        st = status(None, runner=_status_runner(str(tmp_path / "qtRequestory.exe")))
        assert st.registered is True
        assert st.exe_matches is False

    def test_unparseable_last_result_and_missing_csv(self, tmp_path):
        exe = tmp_path / "qtRequestory.exe"
        csv_text = CSV_IT.replace('"267009"', '"N/D"')
        st = status(exe, runner=_status_runner(str(exe), csv_text))
        assert st.last_result is None
        assert st.state == "Pronto"

        def query(args):
            return _ok(TASK_XML_TEMPLATE.format(command=str(exe)), args) if "/XML" in args else _fail()

        st = status(exe, runner=FakeRunner(query=query))
        assert st.registered is True
        assert st.state is None and st.next_run is None and st.last_run is None and st.last_result is None

    def test_a_missing_schtasks_is_not_registered_instead_of_an_exception(self, caplog):
        r"""``schtasks`` lives in ``%SystemRoot%\System32``; a PATH that has lost
        that folder makes ``subprocess.run`` raise ``FileNotFoundError``.

        ``SyncPage.__init__`` calls ``status()``, and ``MainWindow._build_page``
        turns any exception from a page factory into "La pagina
        «Sincronizzazione» non e disponibile in questa versione." — the whole
        page gone, over a PATH the user cannot even see. Not knowing whether a
        task is registered is no reason to hide the synchronisation page.
        """
        def boom(args):
            raise FileNotFoundError(2, "Impossibile trovare il file specificato", "schtasks")

        with caplog.at_level(logging.WARNING):
            st = status(Path(r"C:\x\qtRequestory.exe"), runner=FakeRunner(query=boom))
        assert st == NOT_REGISTERED
        assert "schtasks" in caplog.text

    def test_garbled_xml_is_not_registered_instead_of_an_exception(self, caplog):
        """schtasks answered 0 but the output is not a task definition (a
        truncated pipe, an antivirus banner). Same rule: report "nessun task",
        never take the page down with it."""
        runner = FakeRunner(query=_ok("<Task><unclosed>", ["/Query"]))
        with caplog.at_level(logging.WARNING):
            st = status(Path(r"C:\x\qtRequestory.exe"), runner=runner)
        assert st == NOT_REGISTERED
        assert "xml" in caplog.text.lower()

    def test_a_failing_verbose_query_still_reports_the_task(self, tmp_path):
        """The second call only fills the runtime columns: losing it must not
        lose the registration the first call already established."""
        exe = tmp_path / "qtRequestory.exe"

        def query(args):
            if "/XML" in args:
                return _ok(TASK_XML_TEMPLATE.format(command=str(exe)), args)
            raise OSError("pipe chiusa")

        st = status(exe, runner=FakeRunner(query=query))
        assert st.registered is True
        assert (st.state, st.next_run, st.last_run, st.last_result) == (None, None, None, None)

    def test_task_name_parameter(self, tmp_path):
        runner = _status_runner(str(tmp_path / "x.exe"))
        status(None, runner=runner, task_name="Other Task")
        assert all(c[2] == "Other Task" for c in runner.calls)


# ------------------------------------------------------------- unregister/run


class TestUnregisterAndRun:
    def test_unregister_deletes(self):
        runner = FakeRunner(delete=_ok())
        unregister(runner=runner)
        assert runner.calls == [["/Delete", "/TN", TASK_NAME, "/F"]]

    def test_unregister_tolerates_not_found(self):
        runner = FakeRunner(
            delete=_fail("ERRORE: Impossibile trovare il file specificato."),
            query=_fail("ERRORE: Impossibile trovare il file specificato."),
        )
        unregister(runner=runner)  # no exception
        assert runner.calls[0] == ["/Delete", "/TN", TASK_NAME, "/F"]

    def test_unregister_raises_on_other_errors(self):
        runner = FakeRunner(delete=_fail("ERRORE: Accesso negato."), query=_ok("some listing"))
        with pytest.raises(SchedulerError, match="Accesso negato"):
            unregister(runner=runner)

    def test_unregister_task_name_parameter(self):
        runner = FakeRunner(delete=_ok())
        unregister(runner=runner, task_name="Other Task")
        assert runner.calls[0][2] == "Other Task"

    def test_run_now(self):
        runner = FakeRunner(run=_ok())
        run_now(runner=runner)
        assert runner.calls == [["/Run", "/TN", TASK_NAME]]

    def test_run_now_error(self):
        with pytest.raises(SchedulerError, match="ERRORE"):
            run_now(runner=FakeRunner(run=_fail("ERRORE: task non trovato")))


# ---------------------------------------------------------------------- legacy


class TestLegacyTask:
    def test_detect_true(self):
        runner = FakeRunner(query=_ok("listing"))
        assert detect_legacy_task(runner=runner) is True
        assert runner.calls == [["/Query", "/TN", LEGACY_TASK_NAME]]

    def test_detect_false(self):
        assert detect_legacy_task(runner=FakeRunner(query=_fail())) is False

    def test_a_missing_schtasks_means_no_legacy_task(self, caplog):
        """The wizard's third page asks this while it is being built: an
        unusable ``schtasks`` must not take the first-run wizard down."""
        def boom(args):
            raise FileNotFoundError(2, "Impossibile trovare il file specificato", "schtasks")

        with caplog.at_level(logging.WARNING):
            assert detect_legacy_task(runner=FakeRunner(query=boom)) is False
        assert "schtasks" in caplog.text

    def test_remove_calls_delete(self):
        runner = FakeRunner(delete=_ok())
        remove_legacy_task(runner=runner)
        assert runner.calls == [["/Delete", "/TN", LEGACY_TASK_NAME, "/F"]]

    def test_remove_tolerates_not_found(self):
        remove_legacy_task(runner=FakeRunner(delete=_fail("ERRORE: Impossibile trovare"), query=_fail()))

    def test_remove_raises_on_other_errors(self):
        with pytest.raises(SchedulerError):
            remove_legacy_task(runner=FakeRunner(delete=_fail("ERRORE: Accesso negato."), query=_ok()))


# --------------------------------------------------------- location heuristics


class TestUnstableLocation:
    def test_temp(self, tmp_path, monkeypatch):
        temp = tmp_path / "Temp"
        monkeypatch.setenv("TEMP", str(temp))
        monkeypatch.setenv("TMP", str(temp))
        reason = is_unstable_location(temp / "qtRequestory.exe")
        assert reason and "tempor" in reason.lower()

    def test_downloads(self):
        reason = is_unstable_location(Path(r"C:\Users\mario\Downloads\qtRequestory.exe"))
        assert reason and "Downloads" in reason

    def test_unc(self):
        reason = is_unstable_location(Path(r"\\fileserver\share\tools\qtRequestory.exe"))
        assert reason and "rete" in reason.lower()

    def test_onedrive(self):
        reason = is_unstable_location(Path(r"C:\Users\mario\OneDrive - Company\Tools\qtRequestory.exe"))
        assert reason and "OneDrive" in reason
        assert is_unstable_location(Path(r"C:\Users\mario\OneDrive\qtRequestory.exe"))

    def test_stable(self):
        assert is_unstable_location(Path(r"C:\Tools\qtRequestory\qtRequestory.exe")) is None
        assert is_unstable_location(Path(r"C:\Users\mario\AppData\Local\Programs\qtRequestory\qtRequestory.exe")) is None
        # "Temp"/"Downloads" as a prefix of a longer folder name is not a match
        assert is_unstable_location(Path(r"C:\Temporary Tools\qtRequestory.exe")) is None


def test_current_exe_for_task_uses_paths_module(monkeypatch):
    assert scheduler.current_exe_for_task() is None  # running from source
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert scheduler.current_exe_for_task() == Path(sys.executable).resolve()


def test_run_schtasks_is_the_default_runner():
    assert register.__kwdefaults__["runner"] is scheduler.run_schtasks
    assert status.__kwdefaults__["runner"] is scheduler.run_schtasks


# ----------------------------------------------------------------- integration


@pytest.mark.skipif(not os.environ.get("QTREQ_INTEGRATION"), reason="set QTREQ_INTEGRATION=1 to touch the real Task Scheduler")
def test_real_round_trip():
    name = TASK_NAME + " (pytest)"
    exe = Path(sys.executable)
    try:
        register(TaskSpec(exe=exe, args="-c pass"), task_name=name, description="qtRequestory pytest round trip")
        st = status(exe, task_name=name)
        assert st.registered is True
        assert st.exe_matches is True
        assert st.args == "-c pass"
        assert st.state
    finally:
        unregister(task_name=name)
    assert status(exe, task_name=name).registered is False
