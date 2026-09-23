"""cli.py — argument parsing and dispatch for every mode.

Two kinds of test live here:

* in-process ones that call ``cli.main`` directly (fast, and able to inspect
  what was written);
* a handful of **subprocess** ones that assert the headless modes never import
  Qt. That guarantee cannot be checked in-process: the UI suite runs in the
  same interpreter and would already have ``PySide6`` in ``sys.modules``,
  making the assertion silently vacuous.
"""
from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from qtrequestory import __version__, cli
from qtrequestory.core import opener, scheduler
from qtrequestory.core.config import (
    Config,
    Environment,
    ScheduleSettings,
    default_config,
    load_config,
    save_config,
)
from qtrequestory.core.events import CancelToken, LoggingSink
from qtrequestory.core.jobs import JobReport
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import TaskStatus
from tests.conftest import (
    FDI_A,
    FDI_B,
    KEY_CTE,
    KEY_EMAIL,
    KEY_SINT,
    Mirror,
    StubServer,
    autoindex_html,
    entry_name,
    make_daily_file,
    synthetic_body,
)

SRC = Path(__file__).resolve().parents[1] / "src"


# --------------------------------------------------------- no real console ---


class _NoParentConsole:
    """Answers exactly like a process with no parent console: this is what
    protects every other test in this module from ``_attach_parent_console``
    reaching the real Windows API and stealing ``capsys``'s captured stdout.
    """

    def AttachConsole(self, _pid: int) -> int:
        return 0


@pytest.fixture(autouse=True)
def _stub_windows_console(monkeypatch):
    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _NoParentConsole()})())


# ------------------------------------------------------------------ helpers ---


def _write_config(home: Path, mirror_root: Path, *, envs: list[str] = (), **overrides) -> Path:
    """A real ``config.json`` under ``home`` so no test touches the user's own."""
    cfg = default_config()
    cfg.mirror_root = mirror_root
    cfg.environments = [Environment(name=e, url=f"http://127.0.0.1:1/{e}/") for e in envs]
    # Never the real %TEMP%\qtrequestory-calls: tests must not leave files there,
    # and a leftover from an earlier run would push --find onto its alt name.
    cfg.output_dir = home / "out"
    for key, value in overrides.items():
        setattr(cfg, key, value)
    home.mkdir(parents=True, exist_ok=True)
    save_config(cfg, home / "config.json")
    return home / "config.json"


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    """An isolated ``QTREQUESTORY_HOME`` with a config pointing at a temp mirror."""
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    return app_home


@pytest.fixture
def indexed(tmp_path: Path, monkeypatch, mirror: Mirror) -> Path:
    """``QTREQUESTORY_HOME`` whose configured mirror is the synthetic one, indexed."""
    app_home = tmp_path / "home"
    _write_config(app_home, mirror.root, envs=["coll", "svil"])
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    assert cli.main(["--index"]) == 0
    return app_home


class _RecordingJob:
    """Stands in for ``run_sync_job`` / ``run_index_job``."""

    def __init__(self, exit_code: int = 0) -> None:
        self.exit_code = exit_code
        self.calls: list[tuple[Config, dict]] = []

    def __call__(self, config: Config, **kw) -> JobReport:
        self.calls.append((config, kw))
        return JobReport(sync=None, indexed_files=0, exit_code=self.exit_code)

    @property
    def kwargs(self) -> dict:
        assert len(self.calls) == 1, f"expected one call, got {len(self.calls)}"
        return self.calls[0][1]


class _FakeScheduler:
    """The scheduler surface ``--task`` uses, with nothing behind it."""

    def __init__(self, status: TaskStatus | None = None, *, unstable: str | None = None,
                 exe: Path | None = None, error: Exception | None = None) -> None:
        self._status = status or scheduler.NOT_REGISTERED
        self._unstable = unstable
        self._exe = exe
        self._error = error
        self.calls: list[str] = []

    def status(self) -> TaskStatus:
        self.calls.append("status")
        return self._status

    def register(self) -> None:
        self.calls.append("register")
        if self._error is not None:
            raise self._error

    def unregister(self) -> None:
        self.calls.append("unregister")

    def run_now(self) -> None:
        self.calls.append("run_now")

    def exe_path(self) -> Path | None:
        return self._exe

    def unstable_location_reason(self) -> str | None:
        return self._unstable


# ------------------------------------------------------------ no Qt, ever ---

_PROBE = """
import json, sys
from qtrequestory.cli import main
code = main({argv!r})
print("PROBE" + json.dumps({{"code": code, "qt": [m for m in sys.modules if m.startswith("PySide6")]}}))
"""


def _headless_subprocess(argv: list[str], home: Path) -> dict:
    """Run ``cli.main(argv)`` in a fresh interpreter; report exit code and Qt modules."""
    env = {**os.environ, "PYTHONPATH": str(SRC), "QTREQUESTORY_HOME": str(home)}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(argv=argv)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("PROBE"))
    return json.loads(line[len("PROBE"):])


@pytest.mark.parametrize("argv", [
    ["--sync"],
    ["--index"],
    ["--find", "-e", "coll", "-f", "deadbeef"],
])
def test_a_headless_mode_never_imports_qt(tmp_path: Path, argv: list[str]):
    """``--task`` is covered in-process below: a subprocess would call schtasks."""
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror")
    probe = _headless_subprocess(argv, app_home)
    assert probe["qt"] == []


def test_task_status_never_imports_qt_either(home: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: _FakeScheduler())
    before = {m for m in sys.modules if m.startswith("PySide6")}
    cli.main(["--task", "status"])
    assert {m for m in sys.modules if m.startswith("PySide6")} == before


# ------------------------------------------------------------ console attach ---
#
# Important #14: a windowed build (``console=False``) has ``sys.stdout`` ==
# ``None``, so every headless mode's print used to vanish even when launched
# from an interactive terminal. These stub ``ctypes.windll`` themselves (never
# a real console, per the module-level ``_stub_windows_console`` fixture that
# protects every OTHER test here from the real Windows API).


def test_attach_console_is_a_no_op_without_a_parent_console():
    """The scheduled task's case, and every other test in this module (the
    autouse stub answers 0): the streams must be left exactly alone."""
    old_out, old_err = sys.stdout, sys.stderr
    cli._attach_parent_console(["--sync"])
    assert sys.stdout is old_out
    assert sys.stderr is old_err


def test_attach_console_reopens_stdout_and_stderr_on_conout(monkeypatch):
    class _Attached:
        def AttachConsole(self, pid: int) -> int:
            assert pid == cli._ATTACH_PARENT_PROCESS
            return 1  # non-zero: there IS a parent console

    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _Attached()})())
    fake_out, fake_err = io.StringIO(), io.StringIO()
    opened = iter([fake_out, fake_err])
    monkeypatch.setattr(cli, "_open_conout", lambda: next(opened))

    old_out, old_err = sys.stdout, sys.stderr
    try:
        cli._attach_parent_console(["--sync"])
        assert sys.stdout is fake_out
        assert sys.stderr is fake_err
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def test_attach_console_leaves_both_streams_untouched_if_reopening_either_fails(monkeypatch):
    """Fix round 1 (Minor): both ``CONOUT$`` handles are opened into locals
    and assigned only once BOTH succeeded — a failure reopening the SECOND
    one (stderr) must not leave stdout pointing at a console while stderr
    stays wherever it was."""
    class _Attached:
        def AttachConsole(self, pid: int) -> int:
            return 1

    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _Attached()})())
    fake_out = io.StringIO()
    calls: list[int] = []

    def flaky_open():
        calls.append(len(calls))
        if len(calls) == 1:
            return fake_out
        raise OSError("no second console handle")

    monkeypatch.setattr(cli, "_open_conout", flaky_open)

    old_out, old_err = sys.stdout, sys.stderr
    try:
        cli._attach_parent_console(["--sync"])  # must not raise
        assert sys.stdout is old_out, "must not keep the leaked first handle"
        assert sys.stderr is old_err
    finally:
        sys.stdout, sys.stderr = old_out, old_err


@pytest.mark.parametrize("argv", [["--sync"], ["--index"], ["--find"], ["--task", "status"], ["--version"]])
def test_attach_console_is_attempted_for_every_headless_mode(monkeypatch, argv: list[str]):
    calls: list[int] = []

    class _Recording:
        def AttachConsole(self, pid: int) -> int:
            calls.append(pid)
            return 0

    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _Recording()})())
    cli._attach_parent_console(argv)
    assert calls == [cli._ATTACH_PARENT_PROCESS]


def test_attach_console_is_skipped_for_the_gui(monkeypatch):
    calls: list[int] = []

    class _Recording:
        def AttachConsole(self, pid: int) -> int:
            calls.append(pid)
            return 1

    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _Recording()})())
    cli._attach_parent_console([])
    assert calls == [], "no headless flag: the GUI must never touch the console API"


def test_attach_console_tolerates_a_missing_windll(monkeypatch):
    """Off Windows (or an exotic sandbox) ``ctypes`` may have no ``windll`` at
    all; merely accessing the attribute must not raise and reach the caller."""
    monkeypatch.delattr(cli.ctypes, "windll", raising=False)
    old_out, old_err = sys.stdout, sys.stderr
    cli._attach_parent_console(["--sync"])  # must not raise
    assert sys.stdout is old_out and sys.stderr is old_err


def test_attach_console_is_wired_into_main_before_guard_std_streams(home: Path, monkeypatch):
    """The scheduled windowed ``--sync`` must keep working exactly as before:
    with the autouse "no parent console" stub, ``main`` must still reach
    ``_guard_std_streams`` and run the job normally."""
    monkeypatch.setattr(cli, "run_sync_job",
                        lambda config, **kw: JobReport(sync=None, indexed_files=0, exit_code=0))
    assert cli.main(["--sync"]) == 0


def test_attach_console_success_reaches_stdout_through_main(home: Path, monkeypatch):
    class _Attached:
        def AttachConsole(self, pid: int) -> int:
            return 1

    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _Attached()})())
    fake_out, fake_err = io.StringIO(), io.StringIO()
    opened = iter([fake_out, fake_err])
    monkeypatch.setattr(cli, "_open_conout", lambda: next(opened))
    monkeypatch.setattr(cli, "run_sync_job",
                        lambda config, **kw: JobReport(sync=None, indexed_files=0, exit_code=0))

    old_out, old_err = sys.stdout, sys.stderr
    try:
        assert cli.main(["--sync"]) == 0
        assert sys.stdout is fake_out
    finally:
        sys.stdout, sys.stderr = old_out, old_err


# --------------------------------------------------------------- --version ---


def test_version_prints_the_version(capsys):
    assert cli.main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


# ------------------------------------------------------------------ --sync ---


def test_sync_runs_the_job_with_the_requested_environments(home: Path, monkeypatch):
    job = _RecordingJob(exit_code=1)
    monkeypatch.setattr(cli, "run_sync_job", job)

    assert cli.main(["--sync", "--env", "svil", "--env", "coll", "--force"]) == 1

    assert job.kwargs["envs"] == ["svil", "coll"]
    assert job.kwargs["force"] is True
    assert job.kwargs["dry_run"] is False
    assert isinstance(job.kwargs["sink"], LoggingSink)
    assert isinstance(job.kwargs["cancel"], CancelToken)


def test_sync_without_env_syncs_everything(home: Path, monkeypatch):
    job = _RecordingJob()
    monkeypatch.setattr(cli, "run_sync_job", job)

    assert cli.main(["--sync", "--dry-run"]) == 0
    assert job.kwargs["envs"] is None
    assert job.kwargs["dry_run"] is True


def test_sync_configures_logging_and_writes_the_sync_log(home: Path):
    """End to end against a port nothing listens on: exit 2 and one quiet line."""
    cfg = load_config(home / "config.json")
    cfg.environments = [Environment(name="svil", url="http://127.0.0.1:1/")]
    save_config(cfg, home / "config.json")

    assert cli.main(["--sync"]) == 2

    sync_log = (home / "logs" / "sync.log").read_text(encoding="utf-8")
    assert "svil" in sync_log
    assert "codice di uscita 2" in sync_log
    assert (home / "logs" / "app.log").exists()


def test_sync_dry_run_lists_the_files_it_would_download(tmp_path: Path, monkeypatch, capsys,
                                                          stub_server: StubServer):
    """Minor P1: ``--sync --dry-run`` used to print nothing at all — the
    engine skips the transfer, ``sync.log`` only gets the "anteprima" summary
    lines, and ``LoggingSink`` drops ``FileSkipped``. The CLI is the only
    place left that can show the old script's file-by-file listing."""
    app_home = tmp_path / "home"
    mirror = tmp_path / "mirror"
    cfg = default_config()
    cfg.mirror_root = mirror
    cfg.environments = [Environment(name="coll", url=stub_server.url + "/coll/")]
    cfg.output_dir = app_home / "out"
    app_home.mkdir(parents=True)
    save_config(cfg, app_home / "config.json")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    size = 1_048_576  # exactly 1 MB, so the formatted output is unambiguous
    stub_server.add("/coll/", autoindex_html([("20260921.txt", "21-Sep-2026 18:30", size)]))
    stub_server.add("/coll/20260921.txt", b"x" * size)

    assert cli.main(["--sync", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "[dry-run] scaricherei 20260921.txt (1 MB) -> " in out
    assert str(mirror / "coll" / "2026" / "09" / "20260921.txt") in out
    assert not (mirror / "coll").exists(), "dry-run must not touch the mirror"


def test_sync_with_an_unconfigured_environment_says_so_and_exits_2(home: Path, capsys):
    """Minor P2, the ``--sync -e`` half: the real engine, not a mock — a typo
    must be told apart from a config problem or a network failure."""
    cfg = load_config(home / "config.json")
    cfg.environments = [Environment(name="svil", url="http://127.0.0.1:1/")]
    save_config(cfg, home / "config.json")

    assert cli.main(["--sync", "--env", "colll"]) == 2

    out = capsys.readouterr().out
    assert "ambiente sconosciuto: 'colll' (configurati: svil)" in out


# ---------------------------------------------------- configuration gate ---


def test_headless_modes_refuse_to_run_against_an_unset_mirror_root(tmp_path: Path, monkeypatch, capsys):
    """Minor M3: an emptied ``mirror_root`` must stop the run, not silently
    resolve to the default (once the live installed mirror)."""
    app_home = tmp_path / "home"
    app_home.mkdir(parents=True)
    (app_home / "config.json").write_text('{"schema_version": 1, "mirror_root": ""}', encoding="utf-8")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    monkeypatch.setattr(cli, "run_sync_job", _RecordingJob())

    assert cli.main(["--sync"]) == 2

    out = capsys.readouterr().out
    assert "La cartella dei log non è impostata" in out


def test_headless_modes_refuse_to_run_against_a_relative_mirror_root(tmp_path: Path, monkeypatch, capsys):
    app_home = tmp_path / "home"
    app_home.mkdir(parents=True)
    (app_home / "config.json").write_text(
        '{"schema_version": 1, "mirror_root": "relativo"}', encoding="utf-8"
    )
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    monkeypatch.setattr(cli, "run_index_job", _RecordingJob())

    assert cli.main(["--index"]) == 2

    out = capsys.readouterr().out
    assert "percorso completo" in out


def test_a_first_run_sync_is_never_blocked_by_the_configuration_gate(tmp_path: Path, monkeypatch):
    """The wizard's blank state (no config.json at all yet) must not be
    mistaken for the M3 bug: ``load_config`` hands back the real default
    ``mirror_root``, which ``validate`` accepts."""
    app_home = tmp_path / "home"
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    monkeypatch.setattr(cli, "run_sync_job", _RecordingJob())

    assert cli.main(["--sync"]) == 0
    assert not (app_home / "config.json").exists()


def test_the_task_action_is_not_gated_by_config_validation(tmp_path: Path, monkeypatch):
    """``--task`` never touches ``mirror_root``; a broken one must not stop a
    user from at least removing/inspecting the scheduled task."""
    app_home = tmp_path / "home"
    app_home.mkdir(parents=True)
    (app_home / "config.json").write_text('{"schema_version": 1, "mirror_root": ""}', encoding="utf-8")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    fake = _FakeScheduler()
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: fake)

    assert cli.main(["--task", "status"]) == 1  # not registered, not a config error
    assert fake.calls == ["status"]


def test_an_invalid_log_level_does_not_block_sync(tmp_path: Path, monkeypatch, capsys):
    """Fix round 1 (Important): the pre-run gate is scoped to ``mirror_root``
    only. Before this fix round it called the full ``validate()``, so a typo
    in ``log_level`` — which ``configure_logging`` already falls back from to
    INFO on its own — turned into a hard exit-2 refusal it never was before
    this task."""
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror", log_level="VERBOSE")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    job = _RecordingJob()
    monkeypatch.setattr(cli, "run_sync_job", job)

    assert cli.main(["--sync"]) == 0

    assert len(job.calls) == 1
    assert "Errore di configurazione" not in capsys.readouterr().out


def test_a_malformed_schedule_does_not_block_sync_or_index(tmp_path: Path, monkeypatch, capsys):
    """Same fix: a bad ``schedule`` block only matters to Impostazioni/the
    scheduled task registration, never to ``--sync``/``--index`` themselves."""
    bad_schedule = ScheduleSettings(start_time="not-a-time", repeat_every_h=99, repeat_for_h=99)
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror", schedule=bad_schedule)
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    sync_job = _RecordingJob()
    monkeypatch.setattr(cli, "run_sync_job", sync_job)

    assert cli.main(["--sync"]) == 0
    assert len(sync_job.calls) == 1

    index_job = _RecordingJob()
    monkeypatch.setattr(cli, "run_index_job", index_job)

    assert cli.main(["--index"]) == 0
    assert len(index_job.calls) == 1
    assert "Errore di configurazione" not in capsys.readouterr().out


def test_find_is_not_blocked_by_a_bad_log_level_or_schedule(tmp_path: Path, monkeypatch, capsys):
    """``--find`` DOES depend on ``mirror_root`` (``Config.index_path`` is
    derived from it) but not on ``log_level``/``schedule``; the environment
    is genuinely just not indexed yet, so this must behave exactly like
    ``test_find_says_when_the_environment_was_never_indexed``, not like the
    mirror_root gate."""
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror", envs=["coll"],
                  log_level="VERBOSE", schedule=ScheduleSettings(start_time="nope"))
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))

    assert cli.main(["--find", "-e", "coll", "-f", FDI_A[:8], "--no-open"]) == 1

    out = capsys.readouterr().out
    assert cli.NOTHING_FOUND in out
    assert "Errore di configurazione" not in out


def test_headless_modes_still_refuse_an_unset_mirror_root_after_the_gate_was_scoped_down(
    tmp_path: Path, monkeypatch, capsys,
):
    """The point of scoping the gate down to ``mirror_root_errors``: it must
    keep catching exactly the case it exists for, even alongside other,
    now-ignored problems."""
    app_home = tmp_path / "home"
    app_home.mkdir(parents=True)
    (app_home / "config.json").write_text(
        json.dumps({"schema_version": 1, "mirror_root": "", "log_level": "VERBOSE"}), encoding="utf-8",
    )
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    monkeypatch.setattr(cli, "run_sync_job", _RecordingJob())

    assert cli.main(["--sync"]) == 2
    assert "La cartella dei log non è impostata" in capsys.readouterr().out


def test_ctrl_c_cancels_the_running_job_and_exits_3(home: Path, monkeypatch):
    """The real Ctrl+C path: the installed handler only sets the token.

    Python raises no ``KeyboardInterrupt`` while our handler is installed, so
    the job must see the cancellation, unwind through its own check points
    (which is what releases the lock) and report ``EXIT_CANCELLED``. The
    previous handler has to be back afterwards.
    """
    seen: list[CancelToken] = []

    def job_that_gets_interrupted(config, **kw):
        cancel = kw["cancel"]
        seen.append(cancel)
        assert signal.getsignal(signal.SIGINT) is not before, "the handler must be installed"
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)  # the Ctrl+C itself
        assert cancel.is_set(), "the handler cancels instead of raising"
        return JobReport(sync=None, indexed_files=0, exit_code=3)

    before = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(cli, "run_sync_job", job_that_gets_interrupted)

    assert cli.main(["--sync"]) == 3
    assert seen[0].is_set() is True
    assert signal.getsignal(signal.SIGINT) is before, "the previous handler is restored"


def test_a_keyboard_interrupt_that_escapes_still_exits_3(home: Path, monkeypatch):
    """The fallback: no handler could be installed (``main`` off the main thread)."""
    def interrupted(config, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_sync_job", interrupted)
    assert cli.main(["--sync"]) == 3


def test_cli_sync_logs_unexpected_exceptions_and_exits_1(home: Path, monkeypatch):
    """A windowed exe (``console=False``) has nowhere to show an unhandled
    traceback: it must be logged to ``sync.log`` and the process must exit
    cleanly with code 1, never propagate and pop a PyInstaller crash window."""
    def boom(config, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "run_sync_job", boom)

    assert cli.main(["--sync"]) == 1

    sync_log = (home / "logs" / "sync.log").read_text(encoding="utf-8")
    assert "boom" in sync_log
    assert "Traceback" in sync_log


# ----------------------------------------------------------------- --index ---


def test_index_passes_rebuild_and_returns_the_exit_code(home: Path, monkeypatch):
    job = _RecordingJob(exit_code=1)
    monkeypatch.setattr(cli, "run_index_job", job)

    assert cli.main(["--index", "--rebuild", "--env", "coll"]) == 1
    assert job.kwargs["full_rebuild"] is True
    assert job.kwargs["envs"] == ["coll"]


def test_index_really_indexes_the_mirror(tmp_path: Path, monkeypatch, mirror: Mirror):
    app_home = tmp_path / "home"
    _write_config(app_home, mirror.root, envs=["coll", "svil"])
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))

    assert cli.main(["--index"]) == 0
    assert (mirror.root / ".qtrequestory" / "index.sqlite").exists()


# ------------------------------------------------------------------ --find ---


def test_find_writes_the_pure_pretty_body_and_prints_the_path(indexed: Path, capsys):
    code = cli.main(["--find", "-e", "coll", "-f", FDI_A[:8],
                     "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"])
    assert code == 0

    out = capsys.readouterr().out
    written = Path(out.splitlines()[-1].split("scritto:", 1)[1].strip())
    text = written.read_bytes().decode("utf-8")
    assert text.startswith('{\n    "documents": [')
    assert json.loads(text)["dossier"]["id"].startswith("dossier-")
    assert b"\r\n" not in written.read_bytes()


def test_find_names_the_file_after_day_fdi_and_key(indexed: Path, capsys):
    cli.main(["--find", "-e", "coll", "-f", FDI_A[:8], "-k", KEY_CTE,
              "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"])
    out = capsys.readouterr().out
    assert f"20260918_{FDI_A}_{KEY_CTE}.json" in out


def test_find_by_fdi_takes_the_entry_with_the_whole_pratica(tmp_path: Path, monkeypatch, capsys):
    """The legacy rule: most ``documents`` wins, not the newest entry.

    Important #13: this used to pass for the wrong reason. ``search`` orders
    ties by ``request_date DESC, seq DESC``, and the ``mirror`` fixture's
    default ``request_date`` (a fixed timestamp, not ``None`` — see
    ``docs/DESIGN-core.md``) made every FDI_A entry on 2026-09-18 tie on date,
    so the *query* order already happened to put the 5-document entry first —
    ``pick_best``'s ``prefer_most_documents`` was never actually exercised, and
    mutating ``cli.py``'s ``prefer_most_documents=bool(fdi and not key)`` to
    ``False`` did not turn this test red.

    Here the 5-document entry is given an OLDER ``requestDate`` than the
    1-document one on the same day, so newest-first alone would hand out the
    1-document body instead. See task-7-report.md for the by-hand mutation
    check this pins.
    """
    app_home = tmp_path / "home"
    mirror_root = tmp_path / "mirror"
    make_daily_file(mirror_root, "coll", date(2026, 9, 18), [
        (entry_name(FDI_A, KEY_EMAIL, "1a2b3c0200000031"),
         synthetic_body(FDI_A, KEY_EMAIL, ndocs=5, request_date="2026-09-18T08:00:00.000Z")),
        (entry_name(FDI_A, KEY_CTE, "1a2b3c0200000032"),
         synthetic_body(FDI_A, KEY_CTE, ndocs=1, request_date="2026-09-18T12:00:00.000Z")),
    ])
    _write_config(app_home, mirror_root, envs=["coll"])
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    assert cli.main(["--index"]) == 0

    cli.main(["--find", "-e", "coll", "-f", FDI_A[:8],
              "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"])
    out = capsys.readouterr().out
    # Two spaces before the parenthesis: the legacy script's exact shape.
    assert f"trovato in 20260918.txt: {FDI_A}_{KEY_EMAIL}_1a2b3c0200000031.json  (" in out
    assert "5 documenti" in out
    assert "altre 1 entry" in out


def test_find_with_a_key_keeps_the_query_order(indexed: Path, capsys):
    """An explicit key already names the entry: no document-count reshuffle."""
    cli.main(["--find", "-e", "coll", "-k", KEY_SINT,
              "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"])
    out = capsys.readouterr().out
    assert f"{FDI_B}_{KEY_SINT}" in out.splitlines()[1]


def test_find_reports_the_other_entries_of_the_same_day(indexed: Path, capsys):
    cli.main(["--find", "-e", "coll", "-f", FDI_A[:8],
              "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"])
    out = capsys.readouterr().out
    assert "altre 2 entry" in out
    assert KEY_EMAIL in out


def test_find_exits_1_when_nothing_matches(indexed: Path, capsys):
    assert cli.main(["--find", "-e", "coll", "-f", "ffffffff",
                     "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"]) == 1
    assert "nessuna chiamata trovata" in capsys.readouterr().out


def test_find_says_when_the_environment_was_never_indexed(tmp_path: Path, monkeypatch, capsys):
    """"Nothing found" would be a lie on an index that holds nothing at all.

    ``coll`` IS configured here (unlike the ``home`` fixture's empty list) but
    never synced — the "esegui --sync" advice is only correct for a real,
    simply-not-yet-indexed environment; a name nobody configured gets the
    different message asserted below.
    """
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror", envs=["coll"])
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))

    assert cli.main(["--find", "-e", "coll", "-f", FDI_A[:8], "--no-open"]) == 1
    out = capsys.readouterr().out
    assert cli.NOTHING_FOUND in out
    assert "esegui --sync" in out


def test_find_with_an_unconfigured_environment_says_so(home: Path, capsys):
    """Minor P2: ``--find -e colll`` used to say "esegui --sync", which is
    actively wrong advice for a name that is not even a configured
    environment — syncing "colll" is not a thing that exists to do."""
    assert cli.main(["--find", "-e", "colll", "-f", FDI_A[:8], "--no-open"]) == 2
    out = capsys.readouterr().out
    assert "ambiente sconosciuto: 'colll'" in out
    assert cli.NOTHING_FOUND not in out
    assert "esegui --sync" not in out


def test_find_does_not_blame_the_index_when_it_has_data(indexed: Path, capsys):
    assert cli.main(["--find", "-e", "coll", "-f", "ffffffff",
                     "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"]) == 1
    out = capsys.readouterr().out
    assert cli.NOTHING_FOUND in out
    assert "esegui --sync" not in out


def test_find_writes_where_out_says(indexed: Path, tmp_path: Path, capsys):
    target = tmp_path / "altrove" / "chiamata.json"
    assert cli.main(["--find", "-e", "coll", "-k", KEY_CTE, "--out", str(target),
                     "--from", "2026-08-01", "--to", "2026-09-30", "--no-open"]) == 0
    assert target.read_text(encoding="utf-8").startswith('{\n    "documents": [')


def test_find_opens_the_editor_unless_no_open(indexed: Path, monkeypatch, capsys):
    opened: list[list[Path]] = []
    monkeypatch.setattr(opener, "open_in_editor",
                        lambda paths, editor, **kw: (opened.append(list(paths)), "editor")[1])

    cli.main(["--find", "-e", "coll", "-f", FDI_B[:8], "--from", "2026-08-01", "--to", "2026-09-30"])
    assert len(opened) == 1

    cli.main(["--find", "-e", "coll", "-f", FDI_B[:8], "--from", "2026-08-01",
              "--to", "2026-09-30", "--no-open"])
    assert len(opened) == 1


def test_find_days_sets_the_window_back_from_today(indexed: Path, monkeypatch, capsys):
    """Without --from/--to the window is ``--days`` back from today."""
    seen: list[tuple[date | None, date | None]] = []
    real_search = cli.facade.IndexService.search

    def spy(self, query):
        seen.append((query.day_from, query.day_to))
        return real_search(self, query)

    monkeypatch.setattr(cli.facade.IndexService, "search", spy)
    cli.main(["--find", "-e", "coll", "-f", FDI_A[:8], "--days", "400", "--no-open"])
    day_from, day_to = seen[0]
    assert (day_to - day_from).days == 400


def test_find_needs_exactly_one_environment(indexed: Path):
    with pytest.raises(SystemExit):
        cli.main(["--find", "-f", FDI_A[:8]])
    with pytest.raises(SystemExit):
        cli.main(["--find", "-e", "coll", "-e", "svil", "-f", FDI_A[:8]])


def test_find_needs_an_fdi_or_a_key(indexed: Path):
    with pytest.raises(SystemExit):
        cli.main(["--find", "-e", "coll"])


@pytest.mark.parametrize("argv", [
    ["--sync", "--days", "0"],       # falsy but GIVEN: must not slip through
    ["--sync", "--rebuild"],
    ["--index", "--force"],
    ["--index", "--no-open"],
    ["--version", "--rebuild"],      # --version must not skip the check either
    ["--version", "--out", "x.json"],
])
def test_an_option_of_another_mode_is_refused_not_ignored(home: Path, argv: list[str]):
    """Accepting --rebuild on a --sync would tell the user the index was rebuilt."""
    with pytest.raises(SystemExit):
        cli.main(argv)


# ------------------------------------------------------------------ --task ---


def test_task_install_registers_and_warns_about_an_unstable_location(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler(unstable="L'eseguibile si trova in Downloads: spostalo.")
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: fake)

    assert cli.main(["--task", "install"]) == 0
    assert fake.calls == ["register"]
    out = capsys.readouterr().out
    assert "Downloads" in out


def test_task_install_reports_a_scheduler_failure(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler(error=scheduler.SchedulerError("schtasks: accesso negato"))
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: fake)

    assert cli.main(["--task", "install"]) == 1
    assert "accesso negato" in capsys.readouterr().out


def test_task_remove_and_run(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler()
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: fake)

    assert cli.main(["--task", "remove"]) == 0
    assert cli.main(["--task", "run"]) == 0
    assert fake.calls == ["unregister", "run_now"]


def test_task_status_prints_the_fields_in_italian(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler(TaskStatus(
        registered=True, command=Path(r"C:\Tools\qtRequestory.exe"), args="--sync",
        exe_matches=True, state="Pronto", next_run="23/09/2026 09:00:00",
        last_run="22/09/2026 09:00:00", last_result=0,
    ))
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: fake)

    assert cli.main(["--task", "status"]) == 0
    out = capsys.readouterr().out
    assert "Registrata: sì" in out
    assert "qtRequestory.exe" in out
    assert "Stato: Pronto" in out
    assert "Prossima esecuzione: 23/09/2026 09:00:00" in out
    assert "Ultimo esito: 0" in out


def test_task_status_says_when_nothing_is_registered(home: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scheduler_service", lambda _config: _FakeScheduler())
    assert cli.main(["--task", "status"]) == 1
    assert "Registrata: no" in capsys.readouterr().out


# ---------------------------------------------------------------- --config ---


def test_config_overrides_the_configuration_file(tmp_path: Path, monkeypatch):
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "unused")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    elsewhere = tmp_path / "altro.json"
    cfg = default_config()
    cfg.mirror_root = tmp_path / "chosen"
    save_config(cfg, elsewhere)

    job = _RecordingJob()
    monkeypatch.setattr(cli, "run_index_job", job)
    assert cli.main(["--config", str(elsewhere), "--index"]) == 0
    assert job.calls[0][0].mirror_root == tmp_path / "chosen"


def test_a_headless_run_never_creates_the_configuration(tmp_path: Path, monkeypatch):
    """Deferred fix 1: a first ``--sync`` must not make the wizard disappear."""
    app_home = tmp_path / "home"
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    monkeypatch.setattr(cli, "run_sync_job", _RecordingJob())

    assert cli.main(["--sync"]) == 0
    assert not (app_home / "config.json").exists()


# -------------------------------------------------------------------- GUI ---


def test_no_argument_starts_the_gui_with_the_real_services(home: Path, monkeypatch):
    seen: list = []
    monkeypatch.setattr(cli, "_start_gui", lambda paths: (seen.append(paths), 7)[1])
    assert cli.main([]) == 7
    assert seen[0].config_file == home / "config.json"


def test_the_gui_honours_the_config_override(tmp_path: Path, monkeypatch):
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror")
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    elsewhere = tmp_path / "altro.json"
    save_config(default_config(), elsewhere)

    seen: list[AppPaths] = []
    monkeypatch.setattr(cli, "_start_gui", lambda paths: (seen.append(paths), 0)[1])
    assert cli.main(["--config", str(elsewhere)]) == 0
    assert seen[0].config_file == elsewhere


def test_index_with_an_unconfigured_environment_says_so_and_exits_2(home: Path, capsys):
    """Final review #4: ``--index -e <typo>`` exits 2 like --sync/--find."""
    cfg = load_config(home / "config.json")
    cfg.environments = [Environment(name="svil", url="http://127.0.0.1:1/")]
    save_config(cfg, home / "config.json")

    assert cli.main(["--index", "--env", "colll"]) == 2

    assert "ambiente sconosciuto: 'colll' (configurati: svil)" in capsys.readouterr().out
