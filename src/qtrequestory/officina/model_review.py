"""The review state of a case (``Case.review``) and the initiative's review
settings, as stored in ``caso.json`` / ``iniziativa.json`` (spec §5.5).

``caso.json`` keys: ``profilo``, ``tolleranze``, ``non_variabili``,
``segnate``, ``non_risolte``, ``regole_rumore``, ``riepilogo``.
``iniziativa.json`` keys: ``profilo``, ``regole_rumore``, ``preset_rumore``
(plus the legacy ``noise_rules``, read once when ``regole_rumore`` is absent).

Backward compatible by construction: a missing key is the empty value, so a
file written by 1.2.0 loads as ``Review()``. Loading never raises: a value
that cannot be used (hand-edited junk) is dropped with an Italian line in the
caller's ``load_notes``. A noise rule is ``{"name", "pattern", "enabled"}``
(the legacy form is ``{"name", "pattern"}`` or a bare pattern string).

Stdlib only; no Qt.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from qtrequestory.officina.compare.model import PROFILES, Anchor, CaseSummary, Profile

__all__ = [
    "DEFAULT_PROFILE", "Mark", "NoiseRule", "Review", "Tolerance",
    "initiative_settings_from_json", "initiative_settings_to_json", "noise_rules_from_json",
    "noise_rules_to_json", "review_from_json", "review_to_json",
]

DEFAULT_PROFILE: Profile = "tollerante"

T = TypeVar("T")


@dataclass
class Tolerance:
    """A difference tolerated by hand: valid while BOTH the anchor and the
    normalised generated text still match."""

    anchor: Anchor
    generated: str
    note: str
    when: str


@dataclass
class Mark:
    """A difference "segnata fatta" in TO-BE ``version`` ("da verificare"
    until a newer TO-BE is compared)."""

    anchor: Anchor
    generated: str
    version: int
    when: str


@dataclass
class NoiseRule:
    name: str
    pattern: str
    enabled: bool = True


@dataclass
class Review:
    """Per case, never inherited. ``profile`` None = "come l'iniziativa"."""

    profile: Profile | None = None
    tolerances: list[Tolerance] = field(default_factory=list)
    not_variables: list[tuple[Anchor, str]] = field(default_factory=list)   # (anchor, when)
    marks: list[Mark] = field(default_factory=list)
    #: "non risolta" entries: (anchor, version the mark was MADE in (R10), normalised generated
    #: text at verification — R31: the flag lasts while the diff is there with this text; "" =
    #: unknown, a file written before the field existed)
    unresolved: list[tuple[Anchor, int, str]] = field(default_factory=list)
    noise_rules: list[NoiseRule] = field(default_factory=list)
    summary: CaseSummary | None = None


# ------------------------------------------------------------------- caso.json ---

def review_to_json(review: Review) -> dict:
    """The ``caso.json`` keys of ``review``, in a fixed order."""
    return {
        "profilo": review.profile,
        "tolleranze": [{"anchor": t.anchor.to_json(), "generato": t.generated, "nota": t.note, "quando": t.when}
                       for t in review.tolerances],
        "non_variabili": [{"anchor": a.to_json(), "quando": when} for a, when in review.not_variables],
        "segnate": [{"anchor": m.anchor.to_json(), "generato": m.generated, "versione": m.version,
                     "quando": m.when} for m in review.marks],
        "non_risolte": [{"anchor": a.to_json(), "versione": v, "generato": g} for a, v, g in review.unresolved],
        "regole_rumore": noise_rules_to_json(review.noise_rules),
        "riepilogo": review.summary.to_json() if review.summary is not None else None,
    }


def review_from_json(raw: dict, notes: list[str]) -> Review:
    """The review in a ``caso.json`` object; junk is dropped with a line in ``notes``."""
    where = "caso.json"
    review = Review()
    profile = raw.get("profilo")
    if profile is not None:
        if profile in PROFILES:
            review.profile = profile
        else:
            notes.append(f"{where}: profilo «{profile}» non riconosciuto, si usa quello dell'iniziativa")
    review.tolerances = _entries(raw, "tolleranze", _tolerance, notes)
    review.not_variables = _entries(raw, "non_variabili", _not_variable, notes)
    review.marks = _entries(raw, "segnate", _mark, notes)
    review.unresolved = _entries(raw, "non_risolte", _unresolved, notes)
    review.noise_rules = noise_rules_from_json(raw.get("regole_rumore"), f"{where}: regole_rumore", notes)
    summary = raw.get("riepilogo")
    if summary is not None:
        review.summary = CaseSummary.from_json(summary)
        if review.summary is None:
            notes.append(f"{where}: il riepilogo non è leggibile ed è stato ignorato")
    return review


def _entries(raw: dict, key: str, parse: Callable[[dict], T | None], notes: list[str]) -> list[T]:
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        notes.append(f"caso.json: «{key}» non è un elenco ed è stato ignorato")
        return []
    out: list[T] = []
    for n, item in enumerate(value, start=1):
        parsed = parse(item) if isinstance(item, dict) else None
        if parsed is None:
            notes.append(f"caso.json: «{key}», voce n. {n} non leggibile: scartata")
        else:
            out.append(parsed)
    return out


def _is_int(value: object) -> bool:
    return type(value) is int


def _tolerance(item: dict) -> Tolerance | None:
    anchor = Anchor.from_json(item.get("anchor"))
    generated, note, when = item.get("generato"), item.get("nota", ""), item.get("quando", "")
    if anchor is None or not all(isinstance(v, str) for v in (generated, note, when)):
        return None
    return Tolerance(anchor, generated, note, when)


def _not_variable(item: dict) -> tuple[Anchor, str] | None:
    anchor, when = Anchor.from_json(item.get("anchor")), item.get("quando", "")
    return (anchor, when) if anchor is not None and isinstance(when, str) else None


def _mark(item: dict) -> Mark | None:
    anchor = Anchor.from_json(item.get("anchor"))
    generated, version, when = item.get("generato"), item.get("versione"), item.get("quando", "")
    if anchor is None or not isinstance(generated, str) or not _is_int(version) or not isinstance(when, str):
        return None
    return Mark(anchor, generated, version, when)


def _unresolved(item: dict) -> tuple[Anchor, int, str] | None:
    anchor, version, generated = Anchor.from_json(item.get("anchor")), item.get("versione"), item.get("generato", "")
    if anchor is None or not _is_int(version) or not isinstance(generated, str):
        return None
    return anchor, version, generated


# ----------------------------------------------------------------- noise rules ---

def noise_rules_to_json(rules: list[NoiseRule]) -> list[dict]:
    return [{"name": r.name, "pattern": r.pattern, "enabled": r.enabled} for r in rules]


def noise_rules_from_json(raw: object, where: str, notes: list[str]) -> list[NoiseRule]:
    """Rules from ``[{"name", "pattern", "enabled"?}]`` or bare pattern
    strings (the legacy form); junk dropped with a note. The regex is NOT
    compiled here: a rule that does not compile is reported by the engine."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        notes.append(f"{where}: non è un elenco ed è stato ignorato")
        return []
    rules: list[NoiseRule] = []
    for n, item in enumerate(raw, start=1):
        if isinstance(item, str) and item:
            rules.append(NoiseRule(item, item))
            continue
        if isinstance(item, dict):
            name, pattern, enabled = item.get("name"), item.get("pattern"), item.get("enabled", True)
            if isinstance(pattern, str) and pattern and isinstance(enabled, bool) \
                    and (name is None or isinstance(name, str)):
                rules.append(NoiseRule(name or pattern, pattern, enabled))
                continue
        notes.append(f"{where}: la regola n. {n} non è leggibile ed è stata ignorata")
    return rules


# ------------------------------------------------------------- iniziativa.json ---

def initiative_settings_from_json(raw: dict, notes: list[str]) -> tuple[Profile, list[NoiseRule], list[str]]:
    """``(profile, noise_rules, noise_presets)`` of an ``iniziativa.json``
    object. ``regole_rumore`` wins; the legacy ``noise_rules`` is read only
    when it is absent (and disappears at the next save)."""
    where = "iniziativa.json"
    profile: Profile = DEFAULT_PROFILE
    value = raw.get("profilo")
    if value is not None:
        if value in PROFILES:
            profile = value
        else:
            notes.append(f"{where}: profilo «{value}» non riconosciuto, si usa «{DEFAULT_PROFILE}»")
    if "regole_rumore" in raw:
        rules = noise_rules_from_json(raw.get("regole_rumore"), f"{where}: regole_rumore", notes)
    else:
        rules = noise_rules_from_json(raw.get("noise_rules"), f"{where}: noise_rules", notes)
    presets: list[str] = []
    value = raw.get("preset_rumore")
    if isinstance(value, list):
        for n, name in enumerate(value, start=1):
            if isinstance(name, str) and name:
                presets.append(name)
            else:
                notes.append(f"{where}: il preset di rumore n. {n} non è leggibile ed è stato ignorato")
    elif value is not None:
        notes.append(f"{where}: «preset_rumore» non è un elenco ed è stato ignorato")
    return profile, rules, presets


def initiative_settings_to_json(profile: Profile, rules: list[NoiseRule], presets: list[str]) -> dict:
    return {"profilo": profile, "regole_rumore": noise_rules_to_json(rules), "preset_rumore": list(presets)}
