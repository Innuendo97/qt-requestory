"""The Officina half of the in-memory core (``FakeOfficinaApi``), split out of
``fake_core.py`` (which re-exports everything here, so ``from
tests.fakes.fake_core import FakeOfficinaApi, canned_pdf, fake_diff`` keeps working).

No Qt, no network, no engine import: see ``FakeOfficinaApi`` for the knobs and
``tests/fakes/fake_verdict.py`` for the scripted verdict rules.
"""
from __future__ import annotations

import dataclasses
import io
import json
import re
import time
import urllib.error
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from qtrequestory.core.config import Config, GeneratorEndpoint
from qtrequestory.ui.contracts import (
    Case,
    CaseComparison,
    CompareError,
    Comparison,
    Diff,
    Initiative,
    Judged,
    Mark,
    NoiseRule,
    Profile,
    Review,
    SendResult,
    Tolerance,
    Version,
)

from tests.fakes.fake_verdict import FAKE_PRESETS, fake_comparison, fake_diff, fake_inactive, fake_judge, norm

if TYPE_CHECKING:
    from qtrequestory.core.index.search import SearchHit

    from tests.fakes.fake_core import FakeIndexApi

__all__ = ["FAKE_GENERATOR", "FakeOfficinaApi", "FakeRequest", "canned_pdf", "fake_comparison", "fake_diff"]


def canned_pdf(text: str = "MOD_TEST documento generato dal generatore finto") -> bytes:
    """A small (~1.7 KB), valid one-page PDF whose text layer holds ``text`` (one line per
    ``\\n``), built by hand: no Qt and no pypdfium2 needed to make it, and
    PDFium extracts the words back. ``""`` gives a page without any text."""
    def esc(line: str) -> str:
        return line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    ops = ["BT", "/F1 12 Tf", "14 TL", "56 780 Td"]
    ops += [f"({esc(line)}) Tj T*" for line in text.splitlines()]
    ops.append("ET")
    stream = "\n".join(ops).encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
    ]
    # a comment line pads it past edge.MIN_PDF_BYTES, the size a real print must exceed
    out = bytearray(b"%PDF-1.4\n%" + b"0" * 1100 + b"\n")
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


# ----------------------------------------------------------------- officina ---

#: The generator the fake configuration offers (never contacted: the fake
#: answers in-process). The fake Officina root is ``<root>/officina``.
FAKE_GENERATOR = GeneratorEndpoint("svil", "https://example.invalid/svil/rest/api/submit-job/documentGenerator")


@dataclasses.dataclass(frozen=True)
class FakeRequest:
    """One call the fake generator received (kept in memory only)."""

    url: str
    headers: dict[str, str]
    payload: dict

    @property
    def template_key(self) -> str:
        """The ``template_key`` header (urllib spells it ``Template_key``)."""
        return next((v for k, v in self.headers.items() if k.lower() == "template_key"), "")


class _CannedResponse(io.BytesIO):
    """Enough of ``http.client.HTTPResponse`` for ``generator.send``."""

    def __init__(self, status: int, body: bytes) -> None:
        super().__init__(body)
        self.status = status
        self.headers: dict[str, str] = {}

    def getcode(self) -> int:
        return self.status


class FakeOfficinaApi:
    """The REAL ``OfficinaService`` on real files under the fake's root, with
    only the two outside worlds replaced: the HTTP generator answers
    in-process (a canned PDF by default; no socket is ever opened) and
    Edge's HTML->PDF print is a canned PDF of the HTML's visible text.

    Everything the UI can observe — refusals and their reasons, version
    numbering, the files on disk, the type check, the caches, the
    ``CompareError`` cases — is therefore the shipped behaviour, not a copy
    of it (``tests/test_fake_core.py`` pins this against a real HTTP server).
    ``compare`` can be scripted with ``set_comparison``/``set_compare_error``
    for UI tests that need a particular set of differences.

    **Phase 2 — the case comparison is SCRIPTED** (the real one is a stub
    until the engine lands). ``compare_case`` returns what you canned, judged
    by an in-fake verdict function that follows spec §5.1–5.3
    (``tests/fakes/fake_verdict.py``, rules in its docstring)::

        from tests.fakes.fake_core import fake_diff
        api.set_canned(case.id, 0, [fake_diff("cambiato", "testo", "12,00", "11,00")])  # 0 = AS-IS
        api.set_canned(case.id, 1, [fake_diff("cambiato", "testo", "12,00", "11,50"),   # TO-BE v1
                                    fake_diff("mancante", "stile", "Titolo", "")],
                       note="nota", left_pages=2)                 # any Comparison field
        cc = api.compare_case(ini, case, v1)   # in_corso + tollerata (profile tollerante)

    * ``canned[case_id][n]`` (``set_canned`` or direct assignment) holds a
      ``list[Diff]`` or a ready ``Comparison`` for TO-BE ``n``; ``0`` is the
      AS-IS↔target comparison. No entry 0 → two-way verdict; no entry for the
      version → no differences. The target must exist (else ``CompareError``,
      as in the real service); ``set_compare_error`` applies too.
    * ``fake_diff(op, klass, target_text, generated, context=..., detail=...)``
      builds a ``Diff`` whose anchor is ``(op, klass, context, target_text)``:
      reuse the same target text (and context) across versions for "the same"
      difference; change ``generated`` for "in corso"; drop it from a newer
      version for "fatta" / a resolved mark; keep it identical for "non risolta".
    * Marks, tolerances, not-variables, profile and noise rules are REAL state:
      the actions save with the real model (``Workspace.save_review``: only
      the review keys of ``caso.json``; ``save_initiative_settings`` for
      ``iniziativa.json``) and only THEN update ``case.review`` / ``ini``, so
      a refused save (unreadable file → ``ValueError``) changes nothing and a
      reload sees what was saved. ``compare_case`` saves the summary,
      verifies each mark older than the compared version (R7), remembers
      "non risolta" with the mark's own version (R10) and numbers
      ``judged`` ids 1..n (R9). Duplicate noise-rule names → ``ValueError``.
    * Shortcuts (not the engine): noise rules do not change the canned diffs
      (can ``rumore`` diffs and ``noise_hits`` instead); the other verdict
      shortcuts are listed in ``fake_verdict``'s docstring.
    * ``set_noise_text(case_id, text)`` is what ``count_noise_hits`` counts
      over (default: the canned texts of the case); ``set_dom_view(case_id,
      (target, version))`` scripts ``dom_view`` (default: the two HTML
      sources, ``("", "")`` for a PDF case). ``review_actions`` records every
      action as ``(method name, case id or None)``; ``compare_case_calls``
      records ``(case id, version number)``.
    """

    def __init__(self, root: Path, config_source: Callable[[], Config], index: FakeIndexApi | None = None) -> None:
        from qtrequestory.officina.service import OfficinaService

        self._root = Path(root)
        self.response: tuple[int, bytes] = (200, canned_pdf())
        #: template_key -> (status, body): overrides ``response`` for that key.
        self.responses_for: dict[str, tuple[int, bytes]] = {}
        #: Decides every answer when set (see ``set_responder``).
        self.responder: Callable[[FakeRequest], tuple[int, bytes]] | None = None
        self.network_error: str | None = None
        #: Seconds the fake generator "takes" (a UI test of a busy state).
        self.delay_s = 0.0
        self.requests: list[FakeRequest] = []
        self.compare_calls: list[tuple[Version, Version]] = []
        self.conversions: list[tuple[Path, Path]] = []
        self.scripted_comparison: Comparison | None = None
        self.compare_error: str | None = None
        #: What the HTML print answers instead of a PDF (e.g. "Edge non trovato"), or None.
        self.print_error: str | None = None
        #: case id -> version number (0 = AS-IS) -> list[Diff] | Comparison.
        self.canned: defaultdict[str, dict[int, list[Diff] | Comparison]] = defaultdict(dict)
        self.noise_texts: dict[str, str] = {}
        self.dom_views: dict[str, tuple[str, str]] = {}
        self.review_actions: list[tuple[str, str | None]] = []
        self.compare_case_calls: list[tuple[str, int]] = []
        self._service = OfficinaService(config_source, index=index, opener=self._open,
                                        html_to_pdf=self._html_to_pdf)

    # -- knobs -------------------------------------------------------------

    def set_response(self, body: bytes | None = None, status: int = 200) -> None:
        """What the generator answers from now on (``None``: the canned PDF)."""
        self.response = (status, canned_pdf() if body is None else body)
        self.network_error = None

    def set_response_for(self, template_key: str, body: bytes | None, status: int = 200) -> None:
        """What the generator answers for ONE template key (e.g. fail only
        case 2 of a batch); ``body=None`` removes the override."""
        if body is None:
            self.responses_for.pop(template_key, None)
        else:
            self.responses_for[template_key] = (status, body)

    def set_responder(self, responder: Callable[[FakeRequest], tuple[int, bytes]] | None) -> None:
        """``responder(request) -> (status, body)`` decides every answer until
        ``None``; it may raise ``urllib.error.URLError`` (a network error) or
        ``TimeoutError`` (a timeout), exactly as the real opener would."""
        self.responder = responder

    def set_network_error(self, reason: str | None) -> None:
        """Every call fails as "errore di rete: <reason>" until ``None``."""
        self.network_error = reason

    def set_comparison(self, result: Comparison | None) -> None:
        """Every ``compare`` returns ``result`` until ``None`` (real engine)."""
        self.scripted_comparison = result

    def set_print_error(self, message: str | None) -> None:
        """Every HTML print fails with ``message`` (Edge missing) until ``None``."""
        self.print_error = message

    def set_compare_error(self, message: str | None) -> None:
        """Every ``compare`` raises ``CompareError(message)`` until ``None``."""
        self.compare_error = message

    def set_canned(self, case_id: str, version: int, diffs: list[Diff] | Comparison | None, **fields) -> None:
        """What ``compare_case`` finds for TO-BE ``version`` of ``case_id``
        (``0``: AS-IS↔target); ``fields`` override ``Comparison`` fields
        (``note``, ``left_pages``, ``noise_hits``...); ``None`` removes it."""
        if diffs is None:
            self.canned[case_id].pop(version, None)
        else:
            self.canned[case_id][version] = fake_comparison(diffs, **fields)

    def set_noise_text(self, case_id: str, text: str | None) -> None:
        """The text ``count_noise_hits`` counts over for ``case_id`` (None: default)."""
        if text is None:
            self.noise_texts.pop(case_id, None)
        else:
            self.noise_texts[case_id] = text

    def set_dom_view(self, case_id: str, sources: tuple[str, str] | None) -> None:
        """What ``dom_view`` returns for ``case_id`` (None: default)."""
        if sources is None:
            self.dom_views.pop(case_id, None)
        else:
            self.dom_views[case_id] = sources

    # -- the two replaced outside worlds -------------------------------------

    def _open(self, request, timeout: float = 0):  # noqa: ANN001 - urllib.request.Request
        received = FakeRequest(request.full_url, dict(request.header_items()),
                               json.loads(request.data.decode("utf-8")))
        self.requests.append(received)  # list.append is atomic: batches run in threads
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.responder is not None:
            return _CannedResponse(*self.responder(received))
        if self.network_error is not None:
            raise urllib.error.URLError(self.network_error)
        status, body = self.responses_for.get(received.template_key, self.response)
        return _CannedResponse(status, body)

    def _html_to_pdf(self, html_path: Path, out_pdf: Path, *, timeout_s: int = 60, edge: Path | None = None) -> str | None:
        """Like ``edge.html_to_pdf``: a sanitised copy next to ``out_pdf``, then
        the PDF — here a canned one holding the HTML's visible text."""
        if self.print_error is not None:
            return self.print_error
        raw = Path(html_path).read_bytes()
        self.conversions.append((Path(html_path), Path(out_pdf)))
        out_pdf.with_name(out_pdf.stem + ".sanitised.html").write_bytes(raw)
        text = re.sub(r"(?is)<(style|script)\b.*?</\1>|<[^>]+>", " ", raw.decode("utf-8", "replace"))
        Path(out_pdf).write_bytes(canned_pdf(" ".join(text.split())))
        return None

    # -- contract ------------------------------------------------------------

    def workspace_root(self) -> Path | None:
        return self._service.workspace_root()

    def initiatives(self) -> list[Initiative]:
        return self._service.initiatives()

    def create_initiative(self, name: str) -> Initiative:
        return self._service.create_initiative(name)

    def load(self, initiative_id: str) -> Initiative:
        return self._service.load(initiative_id)

    def case_from_hit(self, ini: Initiative, hit: SearchHit, variant: str = "") -> Case:
        return self._service.case_from_hit(ini, hit, variant)

    def case_from_file(self, ini: Initiative, path: Path, key: str, variant: str = "") -> Case:
        return self._service.case_from_file(ini, path, key, variant)

    def save_case(self, case: Case) -> None:
        self._service.save_case(case)

    def payload(self, case: Case) -> dict:
        return self._service.payload(case)

    def save_payload(self, case: Case, payload: dict) -> None:
        self._service.save_payload(case, payload)

    def set_target(self, case: Case, src: Path) -> Version:
        return self._service.set_target(case, src)

    def generate(self, ini: Initiative, case: Case, kind, *, replace_asis_note: str | None = None,
                 cancel=None) -> tuple[Version | None, SendResult]:
        return self._service.generate(ini, case, kind, replace_asis_note=replace_asis_note, cancel=cancel)

    def compare(self, left: Version, right: Version) -> Comparison:
        self.compare_calls.append((left, right))
        if self.compare_error is not None:
            raise CompareError(self.compare_error)
        if self.scripted_comparison is not None:
            return self.scripted_comparison
        return self._service.compare(left, right)

    def render_path(self, case: Case, version: Version) -> Path:
        return self._service.render_path(case, version)

    def delivery_plan(self, ini: Initiative, case_ids):
        return self._service.delivery_plan(ini, case_ids)

    def delivery_conflicts(self, ini: Initiative, items, destination: Path, *, make_zip: bool) -> list[Path]:
        return self._service.delivery_conflicts(ini, items, destination, make_zip=make_zip)

    def deliver(self, ini: Initiative, items, destination: Path, *, on_conflict, make_zip: bool, cancel=None):
        return self._service.deliver(ini, items, destination, on_conflict=on_conflict, make_zip=make_zip,
                                     cancel=cancel)

    def last_delivery_destination(self, ini: Initiative) -> Path | None:
        return self._service.last_delivery_destination(ini)

    # -- phase 2: scripted case comparison, real review state ----------------

    def compare_case(self, ini: Initiative, case: Case, version: Version) -> CaseComparison:
        self.compare_case_calls.append((case.id, version.number))
        if self.compare_error is not None:
            raise CompareError(self.compare_error)
        if case.target() is None:
            raise CompareError("manca il target del caso: caricarlo prima di confrontare")
        canned = self.canned.get(case.id, {})
        tobe = fake_comparison(canned.get(version.number, []))
        asis = fake_comparison(canned[0]) if 0 in canned else None
        profile: Profile = case.review.profile or ini.profile or "tollerante"
        judged, summary, verification, review = fake_judge(
            tobe, asis, case.review, profile, version.number, self._now())
        latest = case.latest_tobe()
        if not (tobe.left_has_text and tobe.right_has_text):
            pass  # R49: nothing judged, nothing saved
        elif latest is None or version.number >= latest.number:
            self._commit_review(None, case, review)
        else:  # R48: an older version keeps the latest's summary and flags, adds what it found
            found = [e for e in review.unresolved if e not in case.review.unresolved]
            again = {e[0] for e in found}
            self._commit_review(None, case, dataclasses.replace(
                review, summary=case.review.summary,
                unresolved=[e for e in case.review.unresolved if e[0] not in again] + found))
        return CaseComparison(version.number, judged, summary, tobe, asis, verification, profile,
                              fake_inactive(review, judged))

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _workspace(self):
        from qtrequestory.officina.model import Workspace

        root = self._service.workspace_root()
        if root is None:
            raise ValueError("cartella dell'Officina non impostata: sceglierla in Impostazioni")
        return Workspace(root)

    def _commit_review(self, action: str | None, case: Case, review: Review) -> None:
        """Save ``review`` with ``save_review`` (only the review keys, R8), THEN
        put it on ``case``: a refused save leaves the object unchanged."""
        self._workspace().save_review(dataclasses.replace(case, review=review))
        case.review = review
        if action is not None:
            self.review_actions.append((action, case.id))

    def _update_review(self, action: str, case: Case, **changes) -> None:
        self._commit_review(action, case, dataclasses.replace(case.review, **changes))

    def _commit_initiative(self, action: str, ini: Initiative, **changes) -> None:
        """Same rule for ``iniziativa.json``: save a copy, then update ``ini``."""
        updated = dataclasses.replace(ini, **changes)
        self._workspace().save_initiative_settings(updated)
        for name, value in changes.items():
            setattr(ini, name, value)
        self.review_actions.append((action, None))

    def tolerate(self, case: Case, judged: Judged, note: str = "") -> None:
        anchor = judged.diff.anchor
        kept = [t for t in case.review.tolerances if t.anchor != anchor]
        self._update_review("tolerate", case, tolerances=[
            *kept, Tolerance(anchor, norm(judged.diff.right_text), note, self._now())])

    def untolerate(self, case: Case, judged: Judged) -> None:
        self._update_review("untolerate", case, tolerances=[
            t for t in case.review.tolerances if t.anchor != judged.diff.anchor])

    def mark_done(self, case: Case, judged: Judged, version: int) -> None:
        anchor = judged.diff.anchor
        kept = [m for m in case.review.marks if m.anchor != anchor]
        self._update_review("mark_done", case, marks=[
            *kept, Mark(anchor, norm(judged.diff.right_text), version, self._now())])

    def unmark(self, case: Case, judged: Judged) -> None:
        self._update_review("unmark", case, marks=[m for m in case.review.marks if m.anchor != judged.diff.anchor])

    def unmark_all(self, case: Case) -> None:
        self._update_review("unmark_all", case, marks=[])

    def not_variable(self, case: Case, judged: Judged) -> None:
        anchor = judged.diff.anchor
        current = list(case.review.not_variables)
        if all(a != anchor for a, _ in current):
            current.append((anchor, self._now()))
        self._update_review("not_variable", case, not_variables=current)

    def variable_again(self, case: Case, judged: Judged) -> None:
        self._update_review("variable_again", case, not_variables=[
            (a, w) for a, w in case.review.not_variables if a != judged.diff.anchor])

    def reset_tolerances(self, case: Case) -> None:
        self._update_review("reset_tolerances", case, tolerances=[], not_variables=[])

    def set_profile(self, ini: Initiative, case: Case | None, profile: Profile | None) -> None:
        if case is None:
            self._commit_initiative("set_profile", ini, profile=profile or "tollerante")
        else:
            self._update_review("set_profile", case, profile=profile)

    def set_noise_rules(self, ini: Initiative, case: Case | None, rules: list[NoiseRule],
                        presets: list[str] | None = None) -> None:
        _refuse_duplicate_names(rules)
        taken = {p.name for p in FAKE_PRESETS}
        taken |= ({r.name for r in ini.noise_rules} if case is not None
                  else {r.name for c in ini.cases for r in c.review.noise_rules})
        for rule in rules:
            if rule.name in taken:  # across levels too, like the real service
                raise ValueError(f"regola di rumore «{rule.name}»: nome già usato")
        if case is not None:
            self._update_review("set_noise_rules", case, noise_rules=list(rules))
        elif presets is not None:
            self._commit_initiative("set_noise_rules", ini, noise_rules=list(rules), noise_presets=list(presets))
        else:
            self._commit_initiative("set_noise_rules", ini, noise_rules=list(rules))

    def noise_presets(self) -> list[NoiseRule]:
        return [dataclasses.replace(p) for p in FAKE_PRESETS]

    def count_noise_hits(self, case: Case, rules: list[NoiseRule]) -> dict[str, int | str]:
        text = self.noise_texts.get(case.id)
        if text is None:
            text = " ".join(f"{d.left_text} {d.right_text}" for c in self.canned.get(case.id, {}).values()
                            for d in fake_comparison(c).diffs)
        _refuse_duplicate_names(rules)
        hits: dict[str, int | str] = {}
        for rule in rules:
            try:
                hits[rule.name] = sum(1 for _ in re.finditer(rule.pattern, text))
            except re.error as exc:
                hits[rule.name] = f"espressione non valida: {exc}"
        return hits

    def dom_view(self, case: Case, version: Version) -> tuple[str, str]:
        if case.id in self.dom_views:
            return self.dom_views[case.id]
        target = case.target()
        if target is None or target.doc_type != "html" or version.doc_type != "html":
            return "", ""
        return (target.path.read_text(encoding="utf-8", errors="replace"),
                version.path.read_text(encoding="utf-8", errors="replace"))


def _refuse_duplicate_names(rules: list[NoiseRule]) -> None:
    """Rule names are keys (``count_noise_hits``, one row each in the UI):
    two rules with the same name are refused, never merged."""
    seen: set[str] = set()
    for rule in rules:
        if rule.name in seen:
            raise ValueError(f"due regole di rumore hanno lo stesso nome: «{rule.name}»")
        seen.add(rule.name)
