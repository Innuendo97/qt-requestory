"""The inputs and comparisons of the phase-2 case comparison
(``officina.service_review``), on top of ``officina.service_compare``.

* :meth:`CaseInputsMixin._input` — one version as the engine takes it: a PDF
  as its words (``_doc``: disk + memory cache); an HTML as its DOM blocks
  (``compare.extract_html``, extracted with every URL key kept, so the cache
  does not depend on the tracking preset), boxed from Edge's print
  (``compare.html_boxes``, a PDFium search for the blocks the print reads in
  another order). An HTML whose print cannot be made (Edge missing or
  failing) is still compared through its DOM: ``print_error`` says why and
  the words keep zero boxes (spec §6: "Senza Edge: confronto DOM normale").
* :meth:`CaseInputsMixin._compare_pairs` — the comparisons of the target
  with each version of a case comparison (the TO-BE, the AS-IS), cached in
  memory by content hashes, rules and tracking flag: re-judging (a profile
  or a tolerance changed) costs nothing. The presets are matched by the
  pipeline; the user's own rules NEVER run in this process (ruling R46): the
  pipeline's pre-noise sides (``compare.sides.prepare``) of every pair go
  to ONE ``noise_guard.match_spans`` child, which matches the rules on the
  exact keys and line ends the noise stage sees, and the spans it found are
  passed to ``compare.pipeline.finish``. A rule that cannot be used on any
  pair — it does not compile, it runs out of time (R22), no child could run
  it (R37) — is dropped from every pair, with a note. The spans are
  remembered per pair, pattern and print state; neither an UNAVAILABLE
  answer (retried) nor spans of a side without a print (R50: they index a
  text without boxes) are remembered.
* :meth:`CaseInputsMixin._guarded_hits` — the noise dialog's counts per
  rule, in the child too, remembered per pattern and texts.
* :func:`noise_side` — the normalised keys and line ends of an input in
  reading order, what the noise dialog counts on (``count_noise_hits``).

Stdlib only at import time; ``officina.pdf`` (pypdfium2) is imported inside
the one method that searches a print.
"""
from __future__ import annotations

import dataclasses
import threading
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass

from qtrequestory.officina.compare import noise, noise_guard, urls
from qtrequestory.officina.compare.extract_html import extract_html
from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.html_boxes import place
from qtrequestory.officina.compare.model import Block, Comparison, Word
from qtrequestory.officina.compare.normalise import line_end, units
from qtrequestory.officina.compare.pipeline import CustomHits, finish
from qtrequestory.officina.compare.sides import Prepared, prepare
from qtrequestory.officina.model import Version
from qtrequestory.officina.model_review import NoiseRule
from qtrequestory.officina.service_compare import CompareError, _case_folder, _label, _read_version, _sha

__all__ = ["CaseInput", "CaseInputsMixin", "noise_side"]

#: In-memory caches: inputs per content hash, comparisons per (hashes, rules), the
#: dialog's counts per (pattern, hashes), a user rule's spans per (pair, pattern).
_INPUT_CACHE_SIZE = 16
_PAIR_CACHE_SIZE = 32
_PROBE_CACHE_SIZE = 256
_SPANS_CACHE_SIZE = 64


@dataclass(frozen=True)
class CaseInput:
    """One version as the engine takes it (see module doc). ``pages`` is the
    page count of the print for an HTML (0 without one); ``pretty`` the DOM
    tab's source ("" for a PDF)."""

    sha: str
    doc: DocText | tuple[Block, ...]
    pretty: str = ""
    pages: int = 0
    print_error: str = ""


class CaseInputsMixin:
    """Needs ``CompareMixin`` (``_doc``, ``_html_as_pdf``) and :meth:`_init_case`."""

    def _init_case(self) -> None:
        self._case_lock = threading.Lock()
        self._inputs: OrderedDict[tuple[str, str], CaseInput] = OrderedDict()
        self._pairs: OrderedDict[tuple, Comparison] = OrderedDict()
        self._probes: OrderedDict[tuple, int | str] = OrderedDict()
        self._spans: OrderedDict[tuple, object] = OrderedDict()

    # ------------------------------------------------------------- inputs ---

    def _input(self, version: Version) -> CaseInput:
        """``version`` as the engine takes it; ``CompareError`` when its file
        cannot be read (gone, a PDF PDFium cannot read)."""
        label = _label(version)
        data = _read_version(version, label)
        sha = _sha(data)
        key = (sha, version.doc_type or "")
        with self._case_lock:
            cached = self._inputs.get(key)
        if cached is not None:
            return cached
        if version.doc_type == "html":
            made = self._html_input(version, data, sha, label)
        else:
            made = CaseInput(sha, self._doc(version, data, sha, label))  # type: ignore[attr-defined]
        if made.print_error:
            return made  # not remembered: the print is tried again next time (Edge installed meanwhile)
        with self._case_lock:
            self._inputs[key] = made
            while len(self._inputs) > _INPUT_CACHE_SIZE:
                self._inputs.popitem(last=False)
        return made

    def _html_input(self, version: Version, data: bytes, sha: str, label: str) -> CaseInput:
        blocks, pretty = extract_html(data)
        try:
            printed = self._doc(version, data, sha, label)  # type: ignore[attr-defined]
        except CompareError as exc:
            return CaseInput(sha, tuple(blocks), pretty, 0, str(exc))
        search = _LazySearch(self, version, data, sha, label)
        try:
            placed = place(blocks, printed, search)
        finally:
            search.close()
        return CaseInput(sha, tuple(placed), pretty, len(printed.page_sizes))

    def _pretty(self, version: Version) -> str:
        """The DOM tab's source of an HTML version (no print needed)."""
        label = _label(version)
        data = _read_version(version, label)
        with self._case_lock:
            cached = self._inputs.get((_sha(data), "html"))
        return cached.pretty if cached is not None else extract_html(data)[1]

    # -------------------------------------------------------- comparisons ---

    def _compare_pairs(self, target: CaseInput, others: Sequence[tuple[str, CaseInput]],
                       presets: Sequence[NoiseRule], custom: Sequence[NoiseRule],
                       tracking: bool) -> tuple[list[Comparison], dict[str, str]]:
        """The comparison of ``target`` with each ``(label, input)`` of
        ``others`` (cached), and ``{name: why}`` of the ``custom`` rules
        dropped from all of them (see module doc). Without notes: see
        :meth:`_noted`."""
        found: dict[str, dict[str, object]] = {label: {} for label, _ in others}
        prepared: dict[str, Prepared] = {}

        def key(other: CaseInput, label: str, rule: NoiseRule) -> tuple:
            # the spans index the pre-noise text, which depends on the words'
            # boxes: a side without a print is another text (re-review N1)
            return (target.sha, other.sha, label, rule.pattern, bool(target.print_error), bool(other.print_error))

        for label, other in others:
            for rule in custom:
                with self._case_lock:
                    known = self._spans.get(key(other, label, rule))
                if known is not None:
                    found[label][rule.name] = known
        todo = [(label, other) for label, other in others if len(found[label]) < len(custom)]
        if todo:
            sides = []
            for label, other in todo:
                prepared[label] = prepare(target.doc, other.doc, right_label=label)
                sides += prepared[label].noise_sides()
            got = noise_guard.match_spans(sides, custom)
            for n, (label, other) in enumerate(todo):
                for rule in custom:
                    value = got[rule.name]
                    answer = value if isinstance(value, str) else (value[2 * n], value[2 * n + 1])
                    found[label][rule.name] = answer
                    # like the pair: nothing made without a print is served again (R50)
                    if value != noise_guard.UNAVAILABLE and not (target.print_error or other.print_error):
                        with self._case_lock:
                            self._spans[key(other, label, rule)] = answer
                            while len(self._spans) > _SPANS_CACHE_SIZE:
                                self._spans.popitem(last=False)
        dropped: dict[str, str] = {}
        for per in found.values():
            for name, answer in per.items():
                if isinstance(answer, str):
                    dropped.setdefault(name, answer)
        applied = [r for r in custom if r.name not in dropped]
        out = []
        for label, other in others:
            hits: list[CustomHits] = [(r.name, *found[label][r.name]) for r in applied]  # type: ignore[misc]
            out.append(self._finished(target, other, label, prepared.get(label), presets, applied, hits, tracking))
        return out, dropped

    def _finished(self, target: CaseInput, other: CaseInput, label: str, prepared: Prepared | None,
                  presets: Sequence[NoiseRule], applied: Sequence[NoiseRule], hits: list[CustomHits],
                  tracking: bool) -> Comparison:
        key = (target.sha, other.sha, label, tuple((r.name, r.pattern) for r in (*presets, *applied)), tracking)
        with self._case_lock:
            cached = self._pairs.get(key)
        if cached is not None:
            return cached
        if prepared is None:
            prepared = prepare(target.doc, other.doc, right_label=label)
        made = finish(prepared, rules=presets, custom_hits=hits,
                      link_drop=urls.tracking_drop if tracking else urls.keep_all)
        if isinstance(target.doc, tuple) and isinstance(other.doc, tuple):
            made = dataclasses.replace(made, left_pages=target.pages or made.left_pages,
                                       right_pages=other.pages or made.right_pages)
        if not (target.print_error or other.print_error):
            # a comparison made without a print (no boxes) is never served
            # again: the next call retries the print (and says why meanwhile)
            with self._case_lock:
                self._pairs[key] = made
                while len(self._pairs) > _PAIR_CACHE_SIZE:
                    self._pairs.popitem(last=False)
        return made

    @staticmethod
    def _noted(comparison: Comparison, target: CaseInput, other: CaseInput, notes: Sequence[str]) -> Comparison:
        """``comparison`` with the print problems and ``notes`` added to its note."""
        extra = [f"stampa dell'HTML non disponibile, differenze senza posizione nel visore ({side.print_error})"
                 for side in (target, other) if side.print_error]
        extra += list(notes)
        if not extra:
            return comparison
        return dataclasses.replace(comparison, note="; ".join(n for n in (comparison.note, *extra) if n))

    def _guarded_hits(self, rules: Sequence[NoiseRule], inputs: Sequence[CaseInput]) -> dict[str, int | str]:
        """``noise_guard.count_hits`` of the user's ``rules`` over ``inputs``,
        remembered per (pattern, input hashes): the noise dialog's repeated
        counts and every re-judge of the same texts start no child. An
        :data:`~noise_guard.UNAVAILABLE` answer is not remembered (retried)."""
        shas = tuple(i.sha for i in inputs)
        out: dict[str, int | str] = {}
        todo: list[NoiseRule] = []
        for rule in rules:
            with self._case_lock:
                known = self._probes.get((rule.pattern, shas))
            if known is None:
                todo.append(rule)
            else:
                out[rule.name] = known
        if todo:
            hits = noise_guard.count_hits([noise_side(i) for i in inputs], todo)
            for rule in todo:
                out[rule.name] = hits[rule.name]
                if hits[rule.name] == noise_guard.UNAVAILABLE:
                    continue
                with self._case_lock:
                    self._probes[(rule.pattern, shas)] = hits[rule.name]
                    while len(self._probes) > _PROBE_CACHE_SIZE:
                        self._probes.popitem(last=False)
        return out


class _LazySearch:
    """``extract_html.locate``'s search over the Edge print, opened on first
    use (most emails never need it) and closed when done."""

    def __init__(self, owner, version: Version, data: bytes, sha: str, label: str) -> None:
        self._owner, self._version, self._data, self._sha, self._label = owner, version, data, sha, label
        self._search = None
        self._failed = False

    def __call__(self, text: str) -> list[tuple[int, tuple[float, float, float, float]]]:
        if self._search is None and not self._failed:
            from qtrequestory.officina import pdf  # lazy: loads pypdfium2

            try:
                path = self._owner._html_as_pdf(_case_folder(self._version) / "cache", self._data, self._sha,
                                                self._label)
                self._search = pdf.TextSearch(path)
            except (CompareError, ValueError, OSError):
                self._failed = True
        return self._search(text) if self._search is not None else []

    def close(self) -> None:
        if self._search is not None:
            self._search.close()
            self._search = None


def noise_side(item: CaseInput) -> noise_guard.Side:
    """``(keys, line ends)`` of an input: its normalised units and the keys
    a line (or an HTML block) ends after."""
    if isinstance(item.doc, DocText):
        words: list[Word] = list(item.doc.words) if item.doc.has_text else []
        keys, members = units(words)
        ends = [k for k in range(len(keys) - 1)
                if members[k] and members[k + 1] and line_end(members[k][-1], members[k + 1][0])]
        return keys, ends
    keys, ends = [], []
    for block in item.doc:
        block_keys, _ = units(block.words)
        keys += block_keys
        if keys:
            ends.append(len(keys) - 1)
    return keys, sorted(set(ends))
