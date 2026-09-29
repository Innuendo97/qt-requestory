"""Deleting an initiative's folder for good (phase 2.5, D6): ``officina.remove``
and ``OfficinaApi.delete_initiative`` (real service and fake, same behaviour).

The only place of the Officina that removes a whole tree: every path that is
not provably an initiative folder directly inside the Officina folder is
refused with nothing touched, and a file in use leaves the initiative whole.
"""
from __future__ import annotations

import dataclasses
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest

from qtrequestory.core.config import OfficinaSettings, default_config
from qtrequestory.officina import remove
from qtrequestory.officina.model import Initiative, Workspace
from qtrequestory.officina.remove import RefusedDeletion, check_initiative_folder, delete_initiative_folder
from qtrequestory.officina.service import OfficinaService
from tests.fakes.fake_core import build_fake_core

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows file locking")


def _initiative(root: Path, name: str = "Acme-Servizi") -> Initiative:
    ini = Workspace(root).create_initiative(name)
    (ini.folder / "casi" / "c1").mkdir(parents=True)
    (ini.folder / "casi" / "c1" / "doc.pdf").write_bytes(b"%PDF-1.4 finto")
    return ini


def _tree(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "officina"
    folder.mkdir()
    return folder


# ------------------------------------------------------------------ deletes ---

def test_an_initiative_folder_is_deleted_with_everything_inside(root: Path):
    ini = _initiative(root)
    other = _initiative(root, "Altra")

    delete_initiative_folder(root, ini.folder)

    assert not ini.folder.exists()
    assert sorted(p.name for p in root.iterdir()) == [other.folder.name], "nothing else, no leftovers"


def test_read_only_files_do_not_stop_the_deletion(root: Path):
    ini = _initiative(root)
    locked = ini.folder / "casi" / "c1" / "doc.pdf"
    os.chmod(locked, stat.S_IREAD)

    delete_initiative_folder(root, ini.folder)

    assert not ini.folder.exists()


def test_a_folder_already_gone_is_file_not_found(root: Path):
    ini = _initiative(root)
    shutil.rmtree(ini.folder)
    with pytest.raises(FileNotFoundError):
        delete_initiative_folder(root, ini.folder)


# ------------------------------------------------------------------ refuses ---

def test_no_officina_folder_is_refused(root: Path):
    ini = _initiative(root)
    for bad_root in (None, Path("officina"), Path("")):
        with pytest.raises(RefusedDeletion):
            delete_initiative_folder(bad_root, ini.folder)
    assert (ini.folder / "iniziativa.json").is_file()


def test_the_officina_folder_itself_is_refused(root: Path):
    (root / "iniziativa.json").write_text("{}", encoding="utf-8")
    with pytest.raises(RefusedDeletion):
        delete_initiative_folder(root, root)
    assert root.is_dir()


def test_a_folder_outside_or_deeper_than_the_root_is_refused(root: Path, tmp_path: Path):
    outside = _initiative(tmp_path / "altrove")
    deeper = _initiative(root / "sotto")
    ini = _initiative(root)
    for folder in (outside.folder, deeper.folder, root / ini.folder.name / ".." / ini.folder.name,
                   ini.folder / "casi", Path(ini.folder.name)):
        with pytest.raises(RefusedDeletion):
            delete_initiative_folder(root, folder)
    for kept in (outside.folder, deeper.folder, ini.folder):
        assert (kept / "iniziativa.json").is_file()


def test_a_folder_without_iniziativa_json_is_refused(root: Path):
    plain = root / "Documenti"
    plain.mkdir()
    (plain / "nota.txt").write_text("resta", encoding="utf-8")
    fake_meta = root / "Finta"
    (fake_meta / "iniziativa.json").mkdir(parents=True)  # a folder, not a file
    for folder in (plain, fake_meta):
        with pytest.raises(RefusedDeletion):
            delete_initiative_folder(root, folder)
    assert (plain / "nota.txt").is_file() and (fake_meta / "iniziativa.json").is_dir()


def test_a_file_is_refused(root: Path):
    (root / "file.txt").write_text("x", encoding="utf-8")
    with pytest.raises(RefusedDeletion):
        delete_initiative_folder(root, root / "file.txt")
    assert (root / "file.txt").is_file()


def test_reserved_names_are_refused(root: Path):
    with pytest.raises(RefusedDeletion):
        check_initiative_folder(root, root / "NUL")


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
def test_a_junction_to_an_initiative_elsewhere_is_refused(root: Path, tmp_path: Path):
    import _winapi

    elsewhere = _initiative(tmp_path / "altrove", "Vera")
    link = root / "Collegamento"
    _winapi.CreateJunction(str(elsewhere.folder), str(link))
    try:
        with pytest.raises(RefusedDeletion):
            delete_initiative_folder(root, link)
        assert (elsewhere.folder / "casi" / "c1" / "doc.pdf").is_file()
    finally:
        os.rmdir(link)  # removes the junction only


# ------------------------------------------------------------------- locked ---

@windows_only
def test_a_file_in_use_leaves_the_initiative_whole(root: Path):
    ini = _initiative(root)
    before = _tree(ini.folder)
    with open(ini.folder / "casi" / "c1" / "doc.pdf", "rb"):
        with pytest.raises(PermissionError):
            delete_initiative_folder(root, ini.folder)
    assert _tree(ini.folder) == before, "not a single file lost"
    delete_initiative_folder(root, ini.folder)  # free again: it goes
    assert not ini.folder.exists()


def test_a_failure_half_way_puts_the_folder_back(root: Path, monkeypatch):
    ini = _initiative(root)

    def half(path, onexc=None):
        next(Path(path).rglob("doc.pdf")).unlink()
        raise PermissionError(13, "in uso")

    monkeypatch.setattr(remove.shutil, "rmtree", half)
    with pytest.raises(PermissionError):
        delete_initiative_folder(root, ini.folder)
    assert (ini.folder / "iniziativa.json").is_file(), "back under its own name"
    assert [p.name for p in root.iterdir()] == [ini.folder.name], "no hidden copy left"


def test_iniziativa_json_goes_last_so_a_failure_keeps_it_listed(root: Path, monkeypatch):
    ini = _initiative(root)
    (ini.folder / "zeta.txt").write_text("dopo iniziativa.json in ordine alfabetico", encoding="utf-8")
    real = remove._remove_entry

    def fail_on_zeta(path: Path) -> None:
        if path.name == "zeta.txt":
            raise PermissionError(13, "in uso")
        real(path)

    monkeypatch.setattr(remove, "_remove_entry", fail_on_zeta)
    with pytest.raises(PermissionError):
        delete_initiative_folder(root, ini.folder)
    assert (ini.folder / "iniziativa.json").is_file(), "still an initiative: listed and deletable"
    assert (ini.folder / "zeta.txt").is_file() and not (ini.folder / "casi").exists()
    monkeypatch.undo()
    delete_initiative_folder(root, ini.folder)
    assert not ini.folder.exists()


def test_the_deletion_time_is_logged(root: Path, caplog):
    ini = _initiative(root)
    with caplog.at_level("INFO", logger="qtrequestory.officina.remove"):
        delete_initiative_folder(root, ini.folder)
    assert any("eliminata" in r.getMessage() and " s" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------- service and fake ---

def _real_and_fake(tmp_path: Path):
    core = build_fake_core(tmp_path / "core")
    fake = core.officina
    real = OfficinaService(core.config.load)
    return fake, real, fake.workspace_root()


def test_the_service_refuses_what_is_not_inside_its_root(tmp_path: Path):
    settings = OfficinaSettings(root=tmp_path / "officina")
    config = dataclasses.replace(default_config(), officina=settings)
    svc = OfficinaService(lambda: config)
    ini = svc.create_initiative("Acme-Servizi")
    outside = _initiative(tmp_path / "altrove")

    with pytest.raises(ValueError):
        svc.delete_initiative(outside)
    with pytest.raises(ValueError):
        svc.delete_initiative(dataclasses.replace(ini, folder=tmp_path / "officina"))
    svc.delete_initiative(ini)

    assert svc.initiatives() == [] and (outside.folder / "iniziativa.json").is_file()


def test_fake_and_real_delete_and_refuse_alike(tmp_path: Path):
    fake, real, root = _real_and_fake(tmp_path)
    outside = _initiative(tmp_path / "altrove")
    for api in (fake, real):
        ini = api.create_initiative(f"Da eliminare {type(api).__name__}")
        api.delete_initiative(ini)
        assert ini.id not in [i.id for i in api.initiatives()]
        with pytest.raises(FileNotFoundError):
            api.delete_initiative(ini)
        with pytest.raises(ValueError):
            api.delete_initiative(outside)
        with pytest.raises(ValueError):
            api.delete_initiative(dataclasses.replace(ini, folder=root))
    assert (outside.folder / "iniziativa.json").is_file()
    assert fake.deleted == [f"Da eliminare {type(fake).__name__}"]


def test_the_fake_can_fail_like_a_file_in_use(tmp_path: Path):
    fake, _real, _root = _real_and_fake(tmp_path)
    ini = fake.create_initiative("Bloccata")
    fake.delete_error = "file in uso"
    with pytest.raises(PermissionError):
        fake.delete_initiative(ini)
    assert (ini.folder / "iniziativa.json").is_file() and fake.deleted == []


# ------------------------------------------------ rereview minor A (meta, gone) ---

def _capitalise_meta(ini) -> None:
    (ini.folder / "iniziativa.json").rename(ini.folder / "Iniziativa.json")  # a hand rename


def test_a_meta_file_spelt_otherwise_still_goes_last(root: Path, monkeypatch):
    ini = _initiative(root)
    _capitalise_meta(ini)
    (ini.folder / "zeta.txt").write_text("x", encoding="utf-8")
    real = remove._remove_entry
    removed: list[str] = []

    def record(path: Path) -> None:
        removed.append(path.name)
        real(path)

    monkeypatch.setattr(remove, "_remove_entry", record)
    delete_initiative_folder(root, ini.folder)
    assert removed[-1] == "Iniziativa.json" and not ini.folder.exists()


def test_a_meta_file_spelt_otherwise_survives_a_failure(root: Path, monkeypatch):
    ini = _initiative(root)
    _capitalise_meta(ini)
    (ini.folder / "zeta.txt").write_text("x", encoding="utf-8")
    real = remove._remove_entry

    def fail_on_zeta(path: Path) -> None:
        if path.name == "zeta.txt":
            raise PermissionError(13, "in uso")
        real(path)

    monkeypatch.setattr(remove, "_remove_entry", fail_on_zeta)
    with pytest.raises(PermissionError):
        delete_initiative_folder(root, ini.folder)
    assert (ini.folder / "Iniziativa.json").is_file(), "still listed and deletable"


def test_a_child_already_gone_counts_as_removed(root: Path, monkeypatch):
    ini = _initiative(root)
    real = remove._remove_entry

    def vanish(path: Path) -> None:
        real(path)
        if path.name == "casi":
            raise FileNotFoundError(2, "sparito", str(path))  # removed by someone else meanwhile

    monkeypatch.setattr(remove, "_remove_entry", vanish)
    delete_initiative_folder(root, ini.folder)
    assert not ini.folder.exists()


def test_never_file_not_found_while_the_folder_is_back(root: Path, monkeypatch):
    """A FileNotFoundError reads as "already gone" upstream: after the rename
    back it must be another OSError."""
    ini = _initiative(root)

    def odd_rmdir(self):
        raise FileNotFoundError(2, "strano", str(self))

    monkeypatch.setattr(remove.Path, "rmdir", odd_rmdir)
    with pytest.raises(OSError) as info:
        delete_initiative_folder(root, ini.folder)
    assert not isinstance(info.value, FileNotFoundError)
    assert ini.folder.is_dir()
