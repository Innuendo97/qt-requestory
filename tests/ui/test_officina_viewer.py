"""The Officina document viewer: DocView, PageRenderer, SyncController.

A 60-page synthetic PDF (tests/officina/pdfgen.py) is rendered for real by
pypdfium2 in a thread pool. Review Focus 3: a big document opens without
rendering more than the visible pages plus one on each side.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt, QThreadPool
from PySide6.QtGui import QColor

from qtrequestory.officina.compare.extract_pdf import Word, extract
from qtrequestory.ui import theme
from qtrequestory.ui.pages.officina_render import PageRenderer
from qtrequestory.ui.pages.officina_viewer import DocView, SyncController
from tests.officina import pdfgen

PAGES = 60


@pytest.fixture(scope="module")
def big_pdf(qapp, tmp_path_factory):
    """(path, DocText) of a 60-page PDF with a text layer."""
    font_id = pdfgen.load_font()
    if font_id is None:
        pytest.skip("no system font to generate PDFs with")
    try:
        folder = tmp_path_factory.mktemp("viewer")
        html = "".join(
            f"<h2 style='page-break-before: {'always' if n else 'auto'}'>Pagina {n + 1}</h2>"
            f"<p>{pdfgen.lorem(260, seed=n)}</p>"
            for n in range(PAGES)
        )
        path = pdfgen.html_pdf(folder / "big.pdf", html)
        doc = extract(path)
    finally:
        pdfgen.unload_font(font_id)
    assert len(doc.page_sizes) == PAGES
    return path, doc


class CountingRenderer(PageRenderer):
    def __init__(self, pool):
        super().__init__(pool)
        self.calls: list[tuple[str, int, float]] = []

    def request(self, doc_id, path, page, scale):
        self.calls.append((doc_id, page, scale))
        super().request(doc_id, path, page, scale)


@pytest.fixture
def pool():
    thread_pool = QThreadPool()
    yield thread_pool
    thread_pool.waitForDone(5000)


def _view(qtbot, pool, size=(800, 600)) -> tuple[DocView, CountingRenderer]:
    renderer = CountingRenderer(pool)
    view = DocView(renderer)
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    qtbot.waitExposed(view)
    return view, renderer


def _rendered_all_visible(view: DocView) -> bool:
    return all(view.has_image(p) for p in view.visible_pages())


def _first_word_on(doc, page: int) -> Word:
    return next(w for w in doc.words if w.page == page)


def test_only_visible_pages_are_rendered(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, renderer = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    qtbot.waitUntil(lambda: _rendered_all_visible(view), timeout=5000)
    qtbot.wait(200)  # nothing else trickles in afterwards
    visible = list(view.visible_pages())
    assert 1 <= len(visible) <= 3
    assert len(renderer.calls) <= len(visible) + 2
    requested = {page for _, page, _ in renderer.calls}
    assert requested <= set(range(visible[0] - 1, visible[-1] + 2))
    assert sum(view.has_image(p) for p in range(PAGES)) <= len(visible) + 2


def test_scrolling_renders_the_newly_visible_pages(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, renderer = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    qtbot.waitUntil(lambda: _rendered_all_visible(view), timeout=5000)
    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum())
    qtbot.waitUntil(lambda: view.has_image(PAGES - 1), timeout=5000)
    assert PAGES - 1 in view.visible_pages()
    assert len(renderer.calls) <= 10, "the pages scrolled past were never rendered"
    assert not view.has_image(0), "pages far away give their image back"


def test_focus_difference_scrolls_its_words_into_view(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    word = _first_word_on(doc, 40)
    view.set_highlights([(7, "changed", [word]), (8, "added", [_first_word_on(doc, 2)])])
    assert 40 not in view.visible_pages()
    view.focus_difference(7)
    rect = view.mapFromScene(view.difference_rect(7)).boundingRect()
    assert view.viewport().rect().contains(rect)
    assert view.focused_difference() == 7
    qtbot.waitUntil(lambda: view.has_image(40), timeout=5000)


def test_sync_keeps_the_relative_position_and_zoom(qtbot, pool, big_pdf):
    path, doc = big_pdf
    left, _ = _view(qtbot, pool)
    right, _ = _view(qtbot, pool)
    left.load("left", path, doc.page_sizes)
    short = doc.page_sizes[:30]
    right.load("right", path, short)
    sync = SyncController(left, right)
    left.scroll_to_position(20, 0.5)
    page, frac = right.relative_position()
    assert page == 20 and frac == pytest.approx(0.5, abs=0.02)

    right.scroll_to_position(25, 0.25)
    page, frac = left.relative_position()
    assert page == 25 and frac == pytest.approx(0.25, abs=0.02)

    left.set_zoom(2.0)
    assert right.zoom() == pytest.approx(2.0)
    right.set_zoom("fit_page")
    assert left.zoom_mode() == "fit_page"

    sync.set_enabled(False)
    left.scroll_to_position(5, 0.0)
    assert right.relative_position()[0] == 25
    sync.set_enabled(True)
    left.scroll_to_position(6, 0.0)
    assert right.relative_position()[0] == 6


def test_sync_scroll_past_the_shorter_document_stays_at_its_end(qtbot, pool, big_pdf):
    path, doc = big_pdf
    left, _ = _view(qtbot, pool)
    right, _ = _view(qtbot, pool)
    left.load("left", path, doc.page_sizes)
    right.load("right", path, doc.page_sizes[:3])
    SyncController(left, right)
    left.scroll_to_position(40, 0.0)
    bar = right.verticalScrollBar()
    assert bar.value() == bar.maximum()


def test_click_on_a_highlight_emits_its_difference(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    word = _first_word_on(doc, 0)
    view.set_highlights([(3, "removed", [word])])
    centre = view.mapFromScene(view.difference_rect(3).center())
    with qtbot.waitSignal(view.difference_clicked, timeout=1000) as blocker:
        qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    assert blocker.args == [3]
    # a click on bare page does not
    with qtbot.assertNotEmitted(view.difference_clicked):
        qtbot.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                         pos=centre + QPoint(0, 300))


def _fill(item) -> QColor:
    return item.brush().color()


def test_a_theme_switch_recolours_the_overlays(qtbot, pool, big_pdf, themed):
    path, doc = big_pdf
    theme.apply(themed, theme.Mode.LIGHT)
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    words = [_first_word_on(doc, p) for p in range(3)]
    view.set_highlights([(1, "added", [words[0]]), (2, "removed", [words[1]]),
                         (3, "changed", [words[2]])])
    view.focus_difference(1)

    def colours():
        return {kind: (_fill(view.highlight_items(i)[0]).name(),
                       view.highlight_items(i)[0].pen().color().name())
                for i, kind in ((1, "ok"), (2, "bad"), (3, "warn"))}

    light = theme.LIGHT
    assert colours() == {"ok": (light.ok_bg.lower(), light.ok.lower()),
                         "bad": (light.bad_bg.lower(), light.bad.lower()),
                         "warn": (light.warn_bg.lower(), light.warn.lower())}
    assert view.placeholder_colour().name() == light.surface2.lower()
    theme.apply(themed, theme.Mode.DARK)
    dark = theme.DARK
    assert colours() == {"ok": (dark.ok_bg.lower(), dark.ok.lower()),
                         "bad": (dark.bad_bg.lower(), dark.bad.lower()),
                         "warn": (dark.warn_bg.lower(), dark.warn.lower())}
    assert view.placeholder_colour().name() == dark.surface2.lower()
    assert view.focus_ring().pen().color().name() == dark.accent.lower()


def test_words_on_one_line_become_one_highlight(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    line = [w for w in doc.words if w.page == 1][2:5]  # after the heading
    assert line[0].y0 == pytest.approx(line[2].y0, abs=2), "fixture: three words on one line"
    view.set_highlights([(4, "changed", line)])
    assert len(view.highlight_items(4)) == 1
    rect = view.difference_rect(4)
    top = view.page_rect(1).top()
    assert rect.left() <= line[0].x0 and rect.right() >= line[2].x1
    assert rect.top() <= top + line[0].y0


def test_fit_width_follows_the_viewport(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    assert view.zoom_mode() == "fit_width"
    narrow = view.zoom()
    view.resize(1200, 600)
    qtbot.waitUntil(lambda: view.zoom() > narrow * 1.3, timeout=2000)
    page = view.mapFromScene(view.page_rect(0)).boundingRect()
    assert page.width() <= view.viewport().width()


def test_zoom_renders_sharper_images(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, renderer = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    qtbot.waitUntil(lambda: _rendered_all_visible(view), timeout=5000)
    first = max(scale for _, _, scale in renderer.calls)
    view.set_zoom(3.0)
    qtbot.waitUntil(lambda: any(scale > first * 1.5 for _, _, scale in renderer.calls)
                    and _rendered_all_visible(view), timeout=5000)


def test_an_unreadable_file_shows_an_error_page(qtbot, pool, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 rotto")
    view, _ = _view(qtbot, pool)
    view.load("left", broken, [(595.0, 842.0)])
    qtbot.waitUntil(lambda: view.page_error(0) is not None, timeout=5000)
    assert "broken.pdf" in view.page_error(0)


# -- PageRenderer -------------------------------------------------------------

def test_renderer_dedups_in_flight_requests_and_caches(qtbot, pool, big_pdf):
    path, _ = big_pdf
    renderer = PageRenderer(pool)
    got = []
    renderer.rendered.connect(lambda doc_id, page, image: got.append((doc_id, page, image.size())))
    renderer.request("a", path, 3, 1.0)
    renderer.request("a", path, 3, 1.02)  # same scale bucket, still in flight
    qtbot.waitUntil(lambda: len(got) >= 1, timeout=5000)
    qtbot.wait(100)
    assert len(got) == 1 and renderer.jobs_started == 1
    renderer.request("a", path, 3, 1.0)  # cached
    assert len(got) == 2 and renderer.jobs_started == 1
    assert got[0][2].width() == pytest.approx(595, abs=40)


def test_renderer_keeps_only_cache_pages_images(qtbot, pool, big_pdf):
    path, _ = big_pdf
    renderer = PageRenderer(pool, cache_pages=4)
    got = []
    renderer.rendered.connect(lambda *args: got.append(args[1]))
    for page in range(6):
        renderer.request("a", path, page, 0.25)
    qtbot.waitUntil(lambda: len(got) == 6, timeout=5000)
    assert renderer.cached_pages() == 4
    renderer.request("a", path, 0, 0.25)  # evicted: rendered again
    qtbot.waitUntil(lambda: len(got) == 7, timeout=5000)
    assert renderer.jobs_started == 7


def test_viewer_modules_do_not_load_pypdfium2_on_import():
    import subprocess
    import sys

    src = Path(__file__).resolve().parents[2] / "src"
    code = ("import sys; import qtrequestory.ui.pages.officina_viewer; "
            "print(any(m.startswith('pypdfium2') for m in sys.modules))")
    import os

    env = {**os.environ, "PYTHONPATH": str(src), "QT_QPA_PLATFORM": "offscreen"}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         check=True, env=env).stdout.strip()
    assert out == "False"


def test_placeholders_do_not_hold_page_images_before_rendering(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    assert not any(view.has_image(p) for p in range(PAGES))  # nothing synchronous


# -- fix round 1 ----------------------------------------------------------------

def test_fast_zoom_steps_render_only_the_final_scale(qtbot, pool, big_pdf):
    from qtrequestory.ui.pages.officina_render import bucket

    path, doc = big_pdf
    view, renderer = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    qtbot.waitUntil(lambda: _rendered_all_visible(view), timeout=5000)
    start = len(renderer.calls)
    zoom = view.zoom()
    for _ in range(10):  # ten Ctrl+wheel ticks, one event-loop turn apart
        zoom *= 1.1
        view.set_zoom(zoom)
        qtbot.wait(5)
    final = bucket(view.transform().m11() * view.devicePixelRatioF())
    qtbot.waitUntil(lambda: all(view.page_bucket(p) == final for p in view.visible_pages()),
                    timeout=5000)
    qtbot.wait(300)
    later = renderer.calls[start:]
    assert {bucket(scale) for _, _, scale in later} == {final}
    assert len(later) <= len(view.visible_pages()) + 2


def test_forget_takes_back_jobs_of_another_scale(qtbot, big_pdf):
    path, _ = big_pdf
    one = QThreadPool()
    one.setMaxThreadCount(1)
    renderer = PageRenderer(one)
    answered = []
    renderer.rendered.connect(lambda _d, page, _i: answered.append(page))
    for page in range(6):
        renderer.request("a", path, page, 1.0)
    dropped = renderer.forget("a", range(6), keep_scale=2.0)
    assert len(dropped) >= 4  # all but the one already running
    assert all(scale == 1.0 for _, scale in dropped)
    one.waitForDone(5000)
    qtbot.wait(100)
    assert len(answered) == 6 - len(dropped)


class HeldRenderer(PageRenderer):
    """Records requests and never renders: the test answers by hand."""

    def __init__(self, pool):
        super().__init__(pool)
        self.calls: list[tuple[int, float]] = []

    def request(self, doc_id, path, page, scale):
        from qtrequestory.ui.pages.officina_render import bucket

        self.calls.append((page, bucket(scale)))


def test_a_discarded_answer_does_not_block_asking_again(qtbot, pool, big_pdf):
    from PySide6.QtGui import QImage

    path, doc = big_pdf
    renderer = HeldRenderer(pool)
    view = DocView(renderer)
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    qtbot.waitExposed(view)
    view.load("left", path, doc.page_sizes)
    view.set_zoom(1.0)
    qtbot.waitUntil(lambda: bool(renderer.calls), timeout=2000)
    one = renderer.calls[-1][1]
    width = doc.page_sizes[0][0]
    for page in {p for p, _ in renderer.calls}:
        renderer.rendered.emit("left", page, QImage(round(width * one), 20, QImage.Format.Format_RGB32))
    assert view.page_bucket(0) == one
    view.set_zoom(2.0)
    qtbot.waitUntil(lambda: renderer.calls[-1][1] != one, timeout=2000)
    two = renderer.calls[-1][1]
    view.set_zoom(1.0)
    qtbot.wait(300)
    # the 2.0 answer arrives late: not wanted any more, discarded
    renderer.rendered.emit("left", 0, QImage(round(width * two), 20, QImage.Format.Format_RGB32))
    assert view.page_bucket(0) == one
    asked = len(renderer.calls)
    view.set_zoom(2.0)
    qtbot.waitUntil(lambda: (0, two) in renderer.calls[asked:], timeout=2000)


def test_cache_has_a_byte_budget(qtbot, pool, big_pdf):
    path, _ = big_pdf
    image_bytes = 149 * 211 * 4  # A4 at a quarter point per pixel
    renderer = PageRenderer(pool, cache_pages=24, cache_bytes=int(image_bytes * 2.5))
    got = []
    renderer.rendered.connect(lambda *args: got.append(args[1]))
    for page in range(5):
        renderer.request("a", path, page, 0.25)
    qtbot.waitUntil(lambda: len(got) == 5, timeout=5000)
    assert renderer.cached_pages() == 2
    assert renderer.cached_bytes() <= image_bytes * 2.5


def test_a_sharper_image_replaces_the_older_one_in_the_cache(qtbot, pool, big_pdf):
    path, _ = big_pdf
    renderer = PageRenderer(pool)
    got = []
    renderer.rendered.connect(lambda *args: got.append(args[1]))
    renderer.request("a", path, 0, 0.25)
    qtbot.waitUntil(lambda: len(got) == 1, timeout=5000)
    renderer.request("a", path, 0, 0.5)
    qtbot.waitUntil(lambda: len(got) == 2, timeout=5000)
    assert renderer.cached_pages() == 1


def test_a_drag_over_a_highlight_is_not_a_click(qtbot, pool, big_pdf):
    path, doc = big_pdf
    view, _ = _view(qtbot, pool)
    view.load("left", path, doc.page_sizes)
    view.set_highlights([(3, "removed", [_first_word_on(doc, 0)])])
    centre = view.mapFromScene(view.difference_rect(3).center())
    with qtbot.assertNotEmitted(view.difference_clicked):
        qtbot.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=centre)
    with qtbot.assertNotEmitted(view.difference_clicked):
        qtbot.mouseMove(view.viewport(), centre + QPoint(0, 60))
        qtbot.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=centre + QPoint(0, 60))


def test_sync_survives_either_view_being_deleted(qtbot, pool, big_pdf, capfd):
    path, doc = big_pdf
    left, _ = _view(qtbot, pool)
    right = DocView(PageRenderer(pool))
    right.resize(800, 600)
    right.show()
    left.load("left", path, doc.page_sizes)
    right.load("right", path, doc.page_sizes)
    sync = SyncController(left, right)
    right.deleteLater()
    qtbot.wait(50)
    assert not sync.is_attached()
    left.scroll_to_position(10, 0.0)
    left.set_zoom(2.0)
    qtbot.wait(50)
    assert "already deleted" not in capfd.readouterr().err


def test_re_enabling_sync_aligns_zoom_too(qtbot, pool, big_pdf):
    path, doc = big_pdf
    left, _ = _view(qtbot, pool)
    right, _ = _view(qtbot, pool)
    left.load("left", path, doc.page_sizes)
    right.load("right", path, doc.page_sizes)
    sync = SyncController(left, right)
    sync.set_enabled(False)
    left.set_zoom(2.5)
    left.scroll_to_position(12, 0.0)
    assert right.zoom() != pytest.approx(2.5)
    sync.set_enabled(True)
    assert right.zoom() == pytest.approx(2.5)
    assert right.relative_position()[0] == 12


def test_a_failed_page_is_retried_once(qtbot, pool, big_pdf, tmp_path):
    import shutil

    path, doc = big_pdf
    later = tmp_path / "rigenerato.pdf"  # not there yet: being regenerated
    view, renderer = _view(qtbot, pool)
    failures = []
    renderer.failed.connect(lambda *args: failures.append(args[1]))
    view.load("left", later, doc.page_sizes)
    qtbot.waitUntil(lambda: bool(failures), timeout=5000)
    shutil.copyfile(path, later)
    qtbot.waitUntil(lambda: view.has_image(0), timeout=5000)
    assert view.page_error(0) is None
