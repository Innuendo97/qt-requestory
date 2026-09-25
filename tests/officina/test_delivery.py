"""qtrequestory.officina.delivery: the testers' delivery folder (spec §8).

Synthetic data only (this repository is public): template keys are
``MOD_TEST_*``, documents are a few placeholder bytes.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from qtrequestory.officina import delivery
from qtrequestory.officina.delivery import (
    DeliveryError,
    DeliveryItem,
    build_plan,
    find_conflicts,
    plan_delivery,
    run_delivery,
    safe_component,
)
from qtrequestory.officina.model import Initiative, Workspace

PDF = b"%PDF-1.4 synthetic\n%%EOF\n"


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "officina")


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    folder = tmp_path / "consegne"
    folder.mkdir()
    return folder


def _case(ws: Workspace, ini: Initiative, key: str, variant: str = "", *, target: str | None = "atteso.pdf",
          asis: bool = True, tobe: int = 1, tmp: Path | None = None):
    case = ws.add_case(ini, key, variant, {"documents": []}, env="svil", source_fdi=None)
    if target is not None:
        src_dir = (tmp or ini.folder.parent.parent) / "src" / case.id
        src_dir.mkdir(parents=True, exist_ok=True)
        src = src_dir / target
        src.write_bytes(PDF + f"target {case.id}".encode())
        ws.set_target(case, src)
    if asis:
        ws.add_version(case, "asis", PDF + b"asis", "pdf", {})
    for n in range(tobe):
        ws.add_version(case, "tobe", PDF + f"tobe {n + 1}".encode(), "pdf", {})
    return case


def _tree(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _never(_path: Path):
    raise AssertionError("no conflict expected")


# -------------------------------------------------------------------- layout ---

def test_layout_for_one_case(ws: Workspace):
    ini = ws.create_initiative("Prezzi ottobre")
    case = _case(ws, ini, "MOD_TEST_A", target="Contratto atteso.pdf", tobe=2)

    items = plan_delivery(ini, [case.id])

    assert [i.dest_rel for i in items] == [
        "MOD_TEST_A/MOD_TEST_A_ASIS.pdf",
        "MOD_TEST_A/MOD_TEST_A_TOBE.pdf",
        "MOD_TEST_A/Contratto atteso.pdf",
    ]
    assert items[1].src == case.latest_tobe().path, "the latest TO-BE"
    assert items[2].src == case.target().path
    assert {i.case_id for i in items} == {case.id}


def test_layout_for_two_variants_of_one_key(ws: Workspace):
    ini = ws.create_initiative("Prezzi ottobre")
    a = _case(ws, ini, "MOD_TEST_A", "abilitato", target="atteso.pdf")
    b = _case(ws, ini, "MOD_TEST_A", "non abilitato", target="atteso.pdf")
    c = _case(ws, ini, "MOD_TEST_B", target="altro.pdf")

    items = plan_delivery(ini, [a.id, b.id, c.id])

    assert [i.dest_rel for i in items] == [
        "MOD_TEST_A/MOD_TEST_A_abilitato_ASIS.pdf",
        "MOD_TEST_A/MOD_TEST_A_abilitato_TOBE.pdf",
        "MOD_TEST_A/atteso (abilitato).pdf",
        "MOD_TEST_A/MOD_TEST_A_non abilitato_ASIS.pdf",
        "MOD_TEST_A/MOD_TEST_A_non abilitato_TOBE.pdf",
        "MOD_TEST_A/atteso (non abilitato).pdf",
        "MOD_TEST_B/MOD_TEST_B_ASIS.pdf",
        "MOD_TEST_B/MOD_TEST_B_TOBE.pdf",
        "MOD_TEST_B/altro.pdf",
    ]


def test_targets_with_different_names_keep_them(ws: Workspace):
    ini = ws.create_initiative("I")
    a = _case(ws, ini, "MOD_TEST_A", "uno", target="primo.pdf")
    b = _case(ws, ini, "MOD_TEST_A", "due", target="secondo.pdf")

    rels = [i.dest_rel for i in plan_delivery(ini, [a.id, b.id])]

    assert "MOD_TEST_A/primo.pdf" in rels and "MOD_TEST_A/secondo.pdf" in rels


def test_only_the_chosen_cases_are_planned_and_one_variant_alone_has_no_variant_in_names(ws: Workspace):
    ini = ws.create_initiative("I")
    a = _case(ws, ini, "MOD_TEST_A", "uno")
    _case(ws, ini, "MOD_TEST_A", "due")

    rels = [i.dest_rel for i in plan_delivery(ini, [a.id])]

    assert rels[:2] == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf", "MOD_TEST_A/MOD_TEST_A_TOBE.pdf"]


def test_an_html_version_keeps_its_extension(ws: Workspace):
    ini = ws.create_initiative("I")
    case = ws.add_case(ini, "MOD_TEST_EMAIL", "", {}, env="svil", source_fdi=None)
    ws.add_version(case, "tobe", b"<html><body>ciao</body></html>", "html", {})

    assert [i.dest_rel for i in plan_delivery(ini, [case.id])] == ["MOD_TEST_EMAIL/MOD_TEST_EMAIL_TOBE.html"]


def test_missing_slots_are_skipped_and_listed(ws: Workspace):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A", target=None, tobe=0)

    plan = build_plan(ini, [case.id])

    assert [i.dest_rel for i in plan.items] == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf"]
    assert [(m.case_id, m.slot, m.reason) for m in plan.missing] == [
        (case.id, "tobe", "absent"), (case.id, "target", "absent")]


def test_a_version_deleted_on_disk_is_listed_as_gone(ws: Workspace):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A")
    case.latest_tobe().path.unlink()

    plan = build_plan(ini, [case.id])

    assert "MOD_TEST_A/MOD_TEST_A_TOBE.pdf" not in [i.dest_rel for i in plan.items]
    assert [(m.slot, m.reason) for m in plan.missing] == [("tobe", "gone")]


def test_a_target_name_pointing_outside_the_case_is_refused(ws: Workspace, tmp_path: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A")
    outside = tmp_path / "segreto.pdf"
    outside.write_bytes(PDF)
    meta = case.folder / "target" / "target.meta.json"
    raw = json.loads(meta.read_text(encoding="utf-8"))
    raw["original_name"] = os.path.relpath(outside, case.folder / "target")
    meta.write_text(json.dumps(raw), encoding="utf-8")

    plan = build_plan(ini, [case.id])

    assert all(i.src != outside and not i.dest_rel.endswith("segreto.pdf") for i in plan.items)
    # the model already refuses such a name (more than one path component)
    assert [(m.slot, m.reason) for m in plan.missing] == [("target", "broken")]


# --------------------------------------------------------------- path safety ---

@pytest.mark.parametrize(("raw", "expected"), [
    ("MOD_TEST_A", "MOD_TEST_A"),
    ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j"),
    ("tab\there\x00nul\x1f", "tab_here_nul_"),
    ("fine. . ", "fine"),
    ("..", "_"),
    (".", "_"),
    ("", "_"),
    ("   ", "_"),
    ("CON", "CON_"),
    ("nul.pdf", "nul_.pdf"),
    ("Com1.txt", "Com1_.txt"),
    ("LPT9", "LPT9_"),
    ("COM¹", "COM¹_"),
    ("CON .pdf", "CON_ .pdf"),
    ("CONSEGNA", "CONSEGNA"),
])
def test_safe_component(raw: str, expected: str):
    assert safe_component(raw) == expected


def test_safe_component_is_one_component_and_never_absolute():
    for raw in ("C:\\Windows\\x", "/etc/passwd", "\\\\server\\share", "../../x", "a/../../b", "C:x"):
        got = safe_component(raw)
        assert Path(got).name == got and not Path(got).is_absolute() and ".." not in Path(got).parts


def test_safe_component_limits_the_length_and_keeps_the_extension():
    got = safe_component("x" * 400 + ".pdf")
    assert len(got) <= delivery.MAX_COMPONENT and got.endswith(".pdf")


def test_hostile_key_variant_and_target_stay_inside_the_delivery_folder(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    # A target file named CON.pdf cannot exist on Windows (safe_component's
    # own test covers device names); here the two same-named targets get the
    # hostile variants as their suffix.
    a = _case(ws, ini, "..\\..\\MOD_TEST_A", "../../evil", target="atteso.pdf")
    b = _case(ws, ini, "..\\..\\MOD_TEST_A", "c:\\x", target="atteso.pdf")

    items = plan_delivery(ini, [a.id, b.id])
    delivered = run_delivery(items, dest, "..", on_conflict=_never, make_zip=True)

    root = dest / "_"
    for path in delivered:
        assert os.path.commonpath([os.path.abspath(path), os.path.abspath(dest)]) == os.path.abspath(dest)
    assert all(os.path.abspath(p).startswith(os.path.abspath(root) + os.sep) for p in delivered[:-1])
    assert delivered[-1] == dest / "_.zip"
    for rel in (i.dest_rel for i in items):
        parts = rel.split("/")
        assert len(parts) == 2 and all(p == safe_component(p) for p in parts)


def test_an_item_escaping_the_folder_is_refused_not_written(dest: Path, tmp_path: Path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(PDF)
    bad = [DeliveryItem("c", src, "../fuori.pdf"), DeliveryItem("c", src, "C:/assoluto.pdf")]

    with pytest.raises(DeliveryError) as info:
        run_delivery(bad, dest, "I", on_conflict=_never, make_zip=False)

    assert not (dest / "fuori.pdf").exists()
    assert len(info.value.report.failed) == 2 and not info.value.report.delivered


def test_a_destination_that_is_not_absolute_is_refused(tmp_path: Path):
    src = tmp_path / "doc.pdf"
    src.write_bytes(PDF)
    with pytest.raises(ValueError):
        run_delivery([DeliveryItem("c", src, "K/K_ASIS.pdf")], Path("relativa"), "I",
                     on_conflict=_never, make_zip=False)


# ---------------------------------------------------------------------- writes ---

def test_run_delivery_writes_the_tree(ws: Workspace, dest: Path):
    ini = ws.create_initiative("Prezzi ottobre")
    case = _case(ws, ini, "MOD_TEST_A", target="atteso.pdf")

    delivered = run_delivery(plan_delivery(ini, [case.id]), dest, ini.name, on_conflict=_never,
                             make_zip=False)

    folder = dest / "Prezzi ottobre"
    assert _tree(folder) == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf", "MOD_TEST_A/MOD_TEST_A_TOBE.pdf",
                             "MOD_TEST_A/atteso.pdf"]
    assert (folder / "MOD_TEST_A" / "MOD_TEST_A_TOBE.pdf").read_bytes() == case.latest_tobe().path.read_bytes()
    assert sorted(delivered) == sorted(folder / r for r in _tree(folder))
    assert not list(dest.rglob("*.part")), "no temp file left behind"


@pytest.fixture
def delivered_once(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A", target=None)
    items = plan_delivery(ini, [case.id])
    run_delivery(items, dest, "I", on_conflict=_never, make_zip=False)
    old = dest / "I" / "MOD_TEST_A" / "MOD_TEST_A_TOBE.pdf"
    old.write_bytes(b"vecchio")
    ws.add_version(case, "tobe", PDF + b"nuovo", "pdf", {})
    return plan_delivery(ws.load("I"), [case.id]), old


def test_conflict_replace(delivered_once, dest: Path):
    items, old = delivered_once
    asked: list[Path] = []

    run_delivery(items, dest, "I", on_conflict=lambda p: asked.append(p) or "replace", make_zip=False)

    assert old in asked and len(asked) == 2  # AS-IS and TO-BE both existed
    assert old.read_bytes().endswith(b"nuovo")
    assert _tree(dest / "I") == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf", "MOD_TEST_A/MOD_TEST_A_TOBE.pdf"]


def test_conflict_keep_both(delivered_once, dest: Path):
    items, old = delivered_once

    delivered = run_delivery(items, dest, "I", on_conflict=lambda _p: "keep_both", make_zip=False)

    assert old.read_bytes() == b"vecchio"
    assert (old.parent / "MOD_TEST_A_TOBE (2).pdf").read_bytes().endswith(b"nuovo")
    assert old.parent / "MOD_TEST_A_TOBE (2).pdf" in delivered
    run_delivery(items, dest, "I", on_conflict=lambda _p: "keep_both", make_zip=False)
    assert (old.parent / "MOD_TEST_A_TOBE (3).pdf").exists()


def test_conflict_skip(delivered_once, dest: Path):
    items, old = delivered_once

    report = delivery.deliver(items, dest, "I", on_conflict=lambda _p: "skip", make_zip=False)

    assert old.read_bytes() == b"vecchio"
    assert report.delivered == [] and sorted(report.skipped) == sorted(
        dest / "I" / r for r in ("MOD_TEST_A/MOD_TEST_A_ASIS.pdf", "MOD_TEST_A/MOD_TEST_A_TOBE.pdf"))


def test_find_conflicts_lists_existing_files_and_the_zip(delivered_once, dest: Path):
    items, old = delivered_once
    (dest / "I.zip").write_bytes(b"zip vecchio")

    found = find_conflicts(items, dest, "I", make_zip=True)

    assert old in found and dest / "I.zip" in found and len(found) == 3
    assert find_conflicts(items, dest, "I", make_zip=False) == [p for p in found if p.suffix != ".zip"]


def test_sources_are_verified_before_anything_is_copied(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A")
    items = plan_delivery(ini, [case.id])
    case.asis().path.unlink()

    with pytest.raises(DeliveryError) as info:
        run_delivery(items, dest, "I", on_conflict=_never, make_zip=True)

    assert not (dest / "I").exists() and not (dest / "I.zip").exists(), "nothing written"
    assert [rel for rel, _reason in info.value.report.failed] == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf"]


def test_a_failure_midway_reports_delivered_and_failed_without_rolling_back(ws: Workspace, dest: Path,
                                                                             monkeypatch):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A")
    items = plan_delivery(ini, [case.id])
    real_copy = delivery._copy_bytes

    def flaky(src: Path, dst: Path) -> None:
        if "TOBE" in dst.name:
            raise OSError("disco pieno")
        real_copy(src, dst)

    monkeypatch.setattr(delivery, "_copy_bytes", flaky)
    with pytest.raises(DeliveryError) as info:
        run_delivery(items, dest, "I", on_conflict=_never, make_zip=True)

    report = info.value.report
    assert [p.name for p in report.delivered] == ["MOD_TEST_A_ASIS.pdf", "atteso.pdf"]
    assert [(rel, "disco pieno" in reason) for rel, reason in report.failed] == [
        ("MOD_TEST_A/MOD_TEST_A_TOBE.pdf", True)]
    assert _tree(dest / "I") == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf", "MOD_TEST_A/atteso.pdf"], "kept"
    assert report.zip_path is None and not (dest / "I.zip").exists(), "no zip of an incomplete delivery"
    assert not list(dest.rglob("*.part"))


def test_cancel_stops_between_files(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A")

    class Stop:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 1

    report = delivery.deliver(plan_delivery(ini, [case.id]), dest, "I", on_conflict=_never,
                              make_zip=True, cancel=Stop())

    assert len(report.delivered) == 1 and report.cancelled and report.zip_path is None


# ------------------------------------------------------------------------- zip ---

def test_the_zip_holds_the_same_tree(ws: Workspace, dest: Path):
    ini = ws.create_initiative("Prezzi ottobre")
    a = _case(ws, ini, "MOD_TEST_A", "uno")
    b = _case(ws, ini, "MOD_TEST_A", "due")
    c = _case(ws, ini, "MOD_TEST_B")

    delivered = run_delivery(plan_delivery(ini, [a.id, b.id, c.id]), dest, ini.name,
                             on_conflict=_never, make_zip=True)

    archive = dest / "Prezzi ottobre.zip"
    assert delivered[-1] == archive
    with zipfile.ZipFile(archive) as zf:
        files = sorted(n for n in zf.namelist() if not n.endswith("/"))
        assert all(i.compress_type == zipfile.ZIP_DEFLATED for i in zf.infolist() if not i.is_dir())
        assert files == _tree(dest / "Prezzi ottobre")
        for name in files:
            assert zf.read(name) == (dest / "Prezzi ottobre" / name).read_bytes()
    assert not list(dest.glob("*.part"))


def test_the_zip_conflict_is_asked_too(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A")
    (dest / "I.zip").write_bytes(b"vecchio")
    asked: list[Path] = []

    report = delivery.deliver(plan_delivery(ini, [case.id]), dest, "I",
                              on_conflict=lambda p: asked.append(p) or "keep_both", make_zip=True)

    assert asked == [dest / "I.zip"]
    assert (dest / "I.zip").read_bytes() == b"vecchio"
    assert report.zip_path == dest / "I (2).zip" and zipfile.is_zipfile(report.zip_path)


# ------------------------------------------------------------- last destination ---

def test_the_last_destination_is_remembered_per_initiative(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    other = ws.create_initiative("J")
    assert ws.last_delivery_destination(ini) is None

    ws.remember_delivery_destination(ini, dest)

    assert ws.last_delivery_destination(ws.load("I")) == dest
    assert ws.last_delivery_destination(other) is None
    raw = json.loads((ini.folder / "iniziativa.json").read_text(encoding="utf-8"))
    assert raw["delivery"]["last_destination"] == str(dest) and raw["name"] == "I"


# ------------------------------------------------------ fix round 1: the zip ---

def test_the_zip_holds_only_this_delivery(ws: Workspace, dest: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A", target="atteso.pdf")
    folder = dest / "I" / "MOD_TEST_A"
    folder.mkdir(parents=True)
    (folder / "vecchio.pdf").write_bytes(b"stale")               # an earlier delivery's leftover
    (dest / "I" / "ALTRO").mkdir()
    (dest / "I" / "ALTRO" / "altro.pdf").write_bytes(b"stale")
    (folder / "MOD_TEST_A_ASIS.pdf").write_bytes(b"tenuto")      # kept with "Salta"

    report = delivery.deliver(plan_delivery(ini, [case.id]), dest, "I",
                              on_conflict=lambda _p: "skip", make_zip=True)

    with zipfile.ZipFile(report.zip_path) as zf:
        names = sorted(zf.namelist())
        assert names == ["MOD_TEST_A/MOD_TEST_A_ASIS.pdf", "MOD_TEST_A/MOD_TEST_A_TOBE.pdf",
                         "MOD_TEST_A/atteso.pdf"], "no stale file, the kept one is in"
        assert zf.read("MOD_TEST_A/MOD_TEST_A_ASIS.pdf") == b"tenuto"
    assert report.folder_exists and report.zip_left_out == []


def test_a_symlink_is_never_read_into_the_zip(ws: Workspace, dest: Path, tmp_path: Path):
    ini = ws.create_initiative("I")
    case = _case(ws, ini, "MOD_TEST_A", target=None)
    secret = tmp_path / "segreto.pdf"
    secret.write_bytes(b"segreto")
    link = dest / "I" / "MOD_TEST_A" / "MOD_TEST_A_ASIS.pdf"
    link.parent.mkdir(parents=True)
    try:
        os.symlink(secret, link)
    except OSError:
        pytest.skip("creating a symbolic link needs a privilege this session lacks")

    report = delivery.deliver(plan_delivery(ini, [case.id]), dest, "I",
                              on_conflict=lambda _p: "skip", make_zip=True)

    with zipfile.ZipFile(report.zip_path) as zf:
        assert zf.namelist() == ["MOD_TEST_A/MOD_TEST_A_TOBE.pdf"]
    assert report.zip_left_out == [link]


def test_write_zip_refuses_a_member_outside_the_folder(dest: Path, tmp_path: Path):
    outside = tmp_path / "fuori.pdf"
    outside.write_bytes(PDF)
    with pytest.raises(ValueError):
        delivery._write_zip(dest / "I", [outside], tmp_path / "out.zip")


# ---------------------------------------------- fix round 1: long names, loops ---

def _bounded(fn, *args, timeout: float = 5.0):
    """``fn(*args)`` in a thread: an endless loop fails the test instead of hanging it."""
    import threading

    box: dict = {}

    def run():
        try:
            box["value"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), f"{fn.__name__} did not return within {timeout} s"
    if "error" in box:
        raise box["error"]
    return box["value"]


LONG = "x" * 116 + ".pdf"  # exactly MAX_COMPONENT


def test_unique_with_a_name_at_the_limit():
    used: set[str] = set()
    names = [_bounded(delivery._unique, LONG, used) for _ in range(4)]

    assert len({n.casefold() for n in names}) == 4
    assert all(len(n) <= delivery.MAX_COMPONENT and n.endswith(".pdf") for n in names)
    assert names[1].endswith(" (2).pdf") and names[3].endswith(" (4).pdf")


def test_free_name_with_a_name_at_the_limit(tmp_path: Path):
    taken = tmp_path / LONG
    taken.write_bytes(b"1")
    first = _bounded(delivery._free_name, taken)
    first.write_bytes(b"2")
    second = _bounded(delivery._free_name, taken)

    assert first.name.endswith(" (2).pdf") and second.name.endswith(" (3).pdf")
    assert len(second.name) <= delivery.MAX_COMPONENT


def test_same_named_long_targets_with_long_variants_stay_distinct():
    from types import SimpleNamespace

    a = SimpleNamespace(variant="v" * 200 + "uno")
    b = SimpleNamespace(variant="v" * 200 + "due")
    src_a, src_b = Path("a"), Path("b")
    planned = [(a, LONG, src_a), (b, LONG, src_b)]

    _bounded(delivery._suffix_same_named_targets, planned, list(planned))
    used: set[str] = set()
    final = [_bounded(delivery._unique, name, used) for _case, name, _src in planned]

    assert len({n.casefold() for n in final}) == 2
    assert all(len(n) <= delivery.MAX_COMPONENT and n.endswith(".pdf") for n in final)
    assert all(" (" in name for _case, name, _src in planned), "the variant suffix survives the cut"


def test_numbered_gives_up_instead_of_spinning(monkeypatch):
    monkeypatch.setattr(delivery, "_with_suffix", lambda name, _suffix: name)  # a broken suffixer
    with pytest.raises(ValueError):
        _bounded(delivery._numbered, "a.pdf", lambda _c: True)


def test_safe_component_never_returns_empty_after_the_cut():
    assert safe_component("." * 150 + "x.pdf") == "_"
    assert safe_component(" " + "." * 150 + "x" * 5) == "_"


# ------------------------------------------ fix round 1: renames, bad callbacks ---

def test_a_file_written_under_another_name_is_reported(delivered_once, dest: Path):
    items, old = delivered_once

    report = delivery.deliver(items, dest, "I", on_conflict=lambda _p: "keep_both", make_zip=False)

    assert report.renamed == [
        ("MOD_TEST_A/MOD_TEST_A_ASIS.pdf", old.parent / "MOD_TEST_A_ASIS (2).pdf"),
        ("MOD_TEST_A/MOD_TEST_A_TOBE.pdf", old.parent / "MOD_TEST_A_TOBE (2).pdf")]


def test_a_raising_on_conflict_never_loses_the_report(delivered_once, dest: Path):
    items, _old = delivered_once
    (dest / "I" / "MOD_TEST_A" / "MOD_TEST_A_ASIS.pdf").unlink()

    def broken(_path: Path):
        raise RuntimeError("callback rotto")

    report = delivery.deliver(items, dest, "I", on_conflict=broken, make_zip=True)

    assert [p.name for p in report.delivered] == ["MOD_TEST_A_ASIS.pdf"]
    assert report.failed == [("MOD_TEST_A/MOD_TEST_A_TOBE.pdf", "callback rotto")]
    assert report.zip_path is None and not list(dest.rglob("*.part"))
