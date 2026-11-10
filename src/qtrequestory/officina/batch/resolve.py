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
- Nothing found → a call without a hit ("nessuna chiamata nei log"), never a
  fallback to another environment.

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


def resolve(
    targets: Sequence[Target],
    *,
    index: CallIndex,
    source_env: str,
    cancel: CancelToken | None = None,
) -> list[Call]:
    """The calls of ``targets``, in target order (an FDI's calls newest
    first). ``cancel.check()`` runs before every target, so this raises
    :class:`~qtrequestory.core.events.Cancelled` between two lookups."""
    calls: list[Call] = []
    for target in targets:
        if cancel is not None:
            cancel.check()
        value = target.value.strip()
        if target.kind == "key":
            calls.append(_key_call(value, target.folders, index, source_env))
        elif target.kind == "fdi":
            calls.extend(_fdi_calls(value, index, source_env, target.keys))
        else:
            raise ValueError(f"unknown target kind {target.kind!r}")
    return calls


def _key_call(key: str, folders: tuple[str, ...], index: CallIndex, env: str) -> Call:
    if not key:
        return Call(key="", folders=folders, fdi=None, hit=None)
    hits = index.search(SearchQuery(env, template_key=key, key_mode="exact", limit=1))
    if not hits:
        return Call(key=key, folders=folders, fdi=None, hit=None)
    hit = hits[0]
    return Call(key=hit.template_key, folders=folders, fdi=hit.fdi, hit=hit)


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
