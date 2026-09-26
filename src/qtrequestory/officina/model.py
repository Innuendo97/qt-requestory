"""Officina's on-disk model: initiatives, cases and their TARGET/AS-IS/TO-BE
versions (spec §4). Stdlib only — this module must never import
``qtrequestory.officina.pdf`` or any Qt module (see
``tests/test_officina_boundary.py`` and ``tests/test_no_qt_in_core.py``-style
boundary tests).

Layout on disk::

    <root>\\
      <Iniziativa>\\
        iniziativa.json
        casi\\
          <case-id>\\                  case-id = <KEY>[__<variant-slug>]
            caso.json
            payload.json               payload.original.json on first edit
            target\\<original file name> + target.meta.json
            asis\\asis.pdf|html + asis.meta.json (+ asis.previous-<n>.* kept on replace)
            tobe\\v001.pdf|html + v001.meta.json, v002...

The folder is the source of truth: nothing here ever deletes a TO-BE version
on its own, and every write is atomic (temp file + ``fsutil.replace_with_retry``)
so a crash mid-write never leaves a half-written JSON or document behind.
Loading is tolerant by design: a corrupt ``caso.json`` or ``iniziativa.json``
or a version file deleted from disk out from under the app must never raise —
the caller needs to keep working and show what is wrong, not crash (see
``Case.load_error``, ``Initiative.load_error`` and ``Version.missing``).
Writing is not: nothing merges into a JSON file it cannot read (that would
wipe it); the write is refused with a ``ValueError`` instead.

An initiative's identity is its FOLDER (``Initiative.id``); its ``name`` is
only displayed. The case lives in ``model_case``, the documents in
``model_versions``, the JSON helpers in ``model_io``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from qtrequestory.core.fsutil import remove_quietly, replace_with_retry
from qtrequestory.officina.compare.model import Profile
from qtrequestory.officina.model_case import Case, append_history, headers_from, reopen_if_accepted
from qtrequestory.officina.model_case import case_write_lock
from qtrequestory.officina.model_case import case_raw as _case_raw
from qtrequestory.officina.model_case import load_case as _load_case
from qtrequestory.officina.model_case import read_caso_strict as _read_caso_strict
from qtrequestory.officina.model_case import write_review as _write_review
from qtrequestory.officina.model_io import UnreadableJsonError
from qtrequestory.officina.model_io import atomic_copy_text as _atomic_copy_text
from qtrequestory.officina.model_io import read_json_object as _read_json_object
from qtrequestory.officina.model_io import read_json_strict as _read_json_strict
from qtrequestory.officina.model_io import write_bytes_atomic as _write_bytes_atomic
from qtrequestory.officina.model_io import write_json_atomic as _write_json_atomic
from qtrequestory.officina.model_review import (
    DEFAULT_PROFILE,
    NoiseRule,
    initiative_settings_from_json,
    initiative_settings_to_json,
    review_to_json,
)
from qtrequestory.officina.model_versions import SlotKind, Version, content_type_on_disk, is_safe_component
from qtrequestory.officina.model_versions import existing_tobe_numbers as _existing_tobe_numbers
from qtrequestory.officina.model_versions import sniff_doc_type_by_name as _sniff_doc_type_by_name
from qtrequestory.officina.model_versions import write_version as _write_version

__all__ = ["AsisAlreadyExistsError", "Case", "Initiative", "SlotKind", "Version", "Workspace"]

_RESERVED_CHARS = re.compile(r'[\\/:*?"<>|]')
_ASIS_PREV_RE = re.compile(r"^asis\.previous-(\d+)\.meta\.json$")
#: Windows device names: reserved for every path *segment*, case-insensitive,
#: with or without an extension (``NUL``, ``nul.txt``...). ``Path.exists()``
#: is True for these even though nothing can actually be created there, so a
#: folder or case-id that collides with one is silently and permanently
#: broken — ``_safe_folder_name`` escapes them before that can happen.
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"COM{d}" for d in range(10)} | {f"LPT{d}" for d in range(10)}


class AsisAlreadyExistsError(RuntimeError):
    """``add_version("asis", ...)`` was called a second time without a
    ``replace_asis_note``. The existing AS-IS is left untouched."""


@dataclass
class Initiative:
    """One initiative. Its identity is its FOLDER (:attr:`id`): ``name`` is
    only displayed — a folder copied in Explorer keeps the original's name."""

    name: str
    folder: Path
    header_defaults: dict[str, str]
    cases: list[Case] = field(default_factory=list)
    #: ``iniziativa.json`` could not be read: the defaults are unknown, so
    #: nothing is generated and nothing writes over the file.
    load_error: str | None = None
    #: What loading had to leave out (a header default whose value is null).
    load_notes: list[str] = field(default_factory=list)
    #: Phase 2 (``iniziativa.json``: ``profilo``, ``regole_rumore``,
    #: ``preset_rumore``), saved with ``Workspace.save_initiative_settings``.
    profile: Profile = DEFAULT_PROFILE
    noise_rules: list[NoiseRule] = field(default_factory=list)
    noise_presets: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        """The folder's name: what ``Workspace.load`` takes."""
        return self.folder.name


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------ initiatives ---

    def initiatives(self) -> list[Initiative]:
        if not self.root.exists():
            return []
        return [
            self._load_initiative(d)
            for d in sorted(self.root.iterdir())
            if d.is_dir() and (d / "iniziativa.json").exists()
        ]

    def create_initiative(self, name: str) -> Initiative:
        folder = self.root / _safe_folder_name(name)
        if folder.exists():
            raise FileExistsError(f"esiste già un'iniziativa in {folder}")
        folder.mkdir(parents=True)
        (folder / "casi").mkdir()
        _write_json_atomic(folder / "iniziativa.json", {
            "name": name,
            "created": datetime.now().isoformat(),
            "header_defaults": {},
            **initiative_settings_to_json(DEFAULT_PROFILE, [], []),
            "delivery": {},
            "notes": "",
        })
        return Initiative(name=name, folder=folder, header_defaults={}, cases=[])

    def load(self, initiative_id: str) -> Initiative:
        """The initiative in folder ``initiative_id`` (:attr:`Initiative.id`),
        never looked up by its display name. ``FileNotFoundError`` when there
        is no such folder, or ``initiative_id`` is not one plain folder name."""
        if (not is_safe_component(initiative_id)
                or initiative_id.split(".", 1)[0].strip().upper() in _RESERVED_NAMES):
            raise FileNotFoundError(f"iniziativa non trovata: {initiative_id!r}")
        candidate = self.root / initiative_id
        if candidate.is_dir() and (candidate / "iniziativa.json").exists():
            return self._load_initiative(candidate)
        raise FileNotFoundError(f"iniziativa non trovata: {initiative_id!r}")

    def _load_initiative(self, folder: Path) -> Initiative:
        load_error = None
        try:
            raw = _read_json_strict(folder / "iniziativa.json")
        except UnreadableJsonError as exc:
            raw, load_error = {}, str(exc)
        name = str(raw.get("name") or folder.name)
        header_defaults, notes = headers_from(raw.get("header_defaults"), "iniziativa.json")
        profile, noise_rules, noise_presets = initiative_settings_from_json(raw, notes)
        cases_dir = folder / "casi"
        cases: list[Case] = []
        if cases_dir.exists():
            for case_dir in sorted(cases_dir.iterdir()):
                if case_dir.is_dir() and (case_dir / "caso.json").exists():
                    cases.append(_load_case(case_dir))
        return Initiative(name=name, folder=folder, header_defaults=header_defaults, cases=cases,
                          load_error=load_error, load_notes=notes, profile=profile,
                          noise_rules=noise_rules, noise_presets=noise_presets)

    # --------------------------------------------------------------- delivery ---

    def last_delivery_destination(self, ini: Initiative) -> Path | None:
        """The folder the initiative was last delivered to (``iniziativa.json``
        ``delivery.last_destination``), or None."""
        raw = _read_json_object(ini.folder / "iniziativa.json")
        delivery = raw.get("delivery")
        value = delivery.get("last_destination") if isinstance(delivery, dict) else None
        if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
            return None
        return Path(value)

    def remember_delivery_destination(self, ini: Initiative, destination: Path) -> None:
        """Record the destination in ``iniziativa.json``. ``ValueError`` (and
        nothing written) when the file cannot be read: merging into ``{}``
        would wipe the name and the header defaults."""
        meta = ini.folder / "iniziativa.json"
        raw = _read_initiative_for_merge(ini, "destinazione non ricordata")
        delivery = raw.get("delivery")
        delivery = dict(delivery) if isinstance(delivery, dict) else {}
        delivery["last_destination"] = str(destination)
        delivery["last_at"] = datetime.now().isoformat()
        raw["delivery"] = delivery
        _write_json_atomic(meta, raw)

    def save_initiative_settings(self, ini: Initiative) -> None:
        """Merge ``profile``, ``noise_rules`` and ``noise_presets`` into
        ``iniziativa.json`` (the legacy ``noise_rules`` key goes: it was read
        once). ``ValueError`` and nothing written when the file cannot be read."""
        raw = _read_initiative_for_merge(ini, "impostazioni non salvate")
        raw.pop("noise_rules", None)
        raw.update(initiative_settings_to_json(ini.profile, ini.noise_rules, ini.noise_presets))
        _write_json_atomic(ini.folder / "iniziativa.json", raw)

    # ------------------------------------------------------------------ cases ---

    def add_case(
        self, ini: Initiative, key: str, variant: str, payload: dict, *,
        env: str, source_fdi: str | None,
    ) -> Case:
        # The whole id is one path segment (folder name), so it goes through
        # the same folder-safety sanitiser as an initiative name (reserved
        # chars, trailing dot/space, reserved Windows device names): only
        # `key` can carry those (variant is already `_slug`-ged to plain
        # lowercase/dash). `case.key` itself keeps the caller's original,
        # unsanitised value — only the on-disk id/folder name is escaped.
        case_id = _safe_folder_name(
            key if not variant else f"{key}__{_slug(variant)}", fallback="caso")
        case_dir = ini.folder / "casi" / case_id
        if case_dir.exists():
            raise FileExistsError(f"esiste già un caso con id {case_id!r}")
        case_dir.mkdir(parents=True)
        case = Case(
            id=case_id, key=key, variant=variant, env=env,
            headers={}, drop_postman_token=False,
            correlation="new", correlation_value="",
            link_policy="remove", status="open", notes="",
            folder=case_dir, load_error=None, source_fdi=source_fdi,
        )
        raw = {**_case_raw(case), **review_to_json(case.review), "history": []}
        _write_json_atomic(case_dir / "caso.json", raw)
        _write_json_atomic(case_dir / "payload.json", payload)
        ini.cases.append(case)
        return case

    def save_review(self, case: Case) -> None:
        """Merge ONLY ``case.review`` into ``caso.json`` (``profilo``, ``tolleranze``,
        ``non_variabili``, ``segnate``, ``non_risolte``, ``regole_rumore``, ``riepilogo``);
        refused like :meth:`save_case`. The one writer of the review state (R8)."""
        _write_review(case)

    def save_case(self, case: Case) -> None:
        """Merge ``case`` into its ``caso.json`` (history, unknown keys and the
        review keys kept: those are :meth:`save_review`'s). ``ValueError`` and
        nothing written for a case loaded with a ``load_error``, or whose file
        is unreadable now: the merge would start from ``{}`` and wipe env,
        headers and source FDI."""
        if case.load_error:
            raise UnreadableJsonError(
                f"caso.json non è leggibile ({case.load_error}): il caso non viene salvato, "
                "correggere o ripristinare il file")
        case_dir = case.folder
        case_dir.mkdir(parents=True, exist_ok=True)
        with case_write_lock(case_dir):  # the merge inside the lock (R16)
            raw = _read_caso_strict(case_dir)
            raw.update(_case_raw(case))
            raw.setdefault("history", [])
            _write_json_atomic(case_dir / "caso.json", raw)

    # ---------------------------------------------------------------- payload ---

    def payload(self, case: Case) -> dict:
        p = case.folder / "payload.json"
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_payload(self, case: Case, payload: dict) -> None:
        case_dir = case.folder
        current = case_dir / "payload.json"
        original = case_dir / "payload.original.json"
        if current.exists() and not original.exists():
            _atomic_copy_text(current, original)
        _write_json_atomic(current, payload)

    # ----------------------------------------------------------------- target ---

    def set_target(self, case: Case, src: Path) -> Version:
        """Copy ``src`` in as the case's TARGET, keeping its original name.

        Ordered so a crash never leaves the target folder showing neither
        version: the new content is committed first (an atomic rename onto
        the final name — the old file, if same-named, is only ever replaced
        by a complete new one), then the new ``target.meta.json`` is written
        (so a crash before this point still has the *old* meta pointing at
        a file that exists), and only then are stray files from a previous,
        differently-named target removed (a crash before this point simply
        leaves a harmless extra file, cleaned up by the next successful call).
        """
        src = Path(src)
        target_dir = case.folder / "target"
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / src.name
        _write_bytes_atomic(dest, src.read_bytes())  # 1. commit the new content
        created = datetime.now()
        doc_type = _sniff_doc_type_by_name(src.name)
        _write_json_atomic(target_dir / "target.meta.json", {
            "original_name": src.name, "doc_type": doc_type, "created": created.isoformat(),
        })  # 2. point the meta at it
        for existing in target_dir.iterdir():  # 3. only now drop stray files
            if existing == dest or existing.name == "target.meta.json":
                continue
            remove_quietly(existing)
        return Version(
            kind="target", number=0, path=dest, doc_type=doc_type, created=created,
            meta={"original_name": src.name}, missing=False,
        )

    # --------------------------------------------------------------- versions ---

    def add_version(
        self, case: Case, kind: Literal["asis", "tobe"], content: bytes, doc_type: str, meta: dict,
        *, replace_asis_note: str | None = None,
    ) -> Version:
        if doc_type not in ("pdf", "html"):
            raise ValueError(f"doc_type non valido: {doc_type!r}")
        if kind == "tobe":
            version = self._add_tobe(case, content, doc_type, meta)
        elif kind == "asis":
            version = self._add_asis(case, content, doc_type, meta, replace_asis_note)
        else:
            raise ValueError(f"kind non valido: {kind!r}")
        reopen_if_accepted(case)  # acceptance is of a version: a new one reopens
        return version

    def _add_tobe(self, case: Case, content: bytes, doc_type: str, meta: dict) -> Version:
        tobe_dir = case.folder / "tobe"
        tobe_dir.mkdir(parents=True, exist_ok=True)
        existing = _existing_tobe_numbers(tobe_dir)
        number = (max(existing) + 1) if existing else 1
        return _write_version(tobe_dir, f"v{number:03d}", kind="tobe", number=number,
                               content=content, doc_type=doc_type, meta=meta)

    def _add_asis(self, case: Case, content: bytes, doc_type: str, meta: dict,
                  replace_note: str | None) -> Version:
        asis_dir = case.folder / "asis"
        asis_dir.mkdir(parents=True, exist_ok=True)
        existing_meta = asis_dir / "asis.meta.json"
        if existing_meta.exists():
            if not replace_note:
                raise AsisAlreadyExistsError(
                    "esiste già un AS-IS per questo caso: indicare una nota per sostituirlo")
            _read_caso_strict(case.folder)  # unreadable: refuse before moving anything
            self._archive_previous_asis(asis_dir, existing_meta)
            append_history(case.folder, replace_note)
        return _write_version(asis_dir, "asis", kind="asis", number=0,
                               content=content, doc_type=doc_type, meta=meta)

    @staticmethod
    def _archive_previous_asis(asis_dir: Path, existing_meta: Path) -> None:
        prev_numbers = [int(m.group(1)) for p in asis_dir.iterdir() if (m := _ASIS_PREV_RE.match(p.name))]
        prev_n = (max(prev_numbers) + 1) if prev_numbers else 1
        # the content file on disk, never a name built from the (hand-editable) meta
        old_doc_type = content_type_on_disk(asis_dir, "asis")
        if old_doc_type is not None:
            replace_with_retry(asis_dir / f"asis.{old_doc_type}",
                               asis_dir / f"asis.previous-{prev_n}.{old_doc_type}")
        replace_with_retry(existing_meta, asis_dir / f"asis.previous-{prev_n}.meta.json")


# --------------------------------------------------------------------- helpers ---

def _read_initiative_for_merge(ini: Initiative, what: str) -> dict:
    """``iniziativa.json`` to merge into; ``UnreadableJsonError`` when it (or
    the initiative as loaded) cannot be read."""
    if ini.load_error:
        raise UnreadableJsonError(f"{ini.load_error}: {what}")
    try:
        raw = _read_json_strict(ini.folder / "iniziativa.json")
    except UnreadableJsonError as exc:
        raise UnreadableJsonError(f"{exc}: {what}") from None
    return raw or {"name": ini.name, "header_defaults": dict(ini.header_defaults)}


def _slug(variant: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", variant.lower()).strip("-")


def _safe_folder_name(name: str, *, fallback: str = "iniziativa") -> str:
    cleaned = _RESERVED_CHARS.sub("_", name).strip()
    cleaned = cleaned.rstrip(" .")  # Windows forbids a trailing dot/space
    cleaned = cleaned or fallback
    # A reserved device name is broken as a path segment however deep it is
    # (Path.exists() is True for it, but nothing can be created there), so
    # it must be escaped whether or not it "looks like" the whole folder —
    # checked case-insensitively, against the name before any extension.
    stem = cleaned.split(".", 1)[0]
    if stem.upper() in _RESERVED_NAMES:
        # Insert right after the stem, not appended at the very end: for
        # "nul.txt" the fix must be "nul_1.txt" (stem "nul_1"), not
        # "nul.txt_1" (still stem "nul" before the first dot).
        cleaned = f"{stem}_1{cleaned[len(stem):]}"
    return cleaned
