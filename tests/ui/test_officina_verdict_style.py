"""Verdict styling of the Officina viewer (phase 2, spec §7.1).

``look_for`` maps a judged difference to its look (token names, never hex);
the viewer draws it: filled and outlined for the open verdicts, a dashed
2 px green edge for "da verificare", dashed grey for tolerated/noise, a
dashed violet underline for variables, a thin green underline on the target
side for "fatta" (only when the "show fatte" flag is on), and the changed
characters as yellow sub-rects proportional to their offsets in the word.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtGui import QColor

from qtrequestory.officina.compare.model import Anchor, CaseSummary, Diff, Judged, Word
from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages import officina_verdict_style as vs
from qtrequestory.ui.pages.officina_overlays import span_boxes
from qtrequestory.ui.pages.officina_render import PageRenderer
from qtrequestory.ui.pages.officina_viewer import DocView
from tests.fakes.fake_core import canned_pdf

UI_DIR = Path(theme.__file__).parent


def _diff(klass="testo", op="cambiato", left_text="12,00", right_text="11,50", *,
          left=(), right=(), left_spans=None, right_spans=None, diff_id=1) -> Diff:
    return Diff(
        id=diff_id, op=op, klass=klass, left=tuple(left), right=tuple(right),
        left_text=left_text, right_text=right_text,
        left_spans=((0, len(left_text)),) if left_spans is None else left_spans,
        right_spans=((0, len(right_text)),) if right_spans is None else right_spans,
        anchor=Anchor(op, klass, "", left_text),
    )


#: One Judged per state the viewer tells apart.
STATES = {
    "regressione": Judged(_diff(), "regressione"),
    "non_risolta": Judged(_diff(), "da_fare", unresolved=True),
    "da_fare": Judged(_diff(), "da_fare"),
    "in_corso": Judged(_diff(), "in_corso", previous_text="11,00"),
    "da_verificare": Judged(_diff(), "da_fare", marked=True),
    "fatta": Judged(_diff(), "fatta"),
    "tollerata": Judged(_diff(klass="stile"), "tollerata"),
    "rumore": Judged(_diff(klass="rumore"), None),
    "variabile": Judged(_diff(klass="variabile"), None),
}


# -- the looks (pure) ---------------------------------------------------------------

def test_every_verdict_and_state_has_a_distinct_look():
    looks = {name: vs.look_for(j) for name, j in STATES.items()}
    assert len(set(looks.values())) == len(looks)
    assert len({look.icon for look in looks.values()}) == len(looks)
    assert len({look.label for look in looks.values()}) == len(looks)


def test_the_spec_table():
    look = {name: vs.look_for(j) for name, j in STATES.items()}
    assert (look["regressione"].fill, look["regressione"].edge, look["regressione"].dash) == ("bad_bg", "bad", False)
    assert (look["da_fare"].fill, look["da_fare"].edge, look["da_fare"].dash) == ("warn_bg", "warn", False)
    assert (look["in_corso"].fill, look["in_corso"].edge) == ("progress_bg", "accent")
    assert look["regressione"].icon == "▲" and look["da_fare"].icon == "○"
    assert look["non_risolta"].icon == "○!" and look["in_corso"].icon == "◐"
    assert look["da_verificare"].icon == "✓?" and look["fatta"].icon == "✓"
    assert look["tollerata"].icon == "⊘" and look["rumore"].icon == "~"
    assert look["variabile"].icon == "{x}"
    for name in ("tollerata", "rumore"):
        assert (look[name].fill, look[name].edge, look[name].dash, look[name].width) == (None, "muted", True, 1.0)
    assert (look["variabile"].fill, look["variabile"].edge, look["variabile"].dash,
            look["variabile"].underline) == (None, "variable", True, True)
    assert (look["fatta"].fill, look["fatta"].edge, look["fatta"].dash,
            look["fatta"].underline) == (None, "ok", False, True)
    assert look["da_fare"].label == strings.VERDETTO_DA_FARE == "da fare"


def test_every_look_has_a_pill_tone_the_stylesheet_knows():
    qss = theme.build_qss(theme.LIGHT)
    pills = {name: vs.look_for(j).pill for name, j in STATES.items()}
    assert pills["regressione"] == "bad" and pills["in_corso"] == "progress"
    assert pills["da_fare"] == pills["non_risolta"] == "warn"
    assert pills["variabile"] == "variable" and pills["da_verificare"] == pills["fatta"] == "ok"
    for look in vs.LOOKS.values():
        assert f'pill="{look.pill}"' in qss, look.pill


def test_marked_is_a_dashed_2px_ok_edge_without_fill():
    for verdict in ("da_fare", "in_corso", "regressione"):
        look = vs.look_for(Judged(_diff(), verdict, marked=True))
        assert (look.fill, look.edge, look.dash, look.width, look.underline) == (None, "ok", True, 2.0, False)
        assert look.label == "da verificare"


def test_looks_name_existing_tokens():
    fields = {f.name for f in dataclasses.fields(theme.Tokens)}
    for look in (*vs.LOOKS.values(),):
        assert look.edge in fields
        assert look.fill is None or look.fill in fields
    assert "mark_yellow" in fields


def test_a_judged_without_verdict_that_is_not_a_class_is_neutral():
    """The AS-IS view (phase-1 comparison, no verdict) still draws something."""
    look = vs.look_for(Judged(_diff(), None))
    assert look.fill == "neutral_bg" and look.edge == "muted" and not look.dash


def _summary(**counts) -> CaseSummary:
    values = dict(version=2, fatte=0, da_fare=0, in_corso=0, regressioni=0, da_verificare=0,
                  non_risolte=0, tollerate=0, variabili=0, rumore=0, avanzamento=1.0,
                  two_way=False, when="2026-09-25T10:00:00")
    values.update(counts)
    return CaseSummary(**values)


@pytest.mark.parametrize(("counts", "expected"), [
    (dict(regressioni=1, da_fare=3, non_risolte=1, fatte=2), "regressione"),
    (dict(da_fare=3, non_risolte=1, in_corso=1), "non_risolta"),
    (dict(da_fare=2, in_corso=1, fatte=1), "da_fare"),
    (dict(in_corso=1, fatte=4), "in_corso"),
    (dict(da_fare=1, da_verificare=1, fatte=3), "da_verificare"),
    (dict(da_fare=2, da_verificare=1), "da_fare"),
    (dict(fatte=5, tollerate=2, variabili=3), "fatta"),
    (dict(tollerate=1, rumore=2), ""),
])
def test_worst_state_of_a_summary(counts, expected):
    assert vs.worst(_summary(**counts)) == expected


# -- tokens -----------------------------------------------------------------------

NEW_TOKENS = ("progress", "progress_bg", "variable", "variable_bg", "mark_yellow")


def test_new_tokens_exist_light_and_dark():
    for name in NEW_TOKENS:
        for tokens in (theme.LIGHT, theme.DARK):
            assert QColor(getattr(tokens, name)).isValid(), name


def test_dark_tokens_exist_for_every_light_token():
    for field in dataclasses.fields(theme.Tokens):
        light, dark = getattr(theme.LIGHT, field.name), getattr(theme.DARK, field.name)
        assert QColor(light).isValid() and QColor(dark).isValid(), field.name
        assert re.fullmatch(r"#[0-9A-F]{6}", light) and re.fullmatch(r"#[0-9A-F]{6}", dark)


def test_the_new_modules_have_no_hex_colour():
    for rel in ("pages/officina_verdict_style.py", "pages/officina_overlays.py",
                "strings/officina_verdetto.py"):
        text = (UI_DIR / rel).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9A-Fa-f]{6}\b", text), rel


# -- character spans (pure geometry) --------------------------------------------------

def test_a_span_inside_a_word_is_a_proportional_sub_rect():
    word = Word("12,00", 0, 100.0, 100.0, 150.0, 112.0)
    ((page, rect),) = span_boxes([word], "12,00", ((1, 4),))
    assert page == 0
    assert rect.left() == pytest.approx(110.0) and rect.right() == pytest.approx(140.0)
    assert rect.top() == pytest.approx(100.0) and rect.bottom() == pytest.approx(112.0)


def test_spans_follow_the_words_across_spaces():
    words = [Word("prezzo", 0, 10, 0, 70, 10), Word("fisso", 0, 80, 0, 130, 10)]
    boxes = span_boxes(words, "prezzo fisso", ((7, 12),))
    assert [(p, r.left(), r.right()) for p, r in boxes] == [(0, 80.0, 130.0)]
    boxes = span_boxes(words, "prezzo fisso", ((4, 9),))  # "zo fi": two partial words
    assert [(round(r.left()), round(r.right())) for _p, r in boxes] == [(50, 70), (80, 100)]


def test_a_word_not_found_in_the_text_gets_no_guessed_rect():
    words = [Word("prezzo", 0, 10, 0, 70, 10), Word("fiso", 0, 80, 0, 130, 10)]
    boxes = span_boxes(words, "prezzo fisso", ((2, 12),))  # "fiso" is not in the text
    assert [(r.left(), r.right()) for _p, r in boxes] == [(30.0, 70.0)]
    assert span_boxes([Word("zz", 0, 0, 0, 10, 10)], "abc", ((0, 1),)) == []


def test_a_span_over_the_whole_text_pinpoints_nothing():
    word = Word("Titolo", 0, 0, 0, 60, 10)
    assert span_boxes([word], "Titolo", ((0, 6),)) == []
    assert span_boxes([], "", ()) == []


# -- the viewer --------------------------------------------------------------------

@pytest.fixture
def view(qtbot, tmp_path):
    pool = QThreadPool()
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(canned_pdf("uno due tre"))
    doc_view = DocView(PageRenderer(pool))
    qtbot.addWidget(doc_view)
    doc_view.resize(700, 500)
    doc_view.show()
    doc_view.load("doc", pdf, [(612.0, 792.0)])
    yield doc_view
    pool.waitForDone(5000)


W1 = Word("12,00", 0, 100, 100, 150, 112)
W2 = Word("11,50", 0, 100, 200, 150, 212)


def _placed(state: str, diff_id: int, **changes) -> Judged:
    j = STATES[state]
    diff = dataclasses.replace(j.diff, id=diff_id, left=(W1,), right=(W2,), **changes)
    return dataclasses.replace(j, diff=diff)


def _pen(item):
    return item.pen()


def test_marked_is_drawn_dashed_2px_in_ok(view, themed):
    theme.apply(themed, theme.Mode.LIGHT)
    view.set_highlights([(_placed("da_verificare", 1), "right")])
    (item,) = view.highlight_items(1)
    pen = item.pen()
    assert pen.style() == Qt.PenStyle.DashLine and pen.widthF() == 2.0
    assert pen.color().name() == theme.LIGHT.ok.lower()
    assert item.brush().style() == Qt.BrushStyle.NoBrush


def test_on_page_colours_are_the_paper_values_in_both_themes(view, themed):
    """R13: the page is white paper in both themes: overlays keep the LIGHT values."""
    theme.apply(themed, theme.Mode.LIGHT)
    view.set_highlights([(_placed("regressione", 1), "right"), (_placed("in_corso", 2), "right")])

    def colours(i):
        item = view.highlight_items(i)[0]
        return item.brush().color().name(), item.pen().color().name(), item.pen().style()

    assert colours(1) == (theme.LIGHT.bad_bg.lower(), theme.LIGHT.bad.lower(), Qt.PenStyle.SolidLine)
    assert colours(2)[:2] == (theme.LIGHT.progress_bg.lower(), theme.LIGHT.accent.lower())
    theme.apply(themed, theme.Mode.DARK)
    assert colours(1) == (theme.LIGHT.bad_bg.lower(), theme.LIGHT.bad.lower(), Qt.PenStyle.SolidLine)
    assert colours(2)[:2] == (theme.LIGHT.progress_bg.lower(), theme.LIGHT.accent.lower())
    assert view.highlight_items(1)[0].brush().color().alpha() == 255


def test_tolerated_and_noise_are_grey_dashed_1px(view, themed):
    theme.apply(themed, theme.Mode.LIGHT)
    view.set_highlights([(_placed("tollerata", 1), "left"), (_placed("rumore", 2), "left")])
    for i in (1, 2):
        pen = view.highlight_items(i)[0].pen()
        assert pen.style() == Qt.PenStyle.DashLine and pen.widthF() == 1.0
        assert pen.color().name() == theme.LIGHT.muted.lower()


def test_a_variable_is_a_dashed_violet_underline(view, themed):
    theme.apply(themed, theme.Mode.LIGHT)
    view.set_highlights([(_placed("variabile", 1), "left")])
    (item,) = view.highlight_items(1)
    assert item.look.underline and item.pen().style() == Qt.PenStyle.DashLine
    assert item.pen().color().name() == theme.LIGHT.variable.lower()


def test_fatta_is_hidden_unless_shown_and_only_on_the_target_side(view):
    fatta = _placed("fatta", 1)
    view.set_highlights([(fatta, "left")])
    assert view.highlight_items(1) == []
    view.set_show_done(True)
    (item,) = view.highlight_items(1)
    assert item.look.underline and item.pen().style() == Qt.PenStyle.SolidLine
    view.set_highlights([(fatta, "right")])
    assert view.highlight_items(1) == [], "never on the version side"
    view.set_show_done(False)
    view.set_highlights([(fatta, "left")])
    assert view.highlight_items(1) == []


def test_changed_characters_are_yellow_sub_rects(view, themed):
    theme.apply(themed, theme.Mode.LIGHT)
    j = _placed("da_fare", 1, left_spans=((1, 4),), right_spans=((1, 3),))
    view.set_highlights([(j, "left")])
    (mark,) = view.char_marks(1)
    origin = view.page_rect(0).topLeft()
    assert mark.rect().left() == pytest.approx(origin.x() + 110.0)
    assert mark.rect().right() == pytest.approx(origin.x() + 140.0)
    assert mark.brush().color().name() == theme.LIGHT.mark_yellow.lower()
    # R14: a 2 px underline in the page's ink colour, so it shows on warn_bg too
    assert mark.pen().widthF() == 2.0 and mark.pen().color().name() == theme.LIGHT.text.lower()
    theme.apply(themed, theme.Mode.DARK)
    assert mark.brush().color().name() == theme.LIGHT.mark_yellow.lower()
    assert mark.pen().color().name() == theme.LIGHT.text.lower()
    view.set_highlights([(j, "right")])
    (mark,) = view.char_marks(1)
    assert mark.rect().right() == pytest.approx(origin.x() + 130.0)  # right_spans (1, 3)
    view.set_highlights([])
    assert view.char_marks(1) == []


def test_side_picks_the_words(view):
    j = _placed("da_fare", 5)
    view.set_highlights([(j, "left")])
    top_left = view.difference_rect(5).top()
    view.set_highlights([(j, "right")])
    assert view.difference_rect(5).top() > top_left + 50  # W2 is 100 pt lower


# -- the judge never waits for a generation (fix round 1, Important 1) ----------------

def test_judge_returns_at_once_while_the_case_is_being_generated(fake_core, tmp_path, monkeypatch):
    import threading
    import time

    from qtrequestory.ui.pages import officina_judge

    api = fake_core.officina
    ini = api.create_initiative("Banco")
    payload = tmp_path / "MOD_TEST_A.json"
    payload.write_text('{"documents": []}', encoding="utf-8")
    case = api.case_from_file(ini, payload, "MOD_TEST_A")
    started, release = threading.Event(), threading.Event()

    def slow_generate(*_args, **_kwargs):  # an HTTP call that takes its time
        started.set()
        release.wait(10)

    monkeypatch.setattr(api, "generate", slow_generate)
    judged = []
    monkeypatch.setattr(api, "compare_case", lambda *_a: judged.append(1) or "giudicato")
    worker = threading.Thread(target=officina_judge.generate_locked, args=(fake_core, ini, case, "tobe"))
    worker.start()
    try:
        assert started.wait(5)
        t0 = time.monotonic()
        assert officina_judge.judge(fake_core, ini, case, None) is None
        assert time.monotonic() - t0 < 1.0 and judged == []
    finally:
        release.set()
        worker.join(5)
    assert officina_judge.judge(fake_core, ini, case, None) == "giudicato"


def test_a_judge_waits_for_another_judge_of_the_same_case(fake_core, tmp_path, monkeypatch):
    """Two compare jobs of one case (a superseded one still running) do not
    turn each other verdict-less: the second waits for the first."""
    import threading

    from qtrequestory.ui.pages import officina_judge

    api = fake_core.officina
    first_in, release = threading.Event(), threading.Event()
    calls = []

    def compare(*_a):
        calls.append(1)
        if len(calls) == 1:
            first_in.set()
            release.wait(5)
        return "giudicato"

    monkeypatch.setattr(api, "compare_case", compare)

    class _Case:
        id, key = "caso-x", "MOD_TEST_X"

    class _Ini:
        id = "banco"

    out = []
    first = threading.Thread(target=lambda: out.append(officina_judge.judge(fake_core, _Ini, _Case, None)))
    first.start()
    assert first_in.wait(5)
    threading.Timer(0.2, release.set).start()
    assert officina_judge.judge(fake_core, _Ini, _Case, None) == "giudicato"
    first.join(5)
    assert out == ["giudicato"] and len(calls) == 2
