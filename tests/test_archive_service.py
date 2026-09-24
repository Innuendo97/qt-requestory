"""facade.ArchiveService (the UI's ArchiveApi) and its fake, on one synthetic tree."""
from __future__ import annotations

import dataclasses
from datetime import date
from pathlib import Path

import pytest

from qtrequestory.core import facade, importer
from qtrequestory.core.archive import CONFLICT, DUPLICATE, IMPORTABLE, NEEDS_ENV, ArchiveReport
from qtrequestory.core.config import Environment, default_config
from qtrequestory.core.daily import local_path
from qtrequestory.core.importer import ImportResult, VerifiedOriginal
from qtrequestory.core.lock import ProcessLock
from tests.fakes.fake_core import FakeArchiveApi, build_fake_core
from tests.test_archive import LOG, LOG2, OTHER, put

D = date(2026, 9, 22)


def _cfg(tmp_path: Path, **kw):
    return dataclasses.replace(
        default_config(),
        mirror_root=tmp_path / "mirror",
        environments=[Environment("svil", "https://example.invalid/svil/"),
                      Environment("coll", "https://example.invalid/coll/", enabled=False)],
        output_dir=tmp_path / "out",
        **kw,
    )


def _tree(root: Path, mirror: Path) -> None:
    """Every verdict at once."""
    put(root, "coll/20260922.txt", LOG)                   # importable (disabled env still counts)
    put(root, "svil/20260921.txt", LOG)                   # duplicate
    put(mirror, "svil/2026/09/20260921.txt", LOG2)
    put(root, "svil/20260920.txt", LOG)                   # conflict
    put(mirror, "svil/2026/09/20260920.txt", OTHER)
    put(root, "misti/20260919.txt", LOG)                  # needs_env
    put(root, "x.zip", b"PK")                             # ignored


def _shape(report: ArchiveReport) -> list[tuple]:
    return [(f.rel_path, f.env, f.day, f.status, f.reason) for f in report.items]


@pytest.fixture
def mocked_bin(monkeypatch):
    calls: list[str] = []

    def shell(path: str):
        calls.append(path)
        Path(path).unlink()
        return 0, False

    monkeypatch.setattr(importer, "_shell_delete", shell)
    monkeypatch.setattr(importer, "_drive_type", lambda p: importer.DRIVE_FIXED)
    return calls


def test_report_defaults_to_the_mirror_and_uses_the_config(tmp_path):
    cfg = _cfg(tmp_path, folder_envs={"misti": "svil"})
    put(cfg.mirror_root, "coll/2026/9/20260922.txt", LOG)   # misplaced inside the mirror
    put(cfg.mirror_root, "coll/2026/09/20260921.txt", LOG)  # canonical: silent
    put(tmp_path / "old", "misti/20260919.txt", LOG)
    svc = facade.ArchiveService(lambda: cfg)
    assert [f.rel_path for f in svc.report().items] == ["coll/2026/9/20260922.txt"]
    item = svc.report(tmp_path / "old").items[0]
    assert (item.env, item.status) == ("svil", IMPORTABLE)


def test_import_copies_and_recycle_refuses_the_archive(tmp_path, mocked_bin):
    cfg = _cfg(tmp_path)
    _tree(tmp_path / "old", cfg.mirror_root)
    svc = facade.ArchiveService(lambda: cfg)
    report = svc.report(tmp_path / "old")
    result = svc.import_(report)
    assert isinstance(result, ImportResult)
    assert (result.copied, result.skipped, result.conflicts) == (1, 1, 1)
    assert local_path(cfg.mirror_root, "coll", D).read_bytes() == LOG
    inside = local_path(cfg.mirror_root, "coll", D)
    st = inside.stat()
    failures = svc.recycle(result.verified + [VerifiedOriginal(inside, st.st_size, st.st_mtime_ns, inside)])
    assert [p for p, _ in failures] == [inside]
    assert sorted(Path(c) for c in mocked_bin) == sorted(result.verified_paths)


def test_import_refuses_while_a_sync_holds_the_lock(tmp_path):
    cfg = _cfg(tmp_path)
    put(tmp_path / "old", "coll/20260922.txt", LOG)
    svc = facade.ArchiveService(lambda: cfg)
    report = svc.report(tmp_path / "old")
    with ProcessLock(cfg.lock_path):
        with pytest.raises(facade.ArchiveBusy):
            svc.import_(report)
    assert not local_path(cfg.mirror_root, "coll", D).exists()


def test_import_refuses_an_unusable_mirror_root(tmp_path):
    cfg = _cfg(tmp_path)
    put(tmp_path / "old", "coll/20260922.txt", LOG)
    report = facade.ArchiveService(lambda: cfg).report(tmp_path / "old")
    bad = dataclasses.replace(cfg, mirror_root=Path("relativo"))
    with pytest.raises(ValueError):
        facade.ArchiveService(lambda: bad).import_(report)


def test_fake_matches_real_on_the_same_tree(tmp_path, mocked_bin):
    real_cfg = _cfg(tmp_path / "real")
    _tree(tmp_path / "real" / "old", real_cfg.mirror_root)
    fake_core = build_fake_core(tmp_path / "fake")
    fake: FakeArchiveApi = fake_core.archive
    fake_cfg = fake_core.config.config
    fake_core.config.save(dataclasses.replace(fake_cfg, environments=real_cfg.environments))
    _tree(tmp_path / "fake" / "old", fake_core.config.config.mirror_root)

    real = facade.ArchiveService(lambda: real_cfg)
    real_report = real.report(tmp_path / "real" / "old")
    fake_report = fake.report(tmp_path / "fake" / "old")
    assert _shape(fake_report) == _shape(real_report)
    assert {f.status for f in real_report.items} >= {IMPORTABLE, DUPLICATE, CONFLICT, NEEDS_ENV}

    r, f = real.import_(real_report), fake.import_(fake_report)
    assert (r.copied, r.skipped, r.conflicts, len(r.errors), r.envs) == \
           (f.copied, f.skipped, f.conflicts, len(f.errors), f.envs)
    assert [p.name for p in r.verified_paths] == [p.name for p in f.verified_paths]
    assert real.recycle(r.verified) == [] and fake.recycle(f.verified) == []
    assert fake.recycled == f.verified_paths
    inside = local_path(fake_core.config.config.mirror_root, "coll", D)
    st = inside.stat()
    assert [p for p, _ in fake.recycle([VerifiedOriginal(inside, st.st_size, st.st_mtime_ns, inside)])] == [inside]
    assert [p for p, _ in fake.recycle([inside])] == [inside]  # a bare path is never accepted
    assert inside.exists()


@pytest.mark.parametrize("which", ["real", "fake"])
def test_report_accepts_another_canonical_root(tmp_path, which):
    """The wizard counts a folder that is not the configured mirror YET: the
    files already at their canonical place under it are not "to import"."""
    cfg = _cfg(tmp_path)
    new_mirror = tmp_path / "nuovo"
    put(new_mirror, "svil/2026/09/20260921.txt", LOG)      # canonical under the new folder
    put(new_mirror, "vecchi/svil_20260922.txt", LOG)       # stray under it
    if which == "real":
        svc = facade.ArchiveService(lambda: cfg)
    else:
        core = build_fake_core(tmp_path / "fake")
        core.config.save(cfg)
        svc = core.archive
    default = svc.report(new_mirror)
    assert sorted(f.rel_path for f in default.items) == [
        "svil/2026/09/20260921.txt", "vecchi/svil_20260922.txt"]
    other = svc.report(new_mirror, canonical_root=new_mirror)
    assert [f.rel_path for f in other.items] == ["vecchi/svil_20260922.txt"]
    assert other.canonical_root == new_mirror
