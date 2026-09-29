"""Palette B (D13, spec §6): the branded header, the identity amber, the new
tokens and the action roles.

The header is the app icon's blue gradient with WHITE ink: the test samples
the gradient — from the tokens and from the rendered bar — and computes the
WCAG contrast of the header text on every sample, in both modes (Review
Focus 3). The amber is an accent, never text on a light surface.
"""
from __future__ import annotations

import re

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QPushButton

from qtrequestory.ui import theme
from qtrequestory.ui.theme import DARK, LIGHT, Mode
from tests.ui.test_app_bar import ink
from tests.ui.test_theme import contrast

MODES = pytest.mark.parametrize(("mode", "tokens"), [(Mode.LIGHT, LIGHT), (Mode.DARK, DARK)],
                                ids=["light", "dark"])
#: WCAG AA: normal text / non-text (a status dot, an underline).
TEXT, UI = 4.5, 3.0


def _lerp(a: str, b: str, t: float) -> str:
    ca, cb = QColor(a), QColor(b)
    parts = (round(x + (y - x) * t) for x, y in ((ca.red(), cb.red()), (ca.green(), cb.green()),
                                                  (ca.blue(), cb.blue())))
    return "#{:02X}{:02X}{:02X}".format(*parts)


def gradient_samples(t: theme.Tokens, n: int = 201) -> list[str]:
    """``n`` evenly spaced colours of the header gradient (Qt interpolates
    the stops linearly in sRGB)."""
    stops = theme.header_stops(t)
    out = []
    for i in range(n):
        x = i / (n - 1)
        for (x0, c0), (x1, c1) in zip(stops, stops[1:]):
            if x0 <= x <= x1:
                out.append(_lerp(c0, c1, (x - x0) / (x1 - x0)))
                break
    return out


# -- tokens -----------------------------------------------------------------------

NEW = ("flag", "verify", "danger", "positive")


@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_the_new_tokens_read_on_their_soft_colour_and_on_the_surface(tokens):
    for name in NEW:
        strong, soft = getattr(tokens, name), getattr(tokens, f"{name}_bg")
        assert contrast(strong, soft) >= TEXT, name
        assert contrast(strong, tokens.surface) >= TEXT, name


def test_the_new_tokens_have_the_research_values():
    assert (LIGHT.flag, LIGHT.flag_bg, DARK.flag, DARK.flag_bg) == ("#B3400C", "#FBE4D3", "#F0975A", "#4A2A14")
    assert (LIGHT.verify, LIGHT.verify_bg, DARK.verify, DARK.verify_bg) == (
        "#0B7285", "#DDF3F6", "#4FD1DE", "#123138")
    for t in (LIGHT, DARK):  # a role, not a new colour: the same red and green as the states
        assert (t.danger, t.danger_bg, t.positive, t.positive_bg) == (t.bad, t.bad_bg, t.ok, t.ok_bg)


def test_the_identity_amber_is_the_icon_amber():
    assert LIGHT.identity == DARK.identity == "#FFC857"
    assert contrast(LIGHT.identity, LIGHT.surface) < TEXT, "why it is never text on light"


# -- the header gradient ----------------------------------------------------------------

@MODES
def test_header_ink_is_white_and_readable_on_every_point_of_the_gradient(mode, tokens):
    assert tokens.on_header == "#FFFFFF"
    samples = gradient_samples(tokens)
    assert samples[0] == tokens.header_start and samples[-1] == tokens.header_end
    worst = min(contrast(tokens.on_header, c) for c in samples)
    assert worst >= TEXT, worst
    assert min(contrast(tokens.on_header_muted, c) for c in samples) >= TEXT
    # the raised chip / hover on the header carries the same white text
    assert contrast(tokens.on_header, tokens.header_raise) >= TEXT
    assert contrast(tokens.on_header_muted, tokens.header_raise) >= TEXT
    # status dots and the active tab underline: non-text, on the bar and on the chip
    for ink in (tokens.identity, tokens.header_ok, tokens.header_bad, tokens.on_header_muted):
        for bg in (*samples, tokens.header_raise):
            assert contrast(ink, bg) >= UI, (ink, bg)


def test_the_light_header_starts_darker_than_the_icon_light_pole():
    """D13: #2B8AE0 with white is only ~3.6:1 — the light stop is darkened."""
    assert contrast("#FFFFFF", "#2B8AE0") < TEXT
    assert LIGHT.header_start != "#2B8AE0"
    assert LIGHT.header_end == "#0B4F94"


@MODES
def test_the_rendered_header_meets_the_contrast_everywhere(qtbot, themed, mode, tokens):
    """The bar as Qt paints it: every column of its background (above the
    tabs) is a blue on which white reads at >= 4.5:1."""
    from qtrequestory.ui.app_bar import AppBar

    theme.apply(themed, mode)
    bar = AppBar()
    qtbot.addWidget(bar)
    bar.resize(1366, 46)
    bar.show()
    qtbot.waitExposed(bar)
    image = bar.grab().toImage()
    ratio = image.width() / bar.width()
    columns = range(0, image.width(), max(1, image.width() // 300))
    samples = [image.pixelColor(x, int(1 * ratio)).name().upper() for x in columns]
    assert all(contrast(tokens.on_header, c) >= TEXT for c in samples), min(
        samples, key=lambda c: contrast(tokens.on_header, c))
    assert contrast(samples[0], tokens.header_start) < 1.1, "a gradient from the start stop"
    assert contrast(samples[-1], tokens.header_end) < 1.1, "... to the end stop"


@MODES
def test_the_app_name_on_the_header_is_white(qtbot, themed, mode, tokens):
    from PySide6.QtGui import QPalette

    from qtrequestory.ui.app_bar import AppBar

    theme.apply(themed, mode)
    bar = AppBar()
    tab = bar.add_tab("search", "Ricerca", "search")
    icon = bar.add_icon_button("settings", "settings", "Impostazioni")
    qtbot.addWidget(bar)
    bar.show()
    bar.brand_label.ensurePolished()
    assert bar.brand_label.palette().color(QPalette.ColorRole.WindowText).name().upper() == tokens.on_header
    for button in (tab, icon):  # the glyphs are white too
        assert ink(button.icon()) == tokens.on_header


def test_the_active_tab_is_underlined_in_amber():
    qss = theme.build_qss(LIGHT)
    rule = re.search(r'QPushButton\[tab="true"\]:checked\s*\{([^}]*)\}', qss)
    assert rule and f"solid {LIGHT.identity}" in rule.group(1)


@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_the_amber_is_never_text_off_the_header(tokens):
    """Every rule that paints text in the amber is inside the (dark blue) header."""
    qss = theme.build_qss(tokens)
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", qss):
        if re.search(rf"(?<![-\w])color:\s*{tokens.identity}", body):
            for part in selector.split(","):
                assert "#appBar" in part, part.strip()


@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_the_preview_panes_tabs_are_not_header_white(tokens):
    """``[tab="pane"]`` (the preview pane's JSON/Dettagli, review round 1) must not reuse
    ``on_header`` — it sits on the plain page background, not the blue gradient, so a
    checked-white / unchecked-near-white pair there is unreadable, not just off-brand."""
    qss = theme.build_qss(tokens)
    rest = re.search(r'QPushButton\[tab="pane"\]\s*\{([^}]*)\}', qss)
    checked = re.search(r'QPushButton\[tab="pane"\]:checked\s*\{([^}]*)\}', qss)
    assert rest and f"color: {tokens.muted}" in rest.group(1)
    assert checked and f"color: {tokens.text}" in checked.group(1)
    assert tokens.muted != tokens.on_header
    assert tokens.text != tokens.on_header
    # The row sits directly on the page background (no card behind it).
    assert contrast(tokens.muted, tokens.bg) >= TEXT
    assert contrast(tokens.text, tokens.bg) >= TEXT


# -- action roles ------------------------------------------------------------------------

@pytest.mark.parametrize(("role", "token"), [("danger", "danger"), ("positive", "positive")])
def test_the_action_roles_have_their_colours(role, token):
    qss = theme.build_qss(LIGHT)
    rule = re.search(rf'QPushButton\[role="{role}"\]\s*\{{([^}}]*)\}}', qss)
    assert rule, role
    assert getattr(LIGHT, token) in rule.group(1) and getattr(LIGHT, f"{token}_bg") in rule.group(1)
    assert f'QPushButton[role="{role}"]:disabled' in qss


@MODES
def test_a_danger_button_is_painted_red(qtbot, themed, mode, tokens):
    from PySide6.QtGui import QPalette

    theme.apply(themed, mode)
    button = QPushButton("Elimina")
    qtbot.addWidget(button)
    theme.set_role(button, "danger")
    button.ensurePolished()
    assert button.palette().color(QPalette.ColorRole.ButtonText).name().upper() == tokens.danger


def test_delete_and_add_buttons_carry_their_roles(qtbot):
    from qtrequestory.ui.import_result import ResultView
    from qtrequestory.ui.pages.officina_board import Board

    result, board = ResultView(), Board()
    qtbot.addWidget(result)
    qtbot.addWidget(board)
    assert result.delete_button.property("role") == "danger"
    assert board.add_search_button.property("role") == "positive"
