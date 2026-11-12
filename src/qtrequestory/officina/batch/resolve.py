"""From what the user asked (keys, packages, FDIs) to the calls to make
(spec "Sorgente delle chiamate", "Template key scritte a mano").

- A template key → the newest call of that key in the logs of ``source_env``
  (exact match, case-insensitive: the index column is NOCASE). The call keeps
  the spelling of the logs, which becomes the ``template_key`` header.
- A whole FDI → among its calls, the newest one per template key; the folder
  is the FDI. Only that exact FDI counts: a test pratica ``<fdi>-t15`` shares
  the prefix but is another FDI.
- An FDI narrowed to some keys (``Target.keys``, the retry of an FDI's rows)
  → for each of those keys, the newest call OF THAT FDI (never the newest
  call of the key in another FDI), in the order of ``keys``; a key the FDI
  has no call for is a call without a hit.
- One exact call (``Target.kind == "call"``, Ricerca's "Genera documento")
  → that very call, as logged: nothing is looked up (``source_env`` plays no
  part), never the newest call of its key. The folder is its FDI, or
  ``NO_PACKAGE`` for a call without one. A call logged with an empty
  template key is not sent: like an empty key on the key path it ends as
  "nessuna chiamata" (``Call.sendable``), and its row keeps the call.
- Fallback (keys only, never an FDI or an exact call). The payload of the
  newest call can be refused by the generator for reasons that have nothing
  to do with the template (svil missing the price list a coll payload names:
  "Spooling on IPS has failed"), and a key may have no call at all in
  ``source_env`` while another environment has one. So a key's call carries
  ``alternates``: older calls of ``source_env``, then calls of every
  ``fallback_envs`` environment, at most :data:`MAX_PER_ENV` per environment
  and :data:`MAX_CANDIDATES` in all. Within an environment the calls are
  SPREAD back in time (:func:`_spread`: at least 1, 3, 7, 15, 31… days older
  than its newest call), because what breaks a payload (a price list, an
  offer version) lasts weeks: the next day's call would be refused the same
  way. A key with no call in ``source_env`` takes the first fallback call as
  its call.
- Nothing found anywhere → a call without a hit ("nessuna chiamata nei log").

A key that sits in several packages is ONE call written to several folders.

``index`` is duck-typed: anything with ``search(SearchQuery) -> list[SearchHit]``
ordered newest first (``IndexService`` in the app, a real or fake index in
tests). Stdlib + core only, Qt-free.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from typing import Protocol

from qtrequestory.core.events import CancelToken
from qtrequestory.core.index.search import SearchHit, SearchQuery
from qtrequestory.officina.batch.elenco import NO_PACKAGE, Elenco
from qtrequestory.officina.batch.model import Call, Target

#: How many calls of one FDI are looked at (a pratica has a handful).
FDI_LIMIT = 1000
#: Most logged calls one key may try (its call plus the alternates), and most
#: of them from one environment: a long history in ``source_env`` must not
#: crowd out the other environments.
MAX_CANDIDATES = 16
MAX_PER_ENV = 8
#: How many calls of one key are read from the index per environment to pick
#: the alternates from (newest first; one per day is kept).
KEY_LOOKUP_LIMIT = 2000

_SEPARATORS = re.compile(r"[\s,;]+")


class CallIndex(Protocol):
    def search(self, query: SearchQuery) -> list[SearchHit]: ...


def parse_keys(text: str) -> list[str]:
    """Keys typed by hand: separated by spaces, commas, semicolons or line
    breaks (tabs too, for a column pasted from a spreadsheet); duplicates
    (case-insensitive) dropped, first spelling and order kept."""
    return _unique(_SEPARATORS.split(text or ""))


def targets_from_keys(keys: Sequence[str], elenco: Elenco | None) -> tuple[Target, ...]:
    """One target per distinct key; its folders are its packages in ``elenco``,
    or ``NO_PACKAGE`` when there is no list or the key is not in it."""
    targets: list[Target] = []
    for key in _unique(keys):
        folders = elenco.packages_of(key) if elenco is not None else ()
        targets.append(Target("key", key, folders or (NO_PACKAGE,)))
    return tuple(targets)


def targets_from_packages(elenco: Elenco, packages: Collection[str]) -> tuple[Target, ...]:
    """The keys of the chosen ``packages`` in file order; a key's folders are
    the chosen packages that hold it (an unchosen package gets no copy)."""
    chosen = set(packages)
    targets: list[Target] = []
    for key in elenco.keys_of(chosen):
        folders = tuple(p for p in elenco.packages_of(key) if p in chosen)
        targets.append(Target("key", key, folders or (NO_PACKAGE,)))
    return tuple(targets)


def targets_from_fdis(fdis: Sequence[str]) -> tuple[Target, ...]:
    """One target per distinct FDI (stripped, case-insensitive)."""
    return tuple(Target("fdi", fdi, ()) for fdi in _unique(fdis))


def targets_from_hits(hits: Sequence[SearchHit]) -> tuple[Target, ...]:
    """One exact ``"call"`` target per distinct call in ``hits`` (the same
    call twice is sent once), in order; its folder is the call's FDI, or
    ``NO_PACKAGE``."""
    targets: list[Target] = []
    seen: set[SearchHit] = set()
    for hit in hits:
        if hit in seen:
            continue
        seen.add(hit)
        targets.append(Target("call", hit.template_key, (hit.fdi or NO_PACKAGE,), hit=hit))
    return tuple(targets)


def resolve(
    targets: Sequence[Target],
    *,
    index: CallIndex,
    source_env: str,
    cancel: CancelToken | None = None,
    fallback_envs: Sequence[str] = (),
) -> list[Call]:
    """The calls of ``targets``, in target order (an FDI's calls newest
    first). ``cancel.check()`` runs before every target, so this raises
    :class:`~qtrequestory.core.events.Cancelled` between two lookups.
    ``fallback_envs``: see the module docstring (keys only)."""
    others = tuple(e for e in _unique(fallback_envs) if e.casefold() != source_env.casefold())
    calls: list[Call] = []
    for target in targets:
        if cancel is not None:
            cancel.check()
        value = target.value.strip()
        if target.kind == "key":
            calls.append(_key_call(value, target.folders, index, source_env, others))
        elif target.kind == "fdi":
            calls.extend(_fdi_calls(value, index, source_env, target.keys))
        elif target.kind == "call":
            calls.append(exact_call(target))
        else:
            raise ValueError(f"unknown target kind {target.kind!r}")
    return calls


def exact_call(target: Target) -> Call:
    """The call of an exact ``"call"`` target; ``ValueError`` without its hit."""
    hit = target.hit
    if hit is None:
        raise ValueError("una chiamata esatta senza la sua chiamata nei log")
    folders = target.folders or (hit.fdi or NO_PACKAGE,)
    key = hit.template_key if hit.template_key.strip() else ""  # no key: not sendable (Call.sendable)
    return Call(key=key, folders=folders, fdi=hit.fdi, hit=hit, exact=True)


def _key_call(key: str, folders: tuple[str, ...], index: CallIndex, env: str,
              fallback_envs: Sequence[str] = ()) -> Call:
    if not key:
        return Call(key="", folders=folders, fdi=None, hit=None)
    candidates: list[SearchHit] = []
    for e in (env, *fallback_envs):
        if len(candidates) >= MAX_CANDIDATES:
            break
        hits = index.search(SearchQuery(e, template_key=key, key_mode="exact", limit=KEY_LOOKUP_LIMIT))
        candidates.extend(_spread(hits, MAX_PER_ENV))
    candidates = candidates[:MAX_CANDIDATES]
    if not candidates:
        return Call(key=key, folders=folders, fdi=None, hit=None)
    hit = candidates[0]
    return Call(key=hit.template_key, folders=folders, fdi=hit.fdi, hit=hit,
                alternates=tuple(candidates[1:]))


def _spread(hits: Sequence[SearchHit], most: int) -> list[SearchHit]:
    """At most ``most`` of ``hits`` (newest day first), spread back in time:
    the newest, then the first one at least 1 day older, then at least 3,
    7, 15… days older than the newest (``2**n - 1``)."""
    kept: list[SearchHit] = []
    for hit in hits:
        if len(kept) >= most:
            break
        if not kept or (kept[0].day - hit.day).days >= 2 ** len(kept) - 1:
            kept.append(hit)
    return kept


def _fdi_calls(fdi: str, index: CallIndex, env: str, keys: Sequence[str] = ()) -> list[Call]:
    folders = (fdi,)
    only = {key.casefold(): key for key in _unique(keys)}  # () = every key of the FDI
    found: dict[str, Call] = {}
    if fdi:
        wanted = fdi.casefold()
        for hit in index.search(SearchQuery(env, fdi_prefix=fdi, limit=FDI_LIMIT)):
            folded = hit.template_key.strip().casefold()
            if (hit.fdi or "").casefold() != wanted or not folded or folded in found:
                continue
            if only and folded not in only:
                continue
            found[folded] = Call(key=hit.template_key, folders=folders, fdi=fdi, hit=hit)
    if only:
        return [found.get(folded) or Call(key=key, folders=folders, fdi=fdi, hit=None)
                for folded, key in only.items()]
    return list(found.values()) or [Call(key="", folders=folders, fdi=fdi, hit=None)]


def _unique(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        folded = value.casefold()
        if value and folded not in seen:
            seen.add(folded)
            result.append(value)
    return result
