"""The testers' delivery folder (spec §8 "Consegna…").

Layout, under ``<destination>\\<Iniziativa>\\``::

    <KEY>\\<KEY>_ASIS.<ext>
    <KEY>\\<KEY>_TOBE.<ext>             the latest TO-BE
    <KEY>\\<target original name>

Several delivered cases with the same key share the ``<KEY>`` folder and are
told apart by their variant: ``<KEY>_<variant>_ASIS/TOBE.<ext>``. Their
targets keep their names; two targets with the same name get
`` (<variant>)`` before the extension. A slot that is empty (or whose file is
gone) is skipped and listed (:class:`MissingSlot`), never invented.

**Path safety.** Keys, variants, target names and the initiative name are user
data, so each becomes exactly ONE path component through
:func:`safe_component` (Windows-invalid and control characters replaced,
trailing dots and spaces stripped, device names such as ``CON`` or ``COM1``
escaped, never ``..`` or empty). Every final destination is checked again to
lie inside ``<destination>\\<Iniziativa>`` before anything is written, and a
source must lie inside its case folder (a hand-edited ``target.meta.json``
cannot make the delivery copy some other file).

**Writes.** Every file is copied to a temporary ``.<name>.<random>.part`` in
its final folder and only then renamed onto its name, so a delivery never
leaves a half-written document. An existing file is never overwritten
without asking ``on_conflict`` ("replace" / "keep_both" → `` (2)``, `` (3)``…
/ "skip"). On Windows ``os.rename`` refuses to overwrite, which closes the
window between "the name is free" and "the name is taken" (a new file lands
there meanwhile: ``on_conflict`` is asked about it). A file written under
another name than planned is listed in ``DeliveryReport.renamed``. The
sources are all checked before the first copy; a failure after that (any
exception, ``on_conflict``'s included) is reported per file
(:class:`DeliveryReport`) and the other files are still delivered — nothing
already delivered is rolled back silently.

**Zip** (optional): ``<destination>\\<Iniziativa>.zip`` holds exactly THIS
delivery: the files it wrote plus the existing files the user chose to keep
("Salta") at the planned paths — never anything else that happens to be in
the folder (an earlier delivery's leftovers). Entries are relative to
``<Iniziativa>`` with forward slashes, ZIP_DEFLATED; each one must lie inside
the folder, and a symbolic link (or a file reached through one) is never
read: it is left out and listed in ``DeliveryReport.zip_left_out``. The zip
is written through a temporary file like the documents, and only when every
document was delivered: a zip of an incomplete delivery would travel on its
own and nobody would know it is incomplete.

Stdlib only, Qt-free.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from qtrequestory.core.fsutil import is_within, real_is_within, remove_quietly, replace_with_retry
from qtrequestory.officina.model import Case, Initiative, Version

__all__ = [
    "Conflict", "DeliveryError", "DeliveryItem", "DeliveryPlan", "DeliveryReport", "MAX_COMPONENT",
    "MissingSlot", "build_plan", "deliver", "delivery_folder", "find_conflicts", "plan_delivery",
    "run_delivery", "safe_component", "zip_destination",
]

Conflict = Literal["replace", "keep_both", "skip"]
OnConflict = Callable[[Path], Conflict]

#: Longest single component written (OneDrive/SharePoint paths get long fast;
#: the whole path of a synced file is limited to about 400 characters).
MAX_COMPONENT = 120
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_DEVICES = ({"CON", "PRN", "AUX", "NUL"} | {f"COM{d}" for d in "0123456789¹²³"}
            | {f"LPT{d}" for d in "0123456789¹²³"})
#: Most candidates tried for a free " (n)" name before giving up.
MAX_ATTEMPTS = 10_000
#: Longest variant quoted in a target's " (<variant>)" suffix.
_VARIANT_IN_SUFFIX = 40


@dataclass(frozen=True)
class DeliveryItem:
    """One file to deliver: ``dest_rel`` is relative to
    ``<destination>\\<Iniziativa>``, with forward slashes."""

    case_id: str
    src: Path
    dest_rel: str


@dataclass(frozen=True)
class MissingSlot:
    """A slot not delivered: ``reason`` is "absent" (never made), "gone"
    (its file was deleted from disk), "outside" (the file named by the
    metadata is not inside the case folder) or "broken" (the metadata cannot
    name a file at all: ``Version.broken``)."""

    case_id: str
    key: str
    variant: str
    slot: Literal["asis", "tobe", "target"]
    reason: Literal["absent", "gone", "outside", "broken"]


@dataclass(frozen=True)
class DeliveryPlan:
    items: list[DeliveryItem]
    missing: list[MissingSlot]


@dataclass
class DeliveryReport:
    """What a delivery did.

    ``delivered``: files written (the zip last); ``skipped``: existing files
    left as they were ("Salta"); ``renamed``: ``(dest_rel, written path)`` of
    the files written under another name because the planned one was taken
    ("Mantieni entrambi", asked or not); ``failed``: ``(dest_rel or zip name,
    reason)``; ``zip_left_out``: files not put in the zip (a symbolic link);
    ``folder_exists``: the delivery folder exists afterwards (computed in the
    worker, so the UI never stats a synced folder on its thread)."""

    folder: Path
    delivered: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    renamed: list[tuple[str, Path]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    zip_path: Path | None = None
    zip_left_out: list[Path] = field(default_factory=list)
    cancelled: bool = False
    folder_exists: bool = False
    #: Why the destination was not remembered for next time ("" when it was).
    remember_problem: str = ""


class DeliveryError(RuntimeError):
    """Something was not delivered; ``report`` says what was and what was not."""

    def __init__(self, report: DeliveryReport) -> None:
        self.report = report
        failed = "; ".join(f"{name}: {reason}" for name, reason in report.failed)
        super().__init__(f"consegna incompleta ({len(report.delivered)} file consegnati): {failed}")


# ------------------------------------------------------------------- names ---

def safe_component(name: str, fallback: str = "_") -> str:
    """``name`` as one Windows-safe path component (see the module docstring)."""
    cleaned = _INVALID.sub("_", str(name)).strip().rstrip(" .")
    if not cleaned or set(cleaned) <= {"."}:
        cleaned = fallback
    stem, dot, ext = cleaned.partition(".")
    device = stem.rstrip(" ")
    if device.upper() in _DEVICES:
        cleaned = f"{device}_{stem[len(device):]}{dot}{ext}"
    if len(cleaned) > MAX_COMPONENT:
        root, suffix = _split_ext(cleaned)
        cleaned = root[:MAX_COMPONENT - len(suffix)].rstrip(" .") + suffix
        if not cleaned or set(cleaned) <= {"."} or cleaned == suffix:
            cleaned = fallback  # the cut left nothing usable
    return cleaned


def _split_ext(name: str) -> tuple[str, str]:
    """``(root, ext)``; an "extension" over 16 characters is part of the root."""
    root, ext = os.path.splitext(name)
    return (root, ext) if len(ext) <= 16 else (name, "")


def _with_suffix(name: str, suffix: str) -> str:
    """``atteso.pdf`` + `` (x)`` → ``atteso (x).pdf``. The root is cut BEFORE
    the suffix goes on, so the suffix always survives the length limit (a cut
    after it would drop it, and a " (n)" loop would never see a new name)."""
    root, ext = _split_ext(safe_component(name))
    suffix = suffix[:MAX_COMPONENT - len(ext) - 1]
    root = root[:MAX_COMPONENT - len(ext) - len(suffix)].rstrip(" .") or "_"
    return safe_component(f"{root}{suffix}{ext}")


def delivery_folder(destination: Path, ini_name: str) -> Path:
    return Path(destination) / safe_component(ini_name)


def zip_destination(destination: Path, ini_name: str) -> Path:
    return Path(destination) / f"{safe_component(ini_name)}.zip"


# -------------------------------------------------------------------- plan ---

def plan_delivery(ini: Initiative, case_ids: Sequence[str]) -> list[DeliveryItem]:
    """The files to deliver for ``case_ids`` (in the initiative's order)."""
    return build_plan(ini, case_ids).items


def build_plan(ini: Initiative, case_ids: Sequence[str]) -> DeliveryPlan:
    """The files to deliver and the slots skipped (see :class:`MissingSlot`)."""
    wanted = set(case_ids)
    groups: dict[str, list[Case]] = {}
    for case in ini.cases:
        if case.id in wanted:
            groups.setdefault(safe_component(case.key).casefold(), []).append(case)
    items: list[DeliveryItem] = []
    missing: list[MissingSlot] = []
    for cases in groups.values():
        folder = safe_component(cases[0].key)
        several = len(cases) > 1
        planned: list[tuple[Case, str, Path]] = []  # (case, file name, source)
        targets: list[tuple[Case, str, Path]] = []
        for case in cases:
            prefix = safe_component(case.key)
            if several and case.variant.strip():
                prefix = safe_component(f"{prefix}_{case.variant.strip()}")
            for slot, version in (("asis", case.asis()), ("tobe", case.latest_tobe())):
                reason = _unusable(case, version)
                if reason:
                    missing.append(MissingSlot(case.id, case.key, case.variant, slot, reason))
                else:
                    name = _with_suffix(f"{prefix}.{version.doc_type}", f"_{slot.upper()}")
                    planned.append((case, name, version.path))
            target = case.target()
            reason = _unusable(case, target)
            if reason:
                missing.append(MissingSlot(case.id, case.key, case.variant, "target", reason))
            else:
                name = safe_component(target.meta.get("original_name") or target.path.name, "target")
                targets.append((case, name, target.path))
                planned.append((case, name, target.path))
        _suffix_same_named_targets(planned, targets)
        used: set[str] = set()
        for case, name, src in planned:
            name = _unique(name, used)
            items.append(DeliveryItem(case.id, src, f"{folder}/{name}"))
    return DeliveryPlan(items, missing)


def _unusable(case: Case, version: Version | None) -> str:
    if version is None:
        return "absent"
    if version.broken:  # hand-edited metadata that cannot name a file
        return "broken"
    if not real_is_within(version.path, case.folder):
        return "outside"
    if version.missing or not version.path.is_file():
        return "gone"
    return ""


def _suffix_same_named_targets(planned: list[tuple[Case, str, Path]],
                               targets: list[tuple[Case, str, Path]]) -> None:
    counts: dict[str, int] = {}
    for _case, name, _src in targets:
        counts[name.casefold()] = counts.get(name.casefold(), 0) + 1
    for i, (case, name, src) in enumerate(planned):
        is_target = any(case is t_case and src == t_src for t_case, _n, t_src in targets)
        if is_target and counts[name.casefold()] > 1 and case.variant.strip():
            variant = case.variant.strip()[:_VARIANT_IN_SUFFIX]
            planned[i] = (case, _with_suffix(name, f" ({variant})"), src)


def _numbered(name: str, taken: Callable[[str], bool], *, start: int = 2) -> str:
    """The first of ``name (start)``, ``name (start+1)``… that is not ``taken``.
    Bounded: ``ValueError`` after :data:`MAX_ATTEMPTS` candidates, or as soon
    as a candidate stops changing (it cannot with :func:`_with_suffix`, but a
    loop relying on that must not be able to spin forever)."""
    previous = name
    for n in range(start, start + MAX_ATTEMPTS):
        candidate = _with_suffix(name, f" ({n})")
        if candidate.casefold() == previous.casefold():
            break
        if not taken(candidate):
            return candidate
        previous = candidate
    raise ValueError(f"nessun nome libero per {name!r}")


def _unique(name: str, used: set[str]) -> str:
    candidate = name if name.casefold() not in used else \
        _numbered(name, lambda c: c.casefold() in used)
    used.add(candidate.casefold())
    return candidate


# --------------------------------------------------------------- delivery ---

def _destination_of(folder: Path, dest_rel: str) -> Path:
    """``folder / dest_rel``, or ``ValueError`` when it would not lie strictly
    inside ``folder`` (an absolute path, a drive, ``..``)."""
    parts = dest_rel.split("/")
    if not parts or any(p != safe_component(p) for p in parts):
        raise ValueError(f"percorso di consegna non valido: {dest_rel!r}")
    final = folder.joinpath(*parts)
    if not is_within(final, folder) or os.path.normcase(os.path.abspath(final)) == \
            os.path.normcase(os.path.abspath(folder)):
        raise ValueError(f"percorso fuori dalla cartella di consegna: {dest_rel!r}")
    return final


def find_conflicts(items: Sequence[DeliveryItem], destination: Path, ini_name: str, *,
                   make_zip: bool) -> list[Path]:
    """The files a delivery would find already there (to ask about them first)."""
    folder = delivery_folder(destination, ini_name)
    found: list[Path] = []
    for item in items:
        try:
            final = _destination_of(folder, item.dest_rel)
        except ValueError:
            continue
        if os.path.lexists(final):
            found.append(final)
    archive = zip_destination(destination, ini_name)
    if make_zip and os.path.lexists(archive):
        found.append(archive)
    return found


def deliver(items: Sequence[DeliveryItem], destination: Path, ini_name: str, *,
            on_conflict: OnConflict, make_zip: bool, cancel=None) -> DeliveryReport:
    """Copy ``items`` (and zip them): the full report, never an exception for
    a file that could not be delivered. ``ValueError`` for a destination that
    is not an absolute path. ``cancel`` (anything with ``is_set()``) is
    checked before each file; a cancelled delivery builds no zip."""
    report = _deliver(items, destination, ini_name, on_conflict=on_conflict, make_zip=make_zip,
                      cancel=cancel)
    report.folder_exists = report.folder.is_dir()
    return report


def _deliver(items: Sequence[DeliveryItem], destination: Path, ini_name: str, *,
             on_conflict: OnConflict, make_zip: bool, cancel) -> DeliveryReport:
    destination = Path(destination)
    if not destination.is_absolute():
        raise ValueError(f"la cartella di destinazione deve essere un percorso assoluto: {destination}")
    folder = delivery_folder(destination, ini_name)
    report = DeliveryReport(folder)
    targets: list[tuple[DeliveryItem, Path]] = []
    for item in items:
        try:
            targets.append((item, _destination_of(folder, item.dest_rel)))
        except ValueError as exc:
            report.failed.append((item.dest_rel, str(exc)))
        else:
            if not Path(item.src).is_file():
                report.failed.append((item.dest_rel, f"il file di origine non c'è più: {item.src}"))
    if report.failed:
        return report  # nothing copied: the plan is stale or broken

    for item, final in targets:
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            return report
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            if not real_is_within(final.parent, folder):
                raise ValueError("la cartella di consegna porta fuori dalla destinazione")
            written = _commit(final, _file_writer(item.src), on_conflict)
        except Exception as exc:  # noqa: BLE001 - one file never loses the report
            report.failed.append((item.dest_rel, str(exc) or type(exc).__name__))
            continue
        if written is None:
            report.skipped.append(final)
            continue
        report.delivered.append(written)
        if written != final:
            report.renamed.append((item.dest_rel, written))

    if make_zip and not report.failed:
        archive = zip_destination(destination, ini_name)
        members = [*report.delivered, *report.skipped]

        def write_zip(tmp: Path) -> None:
            report.zip_left_out[:] = _write_zip(folder, members, tmp)

        try:
            written = _commit(archive, write_zip, on_conflict)
        except Exception as exc:  # noqa: BLE001 - the report is what matters
            report.failed.append((archive.name, str(exc) or type(exc).__name__))
        else:
            if written is None:
                report.skipped.append(archive)
            else:
                report.zip_path = written
                report.delivered.append(written)
    return report


def run_delivery(items: list[DeliveryItem], destination: Path, ini_name: str, *,
                 on_conflict: OnConflict, make_zip: bool) -> list[Path]:
    """:func:`deliver`, returning the files written (the zip last). Raises
    :class:`DeliveryError` — with the report — when anything failed."""
    report = deliver(items, destination, ini_name, on_conflict=on_conflict, make_zip=make_zip)
    if report.failed:
        raise DeliveryError(report)
    return report.delivered


# ------------------------------------------------------------------ writing ---

def _copy_bytes(src: Path, dst: Path) -> None:
    shutil.copyfile(src, dst)


def _file_writer(src: Path) -> Callable[[Path], None]:
    return lambda tmp: _copy_bytes(Path(src), tmp)


def _commit(final: Path, write: Callable[[Path], None], on_conflict: OnConflict) -> Path | None:
    """Write through ``write(tmp)`` and move the result onto ``final`` (or the
    name ``on_conflict`` leads to). The written path, or None when skipped."""
    tmp = final.parent / f".{final.name}.{uuid.uuid4().hex[:12]}.part"
    try:
        write(tmp)
        while True:
            if not os.path.lexists(final):
                try:
                    os.rename(tmp, final)  # Windows: refuses to overwrite
                    return final
                except FileExistsError:
                    continue  # appeared meanwhile: ask about it
            choice = on_conflict(final)
            if choice == "skip":
                return None
            if choice == "replace":
                replace_with_retry(tmp, final)
                return final
            if choice != "keep_both":
                raise ValueError(f"scelta non valida per un file esistente: {choice!r}")
            final = _free_name(final)
    finally:
        remove_quietly(tmp)


def _free_name(path: Path) -> Path:
    """The first ``<name> (n).<ext>`` next to ``path`` that is free on disk."""
    return path.with_name(_numbered(path.name, lambda c: os.path.lexists(path.with_name(c))))


def _write_zip(folder: Path, members: Sequence[Path], out: Path) -> list[Path]:
    """``members`` (this delivery's files, inside ``folder``) into ``out``,
    named relative to ``folder`` with forward slashes. Returns the ones left
    out: a symbolic link, or a file whose real path leaves ``folder`` (a
    junction on the way), is never read."""
    left_out: list[Path] = []
    real_folder = Path(os.path.realpath(folder))
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((Path(p) for p in members),
                           key=lambda p: p.relative_to(folder).as_posix().casefold()):
            if not is_within(path, folder):
                raise ValueError(f"file fuori dalla cartella di consegna: {path}")
            if (os.path.islink(path) or not path.is_file()
                    or not is_within(Path(os.path.realpath(path)), real_folder)):
                left_out.append(path)
                continue
            zf.write(path, path.relative_to(folder).as_posix())
    return left_out
