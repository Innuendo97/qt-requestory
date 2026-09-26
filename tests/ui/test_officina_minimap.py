"""Officina phase 2 (U5): the minimap beside each document (spec §7.1).

One segment per difference the viewer draws, coloured by verdict, at the
difference's relative vertical position in its document; a click on a
segment goes to that difference, elsewhere to that point of the document.
Offscreen, no PDF rendering (placeholders only).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt, QThreadPool
from PySide6.QtTest import QTest

from qtrequestory.ui import theme
from qtrequestory.ui.contracts import Judged, Word
from qtrequestory.ui.pages.officina_minimap import MINIMAP_W, MiniMap, document_segments
from qtrequestory.ui.pages.officina_render import PageRenderer
from qtrequestory.ui.pages.officina_viewer import GAP, MARGIN, DocView
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_page import open_case, wait_idle

PAGE = (600.0, 800.0)


class SilentRenderer(PageRenderer):
    def request(self, doc_id, path, page, scale):  # placeholders only
        pass


@pytest.fixture
def view(qtbot):
    pool = QThreadPool()
    widget = DocView(SilentRenderer(pool))
    qtbot.addWidget(widget)
    widget.resize(700, 500)
    widget.show()
    qtbot.waitExposed(widget)
    widget.load("doc", Path("nessuno.pdf"), [PAGE, PAGE, PAGE])
    yield widget
    pool.waitForDone(2000)


def _j(diff_id: int, verdict, page: int, y: float, *, klass="testo", side="both", **flags) -> Judged:
    diff = fake_diff("cambiato", klass, f"t{diff_id}", f"g{diff_id}", diff_id=diff_id)
    word = (Word(f"w{diff_id}", page, 60, y, 140, y + 12),)
    diff = dataclasses.replace(diff, left=word if side in ("both", "left") else (),
                               right=word if side in ("both", "right") else ())
    return Judged(diff, verdict, **flags)


def _height() -> float:
    return 2 * MARGIN + 3 * PAGE[1] + 2 * GAP


def test_segments_sit_at_the_relative_position_of_their_difference():
    tops = [MARGIN + i * (PAGE[1] + GAP) for i in range(3)]
    items = [(_j(1, "regressione", 0, 100), "left"), (_j(2, "da_fare", 2, 700), "left")]
    segs = document_segments(items, show_done=False, page_tops=tops, height=_height())
    assert [(s.diff_id, s.state) for s in segs] == [(1, "regressione"), (2, "da_fare")]
    first, last = segs
    assert first.top == pytest.approx((tops[0] + 100 - 1) / _height(), abs=1e-6)
    assert first.bottom == pytest.approx((tops[0] + 112 + 1) / _height(), abs=1e-6)
    assert last.top == pytest.approx((tops[2] + 700 - 1) / _height(), abs=1e-6)
    assert 0.0 < first.top < first.bottom < last.top < last.bottom < 1.0


def test_fatte_are_hidden_unless_shown_and_only_on_the_target_side():
    tops = [MARGIN]
    done = _j(1, "fatta", 0, 100)
    assert document_segments([(done, "left")], show_done=False, page_tops=tops, height=900) == []
    assert document_segments([(done, "right")], show_done=True, page_tops=tops, height=900) == []
    shown = document_segments([(done, "left")], show_done=True, page_tops=tops, height=900)
    assert [s.state for s in shown] == ["fatta"]


def test_variables_noise_and_wordless_sides_have_no_segment():
    tops = [MARGIN]
    items = [(_j(1, None, 0, 100, klass="variabile"), "left"),
             (_j(2, None, 0, 200, klass="rumore"), "left"),
             (_j(3, "da_fare", 0, 300, side="right"), "left"),
             (_j(4, "in_corso", 0, 400), "left")]
    segs = document_segments(items, show_done=False, page_tops=tops, height=900)
    assert [s.diff_id for s in segs] == [4]


def test_a_marked_difference_is_a_green_dashed_segment():
    tops = [MARGIN]
    segs = document_segments([(_j(1, "da_fare", 0, 100, marked=True), "left")], show_done=False,
                             page_tops=tops, height=900)
    assert segs[0].state == "da_verificare"
    from qtrequestory.ui.pages.officina_strip import SEGMENT_LOOKS
    fill, edge, dashed = SEGMENT_LOOKS["da_verificare"]
    assert (fill, edge, dashed) == (None, "ok", True)


def test_the_view_feeds_its_minimap_and_it_sits_beside_the_scroll_bar(view, qtbot):
    view.set_highlights([(_j(1, "regressione", 1, 400), "left"),
                         (_j(2, "fatta", 0, 50), "left")])
    minimap = view.minimap
    assert isinstance(minimap, MiniMap)
    assert [(s.diff_id, s.state) for s in minimap.segments()] == [(1, "regressione")]
    view.set_show_done(True)
    assert {s.diff_id for s in minimap.segments()} == {1, 2}
    viewport, geo = view.viewport().geometry(), minimap.geometry()
    bar_left = view.verticalScrollBar().mapTo(view, QPoint(0, 0)).x()
    assert geo.width() == MINIMAP_W and minimap.isVisible()
    assert viewport.right() < geo.left() and geo.right() < bar_left
    assert geo.height() == viewport.height()
    rect = minimap.segment_rect(minimap.segments()[1])  # page 2 of 3: the middle
    assert geo.height() * 0.3 < rect.center().y() < geo.height() * 0.7


def test_the_minimap_follows_the_viewport_when_a_horizontal_scroll_bar_appears(view, qtbot):
    """U5 minor 5 (R42): zooming in brings the horizontal scroll bar, which
    shortens the viewport without resizing the view: the minimap follows."""
    before = view.viewport().geometry().height()
    view.set_zoom(3.0)
    qtbot.waitUntil(lambda: view.horizontalScrollBar().isVisible(), timeout=3000)
    viewport = view.viewport().geometry()
    assert viewport.height() < before
    qtbot.waitUntil(lambda: view.minimap.geometry().height() == view.viewport().geometry().height(),
                    timeout=3000)
    view.set_zoom("fit_width")
    qtbot.waitUntil(lambda: not view.horizontalScrollBar().isVisible(), timeout=3000)
    qtbot.waitUntil(lambda: view.minimap.geometry().height() == view.viewport().geometry().height(),
                    timeout=3000)


def test_a_click_on_a_segment_goes_to_its_difference(view, qtbot):
    far = _j(7, "in_corso", 2, 600)
    view.set_highlights([(far, "left")])
    assert view.verticalScrollBar().value() == 0
    minimap = view.minimap
    point = minimap.segment_rect(minimap.segments()[0]).center().toPoint()
    with qtbot.waitSignal(view.minimap_chosen) as got:
        QTest.mouseClick(minimap, Qt.MouseButton.LeftButton, pos=point)
    assert got.args == [7]
    assert view.focused_difference() == 7
    assert view._visible_scene_rect().contains(view.difference_rect(7))


def test_a_click_elsewhere_scrolls_to_that_point_of_the_document(view, qtbot):
    view.set_highlights([])
    minimap = view.minimap
    QTest.mouseClick(minimap, Qt.MouseButton.LeftButton,
                     pos=QPoint(MINIMAP_W // 2, round(minimap.height() * 0.75)))
    centre = view.mapToScene(view.viewport().rect().center()).y()
    assert centre == pytest.approx(0.75 * view.sceneRect().height(), abs=40)
    top, bottom = minimap.band()
    assert top < 0.75 < bottom


def test_the_minimap_paints_in_both_themes(view, qtbot, themed):
    view.set_highlights([(_j(1, "regressione", 0, 100), "left"),
                         (_j(2, "da_fare", 1, 100, unresolved=True), "left"),
                         (_j(3, "da_fare", 1, 300, marked=True), "left"),
                         (_j(4, "tollerata", 2, 100), "left")])
    for mode in (theme.Mode.LIGHT, theme.Mode.DARK):
        theme.apply(themed, mode)
        image = view.minimap.grab().toImage()
        assert not image.isNull()
        colour = image.pixelColor(MINIMAP_W // 2 * round(image.devicePixelRatio()),
                                  round(view.minimap.segment_rect(view.minimap.segments()[0])
                                        .center().y() * image.devicePixelRatio()))
        assert colour.name() == theme.tokens().bad.lower()


# ------------------------------------------------------------- page level ---

def test_a_minimap_click_selects_the_difference_in_the_list(qtbot, fake_core, runner, tmp_path):
    from qtrequestory.ui.pages.officina_page import OfficinaPage
    from tests.ui.test_officina_page import FakeWindow

    page = OfficinaPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    page.resize(1300, 760)
    page.show()
    case = open_case(page, fake_core, tmp_path)
    page.case_view.regenerate_button.click()
    wait_idle(qtbot, page)
    words = lambda y: (Word("x", 0, 60, y, 140, y + 12),)  # noqa: E731
    diffs = [dataclasses.replace(fake_diff("cambiato", "testo", t, t[:-1]), left=words(y),
                                 right=words(y)) for t, y in (("Titolo", 100), ("Testo", 400))]
    fake_core.officina.set_canned(case.id, 1, diffs)
    page.open_case(case.id, "v1")
    view = page.case_view.left.view
    qtbot.waitUntil(lambda: len(view.minimap.segments()) == 2, timeout=10000)
    second = view.minimap.segments()[1]
    QTest.mouseClick(view.minimap, Qt.MouseButton.LeftButton,
                     pos=view.minimap.segment_rect(second).center().toPoint())
    assert page.case_view.diffs.current_id() == second.diff_id
    assert page.case_view.right.view.focused_difference() == second.diff_id
