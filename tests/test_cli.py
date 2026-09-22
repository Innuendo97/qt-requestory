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

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from qtrequestory import __version__, cli
from qtrequestory.core import opener, scheduler
from qtrequestory.core.config import Config, Environment, default_config, load_config, save_config
from qtrequestory.core.events import CancelToken, LoggingSink
from qtrequestory.core.jobs import JobReport
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import TaskStatus
from tests.conftest import FDI_A, FDI_B, KEY_CTE, KEY_EMAIL, Mirror

SRC = Path(__file__).resolve().parents[1] / "src"

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
    monkeypatch.setattr(cli, "scheduler_service", lambda: _FakeScheduler())
    before = {m for m in sys.modules if m.startswith("PySide6")}
    cli.main(["--task", "status"])
    assert {m for m in sys.modules if m.startswith("PySide6")} == before


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
    assert "exit 2" in sync_log
    assert (home / "logs" / "app.log").exists()


def test_ctrl_c_during_the_sync_exits_3(home: Path, monkeypatch):
    def interrupted(config, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_sync_job", interrupted)
    assert cli.main(["--sync"]) == 3


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


# ------------------------------------------------------------------ --task ---


def test_task_install_registers_and_warns_about_an_unstable_location(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler(unstable="L'eseguibile si trova in Downloads: spostalo.")
    monkeypatch.setattr(cli, "scheduler_service", lambda: fake)

    assert cli.main(["--task", "install"]) == 0
    assert fake.calls == ["register"]
    out = capsys.readouterr().out
    assert "Downloads" in out


def test_task_install_reports_a_scheduler_failure(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler(error=scheduler.SchedulerError("schtasks: accesso negato"))
    monkeypatch.setattr(cli, "scheduler_service", lambda: fake)

    assert cli.main(["--task", "install"]) == 1
    assert "accesso negato" in capsys.readouterr().out


def test_task_remove_and_run(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler()
    monkeypatch.setattr(cli, "scheduler_service", lambda: fake)

    assert cli.main(["--task", "remove"]) == 0
    assert cli.main(["--task", "run"]) == 0
    assert fake.calls == ["unregister", "run_now"]


def test_task_status_prints_the_fields_in_italian(home: Path, monkeypatch, capsys):
    fake = _FakeScheduler(TaskStatus(
        registered=True, command=Path(r"C:\Tools\qtRequestory.exe"), args="--sync",
        exe_matches=True, state="Pronto", next_run="23/09/2026 09:00:00",
        last_run="22/09/2026 09:00:00", last_result=0,
    ))
    monkeypatch.setattr(cli, "scheduler_service", lambda: fake)

    assert cli.main(["--task", "status"]) == 0
    out = capsys.readouterr().out
    assert "Registrata: sì" in out
    assert "qtRequestory.exe" in out
    assert "Stato: Pronto" in out
    assert "Prossima esecuzione: 23/09/2026 09:00:00" in out
    assert "Ultimo esito: 0" in out


def test_task_status_says_when_nothing_is_registered(home: Path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scheduler_service", lambda: _FakeScheduler())
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
