"""The Officina document viewer: one PDF as a column of pages, with overlays.

:class:`DocView` is a ``QGraphicsView`` (spec §7, research §14: not QPdfView,
which needs PySide6-Addons and has no overlay API). The scene is in PDF
**points** of the displayed page (the space of ``compare.extract_pdf`` Word
boxes), pages stacked top to bottom:

* each page starts as a placeholder (``surface2``) and gets its image from a
  :class:`~qtrequestory.ui.pages.officina_render.PageRenderer` only when it is
  visible — plus one page above and one below, rendered ahead. Pages far from
  the view give their image back, so a 60-page document never holds 60 images
  (Review Focus 3);
* the image is rendered at the view's zoom × the screen's device-pixel ratio
  (HiDPI), snapped to a scale bucket, then scaled back into page points;
* differences are :class:`~qtrequestory.ui.pages.officina_overlays.HighlightItem`
  boxes (managed by ``HighlightsMixin`` there); a click — not a drag — on one
  emits :attr:`DocView.difference_clicked`, and
  :meth:`DocView.focus_difference` scrolls to one and rings it.

:class:`SyncController` keeps two views in step — scroll by *relative page
position* (page index + fraction of that page), and zoom — and can be switched
off. All colours come from ``theme.tokens()`` and follow ``theme.signals``.
"""
from __future__ import annotations

import bisect
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from PySide6.QtCore import QPoint, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QTransform
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.officina_overlays import HighlightItem, HighlightsMixin, PageSlot
from qtrequestory.ui.pages.officina_render import PageRenderer, bucket

if TYPE_CHECKING:
    from PySide6.QtGui import QImage


__all__ = ["DocView", "SyncController", "ZoomMode"]

ZoomMode = Literal["fit_width", "fit_page"] | float

#: Scene layout, in points: space between pages and around the column.
GAP = 12.0
MARGIN = 12.0
#: Logical pixels per point at 100 % (a page shown at its printed size).
PX_PER_PT = 96 / 72
MIN_ZOOM, MAX_ZOOM = 0.25, 4.0
#: Pages rendered ahead above and below the visible ones.
PREFETCH = 1
#: Pages beyond the visible ones (each side) that keep their image.
KEEP = 3
#: Never render above this many pixels per point (A4 ≈ 2400 × 3400 px).
MAX_RENDER_SCALE = 4.0
#: After a zoom change, wait this long before rendering (Ctrl+wheel bursts).
ZOOM_SETTLE_MS = 150
#: A failed page is asked once more after this delay (file being rewritten).
RETRY_MS = 500


class DocView(HighlightsMixin, QGraphicsView):
    """One document's pages, rendered on demand, with difference overlays."""

    difference_clicked = Signal(int)  # Difference.id
    zoom_changed = Signal()           # set_zoom / Ctrl+wheel (not a fit refresh)

    def __init__(self, renderer: PageRenderer | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        if renderer is None:
            pool = QThreadPool(self)
            pool.setMaxThreadCount(1)  # PDFium renders one page at a time anyway
            renderer = PageRenderer(pool, parent=self)
        self._renderer = renderer
        renderer.rendered.connect(self._on_rendered)
        renderer.failed.connect(self._on_failed)
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        # Always on: a scroll bar appearing would change the width fit_width fits.
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self._doc_id = ""
        self._path = Path()
        self._pages: list[PageSlot] = []
        self._tops: list[float] = []
        self._asked: set[tuple[int, float]] = set()
        self._init_highlights()
        self._mode: str | None = "fit_width"
        self._zoom = 1.0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._update_pages)
        self._settle_until = 0.0  # time.monotonic() before which nothing renders
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.setInterval(RETRY_MS)
        self._retry.timeout.connect(self._schedule)
        self._press: QPoint | None = None
        self.verticalScrollBar().valueChanged.connect(self._schedule)
        self.horizontalScrollBar().valueChanged.connect(self._schedule)
        theme.signals.changed.connect(self._recolour)
        self._recolour()

    # -- loading -------------------------------------------------------------

    def load(self, doc_id: str, path: Path, page_sizes: list[tuple[float, float]]) -> None:
        """Show ``path`` (pages of ``page_sizes`` points) as placeholders.

        Nothing is rendered here: the visible pages are requested on the next
        turn of the event loop, the others only when scrolled to.
        """
        self._renderer.forget(self._doc_id, ())
        scene = self.scene()
        for page in self._pages:
            page.remove()
        self._clear_highlights()
        self._doc_id, self._path = doc_id, Path(path)
        self._pages, self._tops, self._asked = [], [], set()
        widest = max((w for w, _ in page_sizes), default=0.0)
        y = MARGIN
        for number, (w, h) in enumerate(page_sizes, 1):
            rect = QRectF((widest - w) / 2, y, w, h)
            label = strings.OFFICINA_VIEWER_PAGE.format(n=number)
            self._pages.append(PageSlot(scene, rect, label))
            self._tops.append(y)
            y += h + GAP
        bottom = y - GAP + MARGIN if page_sizes else 2 * MARGIN
        scene.setSceneRect(QRectF(-MARGIN, 0, widest + 2 * MARGIN, bottom))
        self._recolour()
        self._apply_zoom(keep_position=False)
        self._settle_until = 0.0  # a new document renders at once
        self.verticalScrollBar().setValue(self.verticalScrollBar().minimum())
        self._schedule()

    def page_count(self) -> int:
        return len(self._pages)

    def page_rect(self, page: int) -> QRectF:
        """Page ``page`` in scene coordinates (points)."""
        return QRectF(self._pages[page].rect)

    def has_image(self, page: int) -> bool:
        return self._pages[page].pixmap is not None

    def page_bucket(self, page: int) -> float | None:
        """The scale bucket of the image ``page`` shows (None: no image)."""
        return self._pages[page].bucket

    def page_error(self, page: int) -> str | None:
        """The message shown on ``page`` when it could not be rendered."""
        error = self._pages[page].error
        return None if error is None else strings.OFFICINA_VIEWER_PAGE_ERROR.format(
            n=page + 1, reason=error)

    def placeholder_colour(self) -> QColor:
        """The fill the page placeholders are painted with now."""
        if self._pages:
            return self._pages[0].placeholder.brush().color()
        return QColor(theme.tokens().surface2)

    # -- zoom --------------------------------------------------------------------

    def set_zoom(self, mode: ZoomMode) -> None:
        """``"fit_width"``, ``"fit_page"`` or a factor (1.0 = printed size)."""
        if isinstance(mode, str):
            if mode not in ("fit_width", "fit_page"):
                raise ValueError(f"unknown zoom mode {mode!r}")
            self._mode = mode
        else:
            self._mode = None
            self._zoom = min(MAX_ZOOM, max(MIN_ZOOM, float(mode)))
        self._apply_zoom(keep_position=True)
        self.zoom_changed.emit()

    def zoom(self) -> float:
        return self._zoom

    def zoom_mode(self) -> str | None:
        """The fit mode, or None for a fixed factor."""
        return self._mode

    def _apply_zoom(self, *, keep_position: bool) -> None:
        position = self.relative_position() if keep_position and self._pages else None
        if self._mode is not None:
            self._zoom = self._fit_zoom(self._mode)
        scale = self._zoom * PX_PER_PT
        if scale != self.transform().m11():
            self._settle_until = time.monotonic() + ZOOM_SETTLE_MS / 1000
        self.setTransform(QTransform.fromScale(scale, scale))
        if position is not None:
            self.scroll_to_position(*position)
        self._schedule()

    def _fit_zoom(self, mode: str) -> float:
        scene = self.sceneRect()
        viewport = self.viewport().size()
        if scene.width() <= 0 or viewport.width() <= 0:
            return self._zoom
        fit = viewport.width() / scene.width()
        if mode == "fit_page":
            tallest = max((p.rect.height() for p in self._pages), default=0.0) + 2 * GAP
            if tallest > 0:
                fit = min(fit, viewport.height() / tallest)
        return min(MAX_ZOOM, max(MIN_ZOOM, fit / PX_PER_PT))

    def resizeEvent(self, event) -> None:  # noqa: D102, N802
        super().resizeEvent(event)
        if self._mode is not None:
            self._apply_zoom(keep_position=True)
        self._schedule()

    def wheelEvent(self, event) -> None:  # noqa: D102, N802 - Ctrl+wheel zooms
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self.set_zoom(self._zoom * 1.1 ** steps)
            event.accept()
            return
        super().wheelEvent(event)

    # -- position ----------------------------------------------------------------

    def relative_position(self) -> tuple[int, float]:
        """(page, fraction) at the top of the view; the fraction runs over the
        page *and* the gap after it, so it is continuous across pages."""
        if not self._pages:
            return 0, 0.0
        # half a pixel of slack: scrolling lands on whole pixels
        y = self.mapToScene(0, 0).y() + 0.5 / self.transform().m22()
        page = self._page_at(y)
        stride = self._pages[page].rect.height() + GAP
        return page, min(1.0, max(0.0, (y - self._tops[page]) / stride))

    def scroll_to_position(self, page: int, fraction: float) -> None:
        """Put ``fraction`` of ``page`` at the top; past the last page: the end."""
        if not self._pages:
            return
        bar = self.verticalScrollBar()
        if page >= len(self._pages):
            bar.setValue(bar.maximum())
            return
        page = max(0, page)
        target = self._tops[page] + fraction * (self._pages[page].rect.height() + GAP)
        delta = (target - self.mapToScene(0, 0).y()) * self.transform().m22()
        bar.setValue(bar.value() + round(delta))

    def visible_pages(self) -> range:
        if not self._pages:
            return range(0)
        area = self._visible_scene_rect()
        first = self._page_at(area.top())
        if area.top() > self._pages[first].rect.bottom():
            first += 1  # the top of the view is in the gap after `first`
        last = self._page_at(area.bottom())
        return range(first, max(first, last + 1)) if first < len(self._pages) else range(0)

    def _visible_scene_rect(self) -> QRectF:
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def _page_at(self, y: float) -> int:
        """The last page starting at or above scene ``y`` (0 above the first)."""
        return max(0, bisect.bisect_right(self._tops, y) - 1)

    # -- rendering ---------------------------------------------------------------

    def _schedule(self, *_args) -> None:
        """Update the rendered pages on the next event-loop turn — or, right
        after a zoom change, once the zoom has settled."""
        if self._pages:
            wait = max(0.0, self._settle_until - time.monotonic())
            self._timer.start(round(wait * 1000))

    def _wanted_bucket(self) -> float:
        ratio = self.devicePixelRatioF() or 1.0
        return bucket(min(MAX_RENDER_SCALE, self.transform().m11() * ratio))

    def _update_pages(self) -> None:
        visible = self.visible_pages()
        if not visible:
            return
        wanted = range(max(0, visible.start - PREFETCH), min(len(self._pages), visible.stop + PREFETCH))
        keep = range(visible.start - KEEP, visible.stop + KEEP)
        for number, page in enumerate(self._pages):
            if page.pixmap is not None and number not in keep:
                page.drop_image()
        scale = self._wanted_bucket()
        cancelled = self._renderer.forget(self._doc_id, wanted, keep_scale=scale)
        # _asked holds requests in flight only: answered or taken back leave it
        self._asked = {(p, b) for p, b in self._asked if p in keep} - cancelled
        for number in wanted:
            page = self._pages[number]
            if page.error is None and page.bucket != scale and (number, scale) not in self._asked:
                self._asked.add((number, scale))
                self._renderer.request(self._doc_id, self._path, number, scale)

    def _on_rendered(self, doc_id: str, number: int, image: QImage) -> None:
        if doc_id != self._doc_id or not 0 <= number < len(self._pages) or image.isNull():
            return
        page = self._pages[number]
        got = bucket(image.width() / page.rect.width())
        self._asked.discard((number, got))  # answered, whether used or not
        visible = self.visible_pages()
        if not visible.start - KEEP <= number < visible.stop + KEEP:
            return  # scrolled away meanwhile: do not hold the image
        if page.pixmap is not None and got != self._wanted_bucket():
            return  # an older, other-resolution answer: keep what is shown
        page.set_image(image, got)

    def _on_failed(self, doc_id: str, number: int, reason: str) -> None:
        if doc_id != self._doc_id or not 0 <= number < len(self._pages):
            return
        page = self._pages[number]
        self._asked = {(p, b) for p, b in self._asked if p != number}
        if not page.retried:  # e.g. the file is being rewritten: ask once more
            page.retried = True
            self._retry.start()
            return
        page.error = reason
        page.set_label(self.page_error(number))
        self._recolour()

    # -- input and theme -------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: D102, N802
        left = event.button() == Qt.MouseButton.LeftButton
        self._press = event.position().toPoint() if left else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: D102, N802 - a click, not a drag
        pos = event.position().toPoint()
        press, self._press = self._press, None
        if (event.button() == Qt.MouseButton.LeftButton and press is not None
                and (pos - press).manhattanLength() < QApplication.startDragDistance()):
            for item in self.items(pos):
                if isinstance(item, HighlightItem):
                    self.difference_clicked.emit(item.diff_id)
                    break
        super().mouseReleaseEvent(event)

    def _recolour(self) -> None:
        tokens = theme.tokens()
        self.setBackgroundBrush(QBrush(QColor(tokens.bg)))
        edge = QPen(QColor(tokens.border), 1.0)
        edge.setCosmetic(True)
        for page in self._pages:
            page.recolour(tokens, edge)
        self._recolour_highlights(tokens)


# Re-exported: the viewer's public API is DocView + SyncController.
from qtrequestory.ui.pages.officina_sync import SyncController  # noqa: E402
