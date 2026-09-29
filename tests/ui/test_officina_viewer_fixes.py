"""Officina 2.5, U1 (spec §4): the viewer bugs seen on the first real case.

Per-box selection outlines (never their union), one ring per view with no
leftovers, scrolling only for the anchor box, vertical AND horizontal sync
(zoom too, Ctrl+wheel around the cursor), the side without words aligned to
the corresponding place, no highlight on invisible or off-page words.

The views load placeholders only (a renderer that never renders): the
overlays and the geometry do not need page images.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsView

from qtrequestory.ui.contracts import Anchor, Diff, Judged, Word
from qtrequestory.ui.pages.officina_render import PageRenderer
from qtrequestory.ui.pages.officina_viewer import DocView, SyncController

A4 = (595.0, 842.0)


class SilentRenderer(PageRenderer):
    def request(self, doc_id, path, page, scale):  # never renders: placeholders only
        pass


@pytest.fixture
def make_view(qtbot, tmp_path):
    def make(pages: int = 3, size=(700, 600)) -> DocView:
        view = DocView(SilentRenderer(None))
        qtbot.addWidget(view)
        view.resize(*size)
        view.show()
        qtbot.waitExposed(view)
        view.load("doc", tmp_path / "nessuno.pdf", [A4] * pages)
        return view
    return make


@dataclass(frozen=True)
class InkWord(Word):
    """A Word as A1 will flag it (the UI reads the flags with getattr)."""

    invisible: bool = False
    off_page: bool = False


def _w(text, page, x0, y0, x1=None, cls=Word, **flags):
    return cls(text, page, x0, y0, x1 if x1 is not None else x0 + 40, y0 + 12, **flags)


def _j(diff_id, left=(), right=(), verdict="da_fare") -> Judged:
    lt, rt = " ".join(w.text for w in left), " ".join(w.text for w in right)
    op = "cambiato" if left and right else ("mancante" if left else "in_piu")
    diff = Diff(diff_id, op, "testo", tuple(left), tuple(right), lt, rt, (), (),
                Anchor(op, "testo", f"c{diff_id}", lt))
    return Judged(diff, verdict)


def _rings(view: DocView) -> list:
    """Every scene item that is not a page, a label, a highlight or a mark: the ring(s)."""
    return [i for i in view.scene().items() if i.zValue() == 3]


# -- 1. per-box outlines ------------------------------------------------------------

def test_the_ring_outlines_each_box_not_their_union(make_view):
    view = make_view()
    # a section that jumps from the bottom of the left column to the top of the right one
    words = [_w("Sconti", 0, 40, 700), _w("offerta.", 0, 320, 180)]
    view.set_highlights([(_j(1, left=words), "left")])
    view.focus_difference(1)
    boxes = view.difference_boxes(1)
    assert len(boxes) == 2
    polygons = view.focus_ring().path().toFillPolygons()
    assert len(polygons) == 2, "one outline per box"
    for box in boxes:
        assert any(p.boundingRect().contains(box) for p in polygons)
    middle = (boxes[0].center() + boxes[1].center()) / 2
    assert not view.focus_ring().path().contains(middle), "never the union"


def test_one_ring_item_per_view_after_several_selections(make_view):
    view = make_view()
    items = [(_j(n, left=[_w(f"p{n}", n % 3, 60, 100 + 40 * n)]), "left") for n in range(1, 6)]
    view.set_highlights(items)
    assert view.viewportUpdateMode() == QGraphicsView.ViewportUpdateMode.FullViewportUpdate
    for n in (1, 4, 2, 5, 3, 2):
        view.focus_difference(n)
        assert len(_rings(view)) == 1
    (ring,) = _rings(view)
    assert ring is view.focus_ring() and ring.isVisible()
    assert ring.path().boundingRect().contains(view.difference_boxes(2)[0])


def test_the_view_scrolls_only_when_the_anchor_box_is_hidden(make_view):
    view = make_view()
    near, far = _w("inizio", 0, 60, 60), _w("seguito", 0, 300, 800)
    view.set_highlights([(_j(1, left=[near, far]), "left")])
    before = view.verticalScrollBar().value()
    view.focus_difference(1)
    assert view.verticalScrollBar().value() == before, "the first box is on screen: stay"


def test_the_clicked_box_is_the_anchor(qtbot, make_view):
    view = make_view()
    view.set_zoom(1.0)
    words = [_w("uno", 0, 60, 100), _w("due", 0, 300, 300)]
    view.set_highlights([(_j(1, left=words), "left")])
    second = view.difference_boxes(1)[1]
    qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.mapFromScene(second.center()))
    assert view.difference_rect(1) == second
    view.set_highlights([(_j(1, left=words), "left")])  # the refresh after an action
    assert view.difference_rect(1) == second, "kept across a redraw"
    view.set_highlights([(_j(2, left=words), "left")])
    assert view.difference_rect(2) == view.difference_boxes(2)[0]


# -- 6. invisible / off-page ----------------------------------------------------------

def test_invisible_and_off_page_words_get_no_highlight(make_view):
    view = make_view(pages=1)
    white = _w("10733", 0, 0, 826, cls=InkWord, invisible=True)
    flagged = _w("fuori", 0, 60, 400, cls=InkWord, off_page=True)
    below = _w("sotto", 0, 60, 900)  # past the bottom of an 842 pt page
    shown = _w("vero", 0, 60, 200)
    view.set_highlights([(_j(1, left=[white]), "left"), (_j(2, left=[flagged, below]), "left"),
                         (_j(3, left=[white, shown]), "left")])
    assert view.highlight_items(1) == [] and view.highlight_items(2) == []
    assert len(view.highlight_items(3)) == 1
    assert {s.diff_id for s in view.minimap.segments()} == {3}


# -- 3. 2D sync, zoom around the cursor -------------------------------------------------

def _centre_fraction_x(view: DocView) -> float:
    rect = view.sceneRect()
    return (view.mapToScene(view.viewport().rect().center()).x() - rect.left()) / rect.width()


def test_sync_follows_the_horizontal_scroll_too(make_view):
    left, right = make_view(size=(600, 600)), make_view(size=(760, 600))
    sync = SyncController(left, right)
    left.set_zoom(2.5)
    assert right.zoom() == pytest.approx(2.5)
    bar = left.horizontalScrollBar()
    bar.setValue(round(bar.maximum() * 0.7))  # the wider view cannot reach the very edge
    assert _centre_fraction_x(left) > 0.6
    assert _centre_fraction_x(right) == pytest.approx(_centre_fraction_x(left), abs=0.02)
    right.horizontalScrollBar().setValue(0)
    assert _centre_fraction_x(left) == pytest.approx(_centre_fraction_x(right), abs=0.02)
    sync.set_enabled(False)
    held = right.horizontalScrollBar().value()
    left.horizontalScrollBar().setValue(round(left.horizontalScrollBar().maximum() * 0.6))
    assert right.horizontalScrollBar().value() == held
    sync.set_enabled(True)
    assert _centre_fraction_x(right) == pytest.approx(_centre_fraction_x(left), abs=0.02)


def test_ctrl_wheel_zooms_around_the_cursor(make_view):
    view = make_view()
    view.set_zoom(1.5)
    at = QPoint(500, 400)
    before = view.mapToScene(at)
    event = QWheelEvent(QPointF(at), QPointF(view.viewport().mapToGlobal(at)), QPoint(0, 0),
                        QPoint(0, 240), Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view.viewport(), event)
    assert view.zoom() == pytest.approx(1.5 * 1.21)
    after = view.mapToScene(at)
    assert after.x() == pytest.approx(before.x(), abs=2) and after.y() == pytest.approx(before.y(), abs=2)


# -- 5. the side without words ------------------------------------------------------------

def test_the_side_without_words_goes_to_the_corresponding_place(make_view):
    left, right = make_view(), make_view()
    sync = SyncController(left, right)
    left.set_zoom(1.0)
    missing = _j(1, left=[_w("10733", 1, 60, 780)])
    left.set_highlights([(missing, "left")])
    right.set_highlights([(missing, "right")])
    sync.focus_difference(1)
    target = left.difference_rect(1)
    assert left.mapToScene(left.viewport().rect()).boundingRect().contains(target)
    assert right.focused_difference() is None and not right.focus_ring().isVisible()
    place = right.page_rect(1).topLeft() + target.center() - left.page_rect(1).topLeft()
    seen = right.mapToScene(right.viewport().rect()).boundingRect()
    assert seen.contains(place), (seen, place)
    y_left = left.mapFromScene(target.center()).y()
    assert right.mapFromScene(place).y() == pytest.approx(y_left, abs=4), "side by side"


def test_the_side_without_words_goes_to_the_engine_insertion_point(make_view):
    """I1 (spec §4.5): with ``Diff.empty_at`` the empty side lines up the
    word next to the insertion point, not the same point of the same page."""
    import dataclasses

    left, right = make_view(), make_view()
    sync = SyncController(left, right)
    left.set_zoom(1.0)
    missing = _j(1, left=[_w("10733", 1, 60, 780)])
    # on the version the paragraph moved: its insertion point is on page 2, near the top
    missing = Judged(dataclasses.replace(missing.diff, empty_at=(2, 300.0, 120.0, 340.0, 132.0)), "da_fare")
    left.set_highlights([(missing, "left")])
    right.set_highlights([(missing, "right")])
    at = right.insertion_rect(1)
    assert at.topLeft() == right.page_rect(2).topLeft() + QPointF(300.0, 120.0)
    sync.focus_difference(1)
    target = left.difference_rect(1)
    seen = right.mapToScene(right.viewport().rect()).boundingRect()
    assert seen.contains(at.center()), (seen, at)
    y_left = left.mapFromScene(target.center()).y()
    assert right.mapFromScene(at.center()).y() == pytest.approx(y_left, abs=4), "side by side"
    assert right.focused_difference() is None and not right.focus_ring().isVisible()
    # a side that has the words has no insertion point
    assert left.insertion_rect(1).isNull()


def test_focus_without_scroll_rings_but_does_not_move(make_view):
    view = make_view()
    view.set_highlights([(_j(1, left=[_w("lontano", 2, 60, 700)]), "left")])
    before = view.verticalScrollBar().value()
    view.focus_difference(1, scroll=False)
    assert view.verticalScrollBar().value() == before
    assert view.focused_difference() == 1 and view.focus_ring().isVisible()
