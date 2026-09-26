"""The comparison half of ``OfficinaService`` (``officina.service``).

Both sides go through the staged engine (``compare.extract_pdf`` +
``compare.pipeline.compare_docs``, without noise rules, verdicts or a
review: the AS-IS view and "cos'altro ho cambiato"; ``compare_case`` is
``service_review``'s). An HTML side is printed to PDF by Edge first, in the
case's ``cache\\`` folder, never in ``target\\``, ``asis\\`` or ``tobe\\``:

* the bytes that were hashed are copied to a private file in ``cache\\`` and
  THAT copy is printed, to a private temporary name (Edge's sanitised copy
  lands next to it, so two conversions never share a file); the result is
  checked like Edge's own check (``%PDF-``, over ``MIN_PDF_BYTES``) plus a
  ``%%EOF`` near the end, and only then renamed atomically onto
  ``html-<sha256[:32]>.pdf``. The temporary files are removed either way;
* a lock per final name serialises check-and-convert, so two workers asking
  for the same HTML (the board and the case view) convert it once;
* a cached PDF that fails the check (a crash mid-write before this scheme, a
  hand-edit) is converted again, never reused.

Extractions are cached on disk (``compare.cache``:
``<case>\\cache\\extract-<sha256>.json``, best-effort; a missing, corrupt or
older-format file is a miss, silently written again) and, like the results,
in memory, keyed by content hash: comparing the same two contents again
costs reading and hashing two files. A
PDF is extracted from a private copy of the bytes that were hashed (in
``cache\\``, removed afterwards), like an HTML is printed from one: what is
cached under a hash is always the content of that hash, even when the file
is rewritten while the comparison runs.

A comparison that cannot be made (a file gone, a PDF PDFium cannot read, Edge
missing or failing) raises :class:`CompareError` with an Italian message for
the UI to show — it is *not* folded into a ``Comparison`` note, because a
note would be cached and read like a result ("0 differences"), while the
problem is usually fixable (install Edge, restore the file) and must be
retried. A side without a text layer, instead, IS a result: the comparison
says so in its ``note`` and reports no differences (Review Focus 2).

Stdlib only at import time: ``compare.extract_pdf`` loads pypdfium2 inside
``extract()``.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from qtrequestory.core.fsutil import remove_quietly, replace_with_retry
from qtrequestory.officina.compare import cache as extract_cache
from qtrequestory.officina.compare.edge import MIN_PDF_BYTES
from qtrequestory.officina.compare.extract_pdf import DocText, extract
from qtrequestory.officina.compare.model import Comparison
from qtrequestory.officina.compare.pipeline import compare_docs
from qtrequestory.officina.model import Case, Version

__all__ = ["CompareError", "CompareMixin", "EDGE_TIMEOUT_S"]

log = logging.getLogger("qtrequestory.officina.service")

#: How long Edge may take to print one HTML (a fresh profile costs ~3.5 s).
EDGE_TIMEOUT_S = 60
#: In-memory caches: extractions per content hash, results per hash pair.
_DOC_CACHE_SIZE = 16
_RESULT_CACHE_SIZE = 64

_LABELS = {"target": "target", "asis": "AS-IS", "tobe": "TO-BE"}

HtmlToPdf = Callable[..., "str | None"]


class CompareError(ValueError):
    """A comparison could not be made; the message is Italian, for the user."""


class CompareMixin:
    """``compare`` and ``render_path`` of ``OfficinaService``: needs
    :meth:`_init_compare` called from the service's ``__init__``."""

    def _init_compare(self, html_to_pdf: HtmlToPdf) -> None:
        self._html_to_pdf = html_to_pdf
        self._lock = threading.Lock()
        self._path_locks: dict[Path, threading.Lock] = {}  # one per cached HTML->PDF name
        self._docs: OrderedDict[str, DocText] = OrderedDict()
        self._results: OrderedDict[tuple[str, str, str, str], Comparison] = OrderedDict()

    def compare(self, left: Version, right: Version) -> Comparison:
        """Engine comparison of ``left`` (the reference, usually the TARGET) with
        ``right``. Cached by the two contents' SHA-256. :class:`CompareError`
        when it cannot be made (see the module docstring). The returned object
        may be shared with later calls: do not mutate it."""
        left_label, right_label = _label(left), _label(right)
        left_data, right_data = _read_version(left, left_label), _read_version(right, right_label)
        left_sha, right_sha = _sha(left_data), _sha(right_data)
        key = (left_sha, right_sha, left_label, right_label)
        with self._lock:
            cached = self._results.get(key)
            if cached is not None:
                self._results.move_to_end(key)
                return cached
        started = time.monotonic()
        result = compare_docs(self._doc(left, left_data, left_sha, left_label),
                              self._doc(right, right_data, right_sha, right_label),
                              left_label=left_label, right_label=right_label)
        log.info("Officina: confronto %s/%s: %d differenze (%d ms)", left_label, right_label,
                 len(result.diffs), int((time.monotonic() - started) * 1000))
        with self._lock:
            self._results[key] = result
            while len(self._results) > _RESULT_CACHE_SIZE:
                self._results.popitem(last=False)
        return result

    def render_path(self, case: Case, version: Version) -> Path:
        """The PDF the viewer renders for ``version``: the file itself for a
        PDF; for an HTML, its Edge print in ``<case>\\cache\\`` (converted now
        if needed, the same file ``compare`` uses). :class:`CompareError` when
        the file is gone or the conversion fails."""
        label = _label(version)
        if version.broken:
            raise CompareError(f"{label}: {version.broken}")
        if version.doc_type != "html":
            if not version.path.is_file():
                raise CompareError(f"il file {_of(label)}{label} non esiste più: {version.path.name}")
            return version.path
        data = _read_version(version, label)
        return self._html_as_pdf(case.folder / "cache", data, _sha(data), label)

    def _doc(self, version: Version, data: bytes, sha: str, label: str) -> DocText:
        """The words of ``data``, the bytes hashed as ``sha`` (for an HTML: of
        its Edge print). Never of the live file: an HTML is printed from a
        private copy of ``data``, and a PDF is extracted from one (in
        ``<case>\\cache\\``, removed afterwards), so what is cached under
        ``sha`` — in memory and on disk — is always what ``sha`` stands for,
        even if the version's file is rewritten meanwhile."""
        with self._lock:
            cached = self._docs.get(sha)
            if cached is not None:
                self._docs.move_to_end(sha)
                return cached
        folder = _case_folder(version)
        cache = folder / "cache"
        doc = extract_cache.load(folder, sha)
        if doc is not None:
            self._remember(sha, doc)
            return doc
        if version.doc_type == "html":
            doc = self._extract(self._html_as_pdf(cache, data, sha, label), label)
        else:
            copy = cache / f"extract-{sha[:32]}.{uuid.uuid4().hex[:12]}.pdf"
            try:
                cache.mkdir(parents=True, exist_ok=True)
                copy.write_bytes(data)
            except OSError as exc:
                remove_quietly(copy)
                raise CompareError(f"impossibile preparare il {label} per il confronto: {exc}") from None
            try:
                doc = self._extract(copy, label)
            finally:
                remove_quietly(copy)
        extract_cache.store(folder, sha, doc.words, doc.page_sizes, doc.has_text)
        self._remember(sha, doc)
        return doc

    def _remember(self, sha: str, doc: DocText) -> None:
        with self._lock:
            self._docs[sha] = doc
            self._docs.move_to_end(sha)
            while len(self._docs) > _DOC_CACHE_SIZE:
                self._docs.popitem(last=False)

    @staticmethod
    def _extract(pdf_path: Path, label: str) -> DocText:
        try:
            return extract(pdf_path)
        except (ValueError, OSError) as exc:  # PdfReadError is a ValueError
            raise CompareError(f"{label}: {exc}") from None

    def _path_lock(self, path: Path) -> threading.Lock:
        with self._lock:
            return self._path_locks.setdefault(path, threading.Lock())

    def _html_as_pdf(self, cache: Path, data: bytes, sha: str, label: str) -> Path:
        """The Edge print of the HTML ``data`` (hashed as ``sha``) in ``cache``:
        converted once per name under a lock, through private temporary files,
        and renamed into place only when complete (module docstring)."""
        final = cache / f"html-{sha[:32]}.pdf"
        with self._path_lock(final):
            if not _pdf_problem(final):
                return final
            try:
                cache.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise CompareError(f"impossibile creare la cartella cache del caso: {exc}") from None
            token = uuid.uuid4().hex[:12]
            src = cache / f"html-{sha[:32]}.{token}.src.html"
            tmp = cache / f"html-{sha[:32]}.{token}.pdf"
            try:
                try:
                    src.write_bytes(data)
                except OSError as exc:
                    raise CompareError(f"impossibile preparare l'HTML da convertire: {exc}") from None
                error = self._html_to_pdf(src, tmp, timeout_s=EDGE_TIMEOUT_S) or _pdf_problem(tmp)
                if error:
                    raise CompareError(f"{label}: conversione dell'HTML in PDF non riuscita: {error}")
                try:
                    replace_with_retry(tmp, final)
                except OSError as exc:
                    raise CompareError(f"impossibile salvare il PDF convertito: {exc}") from None
            finally:
                for leftover in (src, tmp, tmp.with_name(tmp.stem + ".sanitised.html")):
                    remove_quietly(leftover)
        return final


# ------------------------------------------------------------------ helpers ---

def _label(version: Version) -> str:
    return _LABELS.get(version.kind, str(version.kind))


def _of(label: str) -> str:
    return "dell'" if label[:1].upper() in "AEIOU" else "del "


def _read_version(version: Version, label: str) -> bytes:
    """The bytes of ``version``'s file (hashed, and for an HTML also printed)."""
    if version.broken:  # its metadata cannot be trusted to name a file
        raise CompareError(f"{label}: {version.broken}")
    try:
        return version.path.read_bytes()
    except FileNotFoundError:
        raise CompareError(f"il file {_of(label)}{label} non esiste più: {version.path.name}") from None
    except OSError as exc:
        raise CompareError(f"impossibile leggere il file {_of(label)}{label} ({version.path.name}): {exc}") from None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case_folder(version: Version) -> Path:
    """``<case>`` from ``<case>\\target|asis|tobe\\<file>``."""
    slot = version.path.parent
    if slot.name not in ("target", "asis", "tobe"):
        raise CompareError(f"il file {version.path.name} non appartiene a un caso dell'Officina")
    return slot.parent


def _pdf_problem(path: Path) -> str:
    """Empty for a complete-looking PDF, else why not. Edge's own check
    (``%PDF-`` header, over ``MIN_PDF_BYTES``) plus a ``%%EOF`` near the end,
    which a file cut short by a crash does not have."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(5)
            fh.seek(max(0, size - 1024))
            tail = fh.read()
    except OSError:
        return "nessun PDF scritto"
    if head != b"%PDF-":
        return "il file scritto non è un PDF"
    if size <= MIN_PDF_BYTES:
        return f"PDF troppo piccolo ({size} byte)"
    if b"%%EOF" not in tail:
        return "PDF incompleto (manca la fine del file)"
    return ""
