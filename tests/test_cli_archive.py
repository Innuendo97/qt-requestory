"""cli.py --archivio / --import: read-only report, copy + verify + index, and the
Recycle Bin only on --delete-originals (always mocked here)."""
from __future__ import annotations

import subprocess
import sys
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest

from qtrequestory import cli
from qtrequestory.core import facade as facade_mod
from qtrequestory.core import importer
from qtrequestory.core.config import load_config
from qtrequestory.core.daily import local_path
from qtrequestory.core.index.db import open_index
from qtrequestory.core.lock import ProcessLock
from tests.test_archive import LOG, LOG2, OTHER, put
from tests.test_cli import _NoParentConsole, _headless_subprocess, _write_config

D = date(2026, 9, 22)


@pytest.fixture(autouse=True)
def _stub_windows_console(monkeypatch):
    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _NoParentConsole()})())


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror", envs=["coll", "svil"])
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    return app_home


@pytest.fixture
def mirror(tmp_path: Path) -> Path:
    return tmp_path / "mirror"


@pytest.fixture
def old(tmp_path: Path) -> Path:
    return tmp_path / "old"


@pytest.fixture
def bin_calls(monkeypatch) -> list[str]:
    calls: list[str] = []

    def shell(path: str):
        calls.append(path)
        Path(path).unlink()
        return 0, False

    monkeypatch.setattr(importer, "_shell_delete", shell)
    monkeypatch.setattr(importer, "_drive_type", lambda p: importer.DRIVE_FIXED)
    return calls


def _indexed_days(mirror: Path) -> list[tuple[str, str]]:
    with closing(open_index(mirror / ".qtrequestory" / "index.sqlite")) as conn:
        return sorted(tuple(r) for r in conn.execute("SELECT env, day FROM files"))


# -------------------------------------------------------------- --archivio ---

def test_archivio_lists_every_file_with_its_verdict_and_changes_nothing(home, mirror, old, capsys):
    put(old, "coll/20260922.txt")
    put(old, "misti/20260921.txt")
    put(old, "coll/x.zip", b"PK")
    before = sorted(p for p in old.rglob("*"))
    assert cli.main(["--archivio", str(old)]) == 1          # needs_env -> 1
    out = capsys.readouterr().out
    assert "coll/20260922.txt" in out and "misti/20260921.txt" in out
    assert "archivio compresso: estrailo nella cartella" in out
    assert "da importare: 1" in out and "da assegnare: 1" in out and "ignorati: 1" in out
    assert sorted(p for p in old.rglob("*")) == before
    assert not mirror.exists()


def test_archivio_without_path_scans_the_mirror(home, mirror, capsys):
    put(mirror, "coll/2026/09/20260921.txt")
    put(mirror, "coll/2026/9/20260922.txt")                   # misplaced
    assert cli.main(["--archivio"]) == 0
    out = capsys.readouterr().out
    assert "coll/2026/9/20260922.txt" in out
    assert "coll/2026/09/20260921.txt" not in out


def test_archivio_exits_1_on_a_conflict(home, mirror, old):
    put(mirror, "coll/2026/09/20260922.txt", OTHER)
    put(old, "coll/20260922.txt", LOG)
    assert cli.main(["--archivio", str(old)]) == 1


def test_archivio_refuses_an_unset_mirror_root(tmp_path, monkeypatch, capsys):
    app_home = tmp_path / "home"
    _write_config(app_home, Path(""), envs=["coll"])
    monkeypatch.setenv("QTREQUESTORY_HOME", str(app_home))
    assert cli.main(["--archivio", str(tmp_path)]) == cli.EXIT_CONFIG_ERROR


# ---------------------------------------------------------------- --import ---

def test_import_copies_indexes_and_keeps_the_originals(home, mirror, old, capsys, bin_calls):
    orig = put(old, "coll/20260922.txt", LOG2)
    put(old, "svil/20260921.txt", LOG)
    assert cli.main(["--import", str(old)]) == 0
    out = capsys.readouterr().out
    assert local_path(mirror, "coll", D).read_bytes() == LOG2
    assert "copiati: 2" in out
    assert _indexed_days(mirror) == [("coll", "2026-09-22"), ("svil", "2026-09-21")]
    assert orig.exists() and bin_calls == []
    assert "--delete-originals" in out


def test_import_env_for_assigns_a_folder_for_this_run_only(home, mirror, old):
    put(old, "misti/20260922.txt")
    put(old, "scarti/20260921.txt")
    assert cli.main(["--import", str(old), "--env-for", "misti=svil", "--env-for", "scarti=ignora"]) == 0
    assert local_path(mirror, "svil", D).exists()
    assert not local_path(mirror, "svil", date(2026, 9, 21)).exists()
    assert load_config(home / "config.json").folder_envs == {}


def test_import_with_a_folder_still_unassigned_exits_1(home, mirror, old):
    put(old, "coll/20260922.txt")
    put(old, "misti/20260921.txt")
    assert cli.main(["--import", str(old)]) == 1
    assert local_path(mirror, "coll", D).exists()


def test_import_delete_originals_recycles_only_the_verified(home, mirror, old, bin_calls, capsys):
    good = put(old, "coll/20260922.txt", LOG)
    conflict = put(old, "svil/20260921.txt", LOG)
    put(mirror, "svil/2026/09/20260921.txt", OTHER)
    unassigned = put(old, "misti/20260920.txt")
    assert cli.main(["--import", str(old), "--delete-originals"]) == 1
    assert bin_calls == [str(good)]
    assert not good.exists() and conflict.exists() and unassigned.exists()
    assert "Cestino: 1" in capsys.readouterr().out


def test_import_while_a_sync_runs_touches_nothing(home, mirror, old, capsys):
    put(old, "coll/20260922.txt")
    with ProcessLock(mirror / ".qtrequestory" / "sync.lock"):
        assert cli.main(["--import", str(old)]) == 1
    assert "sincronizzazione in corso" in capsys.readouterr().out
    assert not local_path(mirror, "coll", D).exists()


@pytest.mark.parametrize("argv", [
    ["--import", "x", "--env-for", "senza-uguale"],
    ["--import", "x", "--env-for", "=svil"],
    ["--archivio", "x", "--env-for", "a=svil"],
    ["--archivio", "x", "--delete-originals"],
    ["--sync", "--delete-originals"],
    ["--archivio", "x", "-e", "coll"],
])
def test_misused_options_are_refused(home, argv):
    with pytest.raises(SystemExit):
        cli.main(argv)


def test_env_for_an_unconfigured_env_is_a_config_error(home, old, capsys):
    put(old, "misti/20260922.txt")
    assert cli.main(["--import", str(old), "--env-for", "misti=prod"]) == cli.EXIT_CONFIG_ERROR
    assert "prod" in capsys.readouterr().out


def test_archivio_never_imports_qt(tmp_path):
    app_home = tmp_path / "home"
    _write_config(app_home, tmp_path / "mirror", envs=["coll"])
    probe = _headless_subprocess(["--archivio"], app_home)
    assert probe["qt"] == []


def test_the_new_modes_attach_the_console(monkeypatch):
    calls: list[int] = []

    class _Recording:
        def AttachConsole(self, pid: int) -> int:
            calls.append(pid)
            return 0

    monkeypatch.setattr(cli.ctypes, "windll", type("Windll", (), {"kernel32": _Recording()})())
    cli._attach_parent_console(["--archivio"])
    cli._attach_parent_console(["--import", "x"])
    assert len(calls) == (2 if sys.platform == "win32" else 0)


# ------------------------------------------------------------ fix round 1 ---

@pytest.mark.parametrize("argv", [["--import", ""], ["--import", "manca"], ["--archivio", "manca"]])
def test_a_missing_or_empty_folder_is_a_config_error_never_the_gui(home, tmp_path, monkeypatch, capsys, argv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_start_gui", lambda paths: pytest.fail("the GUI must not start"))
    assert cli.main(argv) == cli.EXIT_CONFIG_ERROR
    assert "cartella" in capsys.readouterr().out


def test_a_file_instead_of_a_folder_is_a_config_error(home, old):
    f = put(old, "coll/20260922.txt")
    assert cli.main(["--import", str(f)]) == cli.EXIT_CONFIG_ERROR
    assert cli.main(["--archivio", str(f)]) == cli.EXIT_CONFIG_ERROR


def test_import_resolves_a_relative_path(home, mirror, old, monkeypatch):
    put(old, "coll/20260922.txt")
    monkeypatch.chdir(old.parent)
    assert cli.main(["--import", old.name]) == 0
    assert local_path(mirror, "coll", D).exists()


def test_a_cancelled_import_never_recycles(home, mirror, old, bin_calls, monkeypatch):
    put(old, "coll/20260921.txt")
    put(old, "coll/20260922.txt")
    real = importer.run_import

    def cancel_after_first(report, root, *, cancel=None, progress=None):
        def prog(done, total, rel):
            if done == 1:
                cancel.cancel()
        return real(report, root, cancel=cancel, progress=prog)

    monkeypatch.setattr(facade_mod, "run_import", cancel_after_first)
    assert cli.main(["--import", str(old), "--delete-originals"]) == cli.EXIT_CANCELLED
    assert bin_calls == []
