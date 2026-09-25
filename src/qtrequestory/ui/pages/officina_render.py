"""Page rendering for the Officina viewer: PDFium in a thread pool, LRU cache.

:class:`PageRenderer` turns ``(doc_id, path, page, scale)`` requests into
``QImage`` s rendered off the GUI thread by ``qtrequestory.officina.pdf`` (the
only module allowed to load pypdfium2 — imported here lazily, inside the
worker, so importing the viewer never loads it: tests/test_officina_boundary.py
and tests/ui/test_officina_viewer.py check that).

* Scales are snapped to **buckets** (steps of about 12 %), so a tiny zoom change
  reuses the images it has instead of rendering everything again.
* A request already in flight is not queued twice; a finished one lands in an
  LRU cache of ``cache_pages`` images keyed by ``(doc_id, page, bucket)``.
* A document is identified by its ``doc_id`` *and* its file (path, size,
  mtime): a new file under the same id drops the old images.
* :meth:`PageRenderer.forget` takes back queued jobs nobody needs any more
  (pages scrolled past), so a fast scroll through 60 pages does not leave the
  visible one waiting behind 58 others.

PDFium is not thread-safe: ``officina.pdf`` serialises every call with one lock,
so the pool gives responsiveness (the GUI thread never renders), not
parallel renders.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

__all__ = ["PageRenderer", "bucket"]

#: Buckets per doubling of the scale (2 ** (1/6) ≈ 12 % apart).
_STEPS = 6
MIN_SCALE, MAX_SCALE = 0.05, 8.0
#: Default byte budget of the image cache.
CACHE_BYTES = 256 * 2**20


def bucket(scale: float) -> float:
    """``scale`` snapped to the nearest bucket (what is actually rendered)."""
    scale = min(MAX_SCALE, max(MIN_SCALE, float(scale)))
    return round(2 ** (round(math.log2(scale) * _STEPS) / _STEPS), 4)


_Ident = tuple[str, int, int]          # path, size, mtime_ns
_Key = tuple[str, _Ident, int, float]  # doc_id, file, page, bucket


def _ident(path: Path) -> _Ident:
    try:
        stat = path.stat()
    except OSError:
        return str(path), -1, -1
    return str(path), stat.st_size, stat.st_mtime_ns


class _Relay(QObject):
    """Carries a finished job back to the GUI thread (queued connection)."""

    done = Signal(object, object)  # key, QImage | str (the error)


#: Jobs handed to a pool and not finished yet. ``autoDelete`` is off (``forget``
#: needs ``tryTake``), so Python must keep each wrapper alive while the pool
#: holds it — even if the renderer that queued it is gone meanwhile.
_ALIVE: set["_Job"] = set()


class _Job(QRunnable):
    def __init__(self, key: _Key, path: Path, relay: _Relay) -> None:
        super().__init__()
        self.setAutoDelete(False)  # the renderer owns it (tryTake in forget)
        self.key, self._path, self._relay = key, path, relay

    def run(self) -> None:  # noqa: D102 - QRunnable entry point
        from qtrequestory.officina import pdf  # lazy: loads pypdfium2

        _doc_id, _file, page, scale = self.key
        try:
            self._render(pdf, page, scale)
        finally:
            _ALIVE.discard(self)

    def _render(self, pdf, page: int, scale: float) -> None:
        try:
            rendered = pdf.render_page(self._path, page, scale)
            image = QImage(rendered.data, rendered.width, rendered.height, rendered.stride,
                           QImage.Format.Format_RGB32).copy()  # own the pixels
            self._relay.done.emit(self.key, image)
        except Exception as exc:  # noqa: BLE001 - any failure is shown on the page
            self._relay.done.emit(self.key, str(exc) or type(exc).__name__)


class PageRenderer(QObject):
    """Renders pages on ``pool`` and caches recent images.

    The cache holds at most ``cache_pages`` images and ``cache_bytes`` bytes
    (a page at the 4 px/pt cap is about 30 MB), least recently used out first;
    a page keeps only its newest scale.
    """

    rendered = Signal(str, int, QImage)  # doc_id, page index, image
    failed = Signal(str, int, str)       # doc_id, page index, reason (Italian)

    def __init__(self, pool: QThreadPool, cache_pages: int = 24, cache_bytes: int = CACHE_BYTES,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = pool
        self._limit = max(1, cache_pages)
        self._budget = max(1, cache_bytes)
        self._bytes = 0
        self._cache: OrderedDict[_Key, QImage] = OrderedDict()
        self._jobs: dict[_Key, _Job] = {}
        self._files: dict[str, _Ident] = {}
        self._relay = _Relay()
        self._relay.done.connect(self._on_done)
        #: How many render jobs were submitted to the pool (tests, diagnostics).
        self.jobs_started = 0

    def request(self, doc_id: str, path: Path, page: int, scale: float) -> None:
        """Render ``page`` of ``path`` at about ``scale`` pixels per point.

        The answer is :attr:`rendered` (straight away when cached) or
        :attr:`failed`; a request already in flight is not queued again.
        """
        path = Path(path)
        ident = self._file(doc_id, path)
        key = (doc_id, ident, page, bucket(scale))
        image = self._cache.get(key)
        if image is not None:
            self._cache.move_to_end(key)
            self.rendered.emit(doc_id, page, image)
            return
        if key in self._jobs:
            return
        job = _Job(key, path, self._relay)
        self._jobs[key] = job
        self.jobs_started += 1
        _ALIVE.add(job)
        self._pool.start(job)

    def forget(self, doc_id: str, keep: Iterable[int],
               keep_scale: float | None = None) -> set[tuple[int, float]]:
        """Take back ``doc_id``'s queued jobs nobody needs any more.

        That is a job for a page not in ``keep`` or — with ``keep_scale`` — for
        another scale bucket (a zoom moved on). Returns the ``(page, bucket)``
        pairs taken back: they will never answer. A job already running cannot
        be stopped and still answers.
        """
        keep = set(keep)
        wanted = None if keep_scale is None else bucket(keep_scale)
        dropped: set[tuple[int, float]] = set()
        for key, job in list(self._jobs.items()):
            _doc, _file, page, scale = key
            stale = page not in keep or (wanted is not None and scale != wanted)
            if key[0] == doc_id and stale and self._pool.tryTake(job):
                del self._jobs[key]
                _ALIVE.discard(job)
                dropped.add((page, scale))
        return dropped

    def cached_pages(self) -> int:
        return len(self._cache)

    def cached_bytes(self) -> int:
        return self._bytes

    # -- internals ---------------------------------------------------------

    def _file(self, doc_id: str, path: Path) -> _Ident:
        """The file identity of ``doc_id``; a new file drops the old images."""
        ident = _ident(path)
        if self._files.get(doc_id) != ident:
            self._files[doc_id] = ident
            for key in [k for k in self._cache if k[0] == doc_id]:
                self._drop(key)
        return ident

    def _drop(self, key: _Key) -> None:
        self._bytes -= self._cache.pop(key).sizeInBytes()

    def _store(self, key: _Key, image: QImage) -> None:
        """Cache ``image``, replacing the page's other scales; evict LRU to fit."""
        doc_id, ident, page, _scale = key
        for other in [k for k in self._cache if k[:3] == (doc_id, ident, page)]:
            self._drop(other)
        self._cache[key] = image
        self._bytes += image.sizeInBytes()
        while len(self._cache) > 1 and (len(self._cache) > self._limit or self._bytes > self._budget):
            self._drop(next(iter(self._cache)))

    def _on_done(self, key: _Key, result: object) -> None:
        self._jobs.pop(key, None)
        doc_id, ident, page, _scale = key
        if self._files.get(doc_id) != ident:
            return  # an answer for a file this id no longer shows
        if isinstance(result, QImage):
            self._store(key, result)
            self.rendered.emit(doc_id, page, result)
        else:
            self.failed.emit(doc_id, page, str(result))
