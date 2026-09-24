"""An unusable ``mirror_root`` ("" / "." / relative) never reaches the disk.

``Path("")`` normalises to ``Path(".")``: every path the core derives from
it (index, sync state, lock, ``<env>/`` listings) resolves against the
process CWD. Before 1.1.0's final review the GUI polled exactly those paths
while the folder was not configured, creating ``./.qtrequestory/index.sqlite``
wherever the exe happened to be started. The facade now answers "nothing
there" (or ``ValueError`` for the operations that need a mirror) without
touching the disk, and the fake answers the same.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from qtrequestory.core import facade
from qtrequestory.core.config import default_config
from qtrequestory.core.events import CancelToken, CollectingSink
from qtrequestory.core.index.search import SearchQuery
from qtrequestory.core.paths import AppPaths
from qtrequestory.ui.contracts import Environment
from tests.fakes.fake_core import build_fake_core

INVALID_ROOTS = [Path(""), Path("."), Path("relative/logs")]
ENV = "svil"


def _cfg(root: Path):
    return dataclasses.replace(default_config(), mirror_root=root,
                               environments=[Environment(ENV, "https://example.invalid/svil/")])


def _real(tmp_path: Path, root: Path):
    cfg = _cfg(root)
    paths = AppPaths(tmp_path / "apphome").ensure()
    return (facade.SyncService(lambda: cfg, paths=paths), facade.IndexService(lambda: cfg))


def _fake(tmp_path: Path, root: Path):
    core = build_fake_core(tmp_path / "fake")
    core.config.config = _cfg(root)
    return core.sync, core.index


def _exercise(sync, index) -> dict:
    """Every read the GUI polls, with what each answered (or raised)."""
    out: dict = {}
    status = sync.env_status(ENV)
    out["env_status"] = (status.last_success, status.fresh, status.n_local_files,
                         status.local_bytes, status.latest_day, status.index_pending)
    out["is_fresh"] = sync.is_fresh(ENV)
    out["lock_holder"] = sync.lock_holder()
    out["coverage"] = index.coverage(ENV)
    out["count_local_files"] = index.count_local_files()
    for name, call in [
        ("coverage_days", lambda: index.coverage_days(ENV)),
        ("plan", lambda: index.plan([ENV])),
        ("list_template_keys", lambda: index.list_template_keys(ENV)),
        ("search", lambda: index.search(SearchQuery(ENV, template_key="MOD_TEST_A"))),
        ("update", lambda: index.update([ENV], sink=CollectingSink(), cancel=CancelToken())),
        ("run", lambda: sync.run([ENV], sink=CollectingSink(), cancel=CancelToken())),
    ]:
        with pytest.raises(ValueError) as exc:
            call()
        out[name] = str(exc.value)
    return out


@pytest.mark.parametrize("root", INVALID_ROOTS, ids=["empty", "dot", "relative"])
def test_real_facade_never_touches_the_cwd(root: Path, tmp_path: Path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    day_dir = cwd / ENV / "2026" / "09"  # a listing that WOULD be found under the CWD
    day_dir.mkdir(parents=True)
    (day_dir / "20260918.txt").write_bytes(b"x")
    monkeypatch.chdir(cwd)
    before = sorted(p.relative_to(cwd) for p in cwd.rglob("*"))

    got = _exercise(*_real(tmp_path, root))

    assert sorted(p.relative_to(cwd) for p in cwd.rglob("*")) == before
    assert got["env_status"] == (None, False, 0, 0, None, 0)
    assert got["is_fresh"] is False
    assert got["lock_holder"] is None
    assert got["coverage"] is None
    assert got["count_local_files"] == 0
    assert got["coverage_days"].startswith("La cartella dei log")


@pytest.mark.parametrize("root", INVALID_ROOTS, ids=["empty", "dot", "relative"])
def test_fake_answers_like_the_real_facade(root: Path, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert _exercise(*_fake(tmp_path, root)) == _exercise(*_real(tmp_path, root))


def test_count_local_files_of_an_explicit_folder_is_still_counted(tmp_path: Path):
    """The wizard counts the folder the user just picked, not the config's."""
    _sync, index = _real(tmp_path, Path(""))
    day_dir = tmp_path / "picked" / ENV / "2026" / "09"
    day_dir.mkdir(parents=True)
    (day_dir / "20260918.txt").write_bytes(b"x")
    assert index.count_local_files(tmp_path / "picked") == 1
