"""The application theme: tokens, palette, generated QSS and the saved mode.

What is tested is the contract the pages build on — every text colour is
readable against the surface it sits on (WCAG contrast, computed here), the
style is Fusion painted from the tokens, the mode survives a restart, and the
QSS covers every role the pages set. The hues themselves are taste and are not
asserted beyond that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette

from qtrequestory.ui import icons, theme
from qtrequestory.ui.actions import user_settings
from qtrequestory.ui.theme import DARK, LIGHT, Mode

UI_DIR = Path(theme.__file__).parent


# ------------------------------------------------------------------ contrast ---

def _luminance(hex_colour: str) -> float:
    colour = QColor(hex_colour)
    channels = []
    for value in (colour.redF(), colour.greenF(), colour.blueF()):
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.x contrast ratio between two ``#RRGGBB`` colours."""
    light, dark = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_the_contrast_helper_matches_the_known_extremes():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#777777") == pytest.approx(1.0)


@pytest.mark.parametrize("tokens", [LIGHT, DARK], ids=["light", "dark"])
def test_text_tokens_meet_contrast(tokens):
    for surface in (tokens.bg, tokens.surface, tokens.surface2):
        assert contrast(tokens.text, surface) >= 7, surface
    assert contrast(tokens.muted, tokens.surface) >= 4.5
    for fg, bg in ((tokens.ok, tokens.ok_bg), (tokens.warn, tokens.warn_bg),
                   (tokens.bad, tokens.bad_bg), (tokens.muted, tokens.neutral_bg)):
        assert contrast(fg, bg) >= 4.5, (fg, bg)
    assert contrast(tokens.on_accent, tokens.accent) >= 4.5
    assert contrast(tokens.selection_text, tokens.selection) >= 7


def test_the_accent_is_the_brand_blue_in_light_mode():
    assert LIGHT.accent == "#0F6CBD"


def test_the_spacing_scale():
    assert theme.SPACE == (4, 8, 12, 16, 24)


# ------------------------------------------------------------------- apply ---

def test_apply_uses_fusion_and_palette(themed):
    theme.apply(themed, Mode.LIGHT)

    palette = themed.palette()
    assert palette.window().color().name().upper() == LIGHT.bg
    assert palette.color(QPalette.ColorRole.Base).name().upper() == LIGHT.surface
    assert palette.color(QPalette.ColorRole.Highlight).name().upper() == LIGHT.selection
    assert themed.styleSheet() == theme.build_qss(LIGHT)
    assert theme.tokens() is LIGHT
    # With an application stylesheet ``style()`` is Qt's stylesheet wrapper,
    # whose name() is empty; the style underneath shows once the sheet is off.
    themed.setStyleSheet("")
    assert themed.style().name().lower() == "fusion"


@pytest.fixture
def requested_schemes(monkeypatch):
    """What ``apply`` asks ``QStyleHints.setColorScheme`` for.

    The offscreen platform ignores the request, so the call itself is recorded.
    """
    from PySide6.QtGui import QStyleHints

    calls: list[Qt.ColorScheme] = []
    monkeypatch.setattr(QStyleHints, "setColorScheme", lambda self, scheme: calls.append(scheme))
    return calls


def test_apply_dark_switches_every_derived_thing(themed, requested_schemes):
    theme.apply(themed, Mode.DARK)

    assert themed.palette().window().color().name().upper() == DARK.bg
    assert themed.styleSheet() == theme.build_qss(DARK)
    assert theme.tokens() is DARK
    assert requested_schemes == [Qt.ColorScheme.Dark], "native title bars follow"


def test_system_mode_hands_the_scheme_back_to_the_desktop(themed, requested_schemes):
    theme.apply(themed, Mode.SYSTEM)
    assert requested_schemes == [Qt.ColorScheme.Unknown]


def test_apply_without_a_mode_uses_the_saved_one(themed):
    theme.save_mode(Mode.DARK)
    theme.apply(themed)
    assert theme.tokens() is DARK


def test_system_mode_follows_the_style_hint(themed):
    hints = themed.styleHints()
    scheme = theme.resolved_scheme(Mode.SYSTEM)
    assert scheme in (Qt.ColorScheme.Light, Qt.ColorScheme.Dark)
    assert theme.resolved_scheme(Mode.LIGHT) == Qt.ColorScheme.Light
    assert theme.resolved_scheme(Mode.DARK) == Qt.ColorScheme.Dark

    theme.apply(themed, Mode.SYSTEM)
    expected = DARK if hints.colorScheme() == Qt.ColorScheme.Dark else LIGHT
    assert theme.tokens() is expected


def test_apply_emits_changed_and_clears_icon_cache(themed, qtbot, monkeypatch):
    cleared: list[bool] = []
    monkeypatch.setattr(icons, "clear_cache", lambda: cleared.append(True))

    with qtbot.waitSignal(theme.signals.changed, timeout=1000):
        theme.apply(themed, Mode.LIGHT)
    assert cleared


# -------------------------------------------------------------------- mode ---

def test_mode_is_persisted():
    theme.save_mode(Mode.DARK)
    assert theme.saved_mode() is Mode.DARK
    assert user_settings().value(theme.MODE_SETTING) == "dark"


def test_an_unknown_stored_mode_falls_back_to_system():
    user_settings().setValue(theme.MODE_SETTING, "fucsia")
    assert theme.saved_mode() is Mode.SYSTEM


def test_nothing_stored_means_system():
    assert theme.saved_mode() is Mode.SYSTEM


# --------------------------------------------------------------------- QSS ---

def test_build_qss_mentions_every_role():
    qss = theme.build_qss(LIGHT)
    for needle in ('role="pageTitle"', 'role="section"', 'role="muted"', 'role="card"',
                   'role="primary"', 'role="icon"', 'pill="ok"', 'pill="warn"', 'pill="bad"',
                   'pill="neutral"', 'segment="true"', 'tab="true"', "#appBar",
                   "QHeaderView::section", "QProgressBar::chunk", "QToolTip", "QMenu::item",
                   "QScrollBar"):
        assert needle in qss, needle
    assert LIGHT.accent in qss
    assert theme.build_qss(DARK) != qss


def test_the_checked_segment_is_a_selection_band_not_an_accent_fill():
    qss = theme.build_qss(LIGHT)
    rule = re.search(r'QPushButton\[segment="true"\]:checked\s*\{([^}]*)\}', qss)
    assert rule, "segmented buttons need a checked state"
    body = rule.group(1)
    assert LIGHT.selection in body
    assert f"background: {LIGHT.accent}" not in body


def test_set_role_sets_the_property_and_repolishes(themed, qtbot):
    from PySide6.QtWidgets import QLabel

    theme.apply(themed, Mode.LIGHT)
    label = QLabel("Titolo")
    qtbot.addWidget(label)
    before = label.font().pointSizeF()

    theme.set_role(label, "pageTitle")

    assert label.property("role") == "pageTitle"
    label.ensurePolished()
    assert label.font().pointSizeF() > before


# -------------------------------------------------------------------- font ---

def test_mono_font_asks_for_cascadia_then_consolas(qapp):
    font = theme.mono_font()
    assert font.families()[:2] == ["Cascadia Mono", "Consolas"]
    assert font.styleHint() == QFont.StyleHint.TypeWriter
    assert theme.mono_font(11).pointSizeF() == pytest.approx(11)


# ------------------------------------------------------------ no literals ---

def test_no_module_hardcodes_colours():
    offenders = []
    for path in UI_DIR.rglob("*.py"):
        if path.name == "theme.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"#[0-9A-Fa-f]{6}\b", line):
                offenders.append(f"{path.relative_to(UI_DIR)}:{number}: {line.strip()}")
    assert offenders == []


def test_no_module_uses_the_mid_role_or_the_system_fixed_font():
    offenders = []
    for path in UI_DIR.rglob("*.py"):
        if path.name == "theme.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("ColorRole.Mid", "SystemFont.FixedFont", "setStyleSheet("):
            if needle in text:
                offenders.append(f"{path.relative_to(UI_DIR)}: {needle}")
    assert offenders == []


# --------------------------------------------------------- widgets fit ---

def test_segmented_period_buttons_do_not_clip_their_text(themed, qtbot):
    """The checked segment is bold: its width must be computed for bold text."""
    from qtrequestory.ui.pages.search_form import SearchForm

    theme.apply(themed, Mode.LIGHT)
    form = SearchForm()
    qtbot.addWidget(form)
    form.show()
    qtbot.waitExposed(form)
    for button in form.period_group.buttons():
        assert button.property("segment") is True
        bold = QFont(button.font())
        bold.setWeight(QFont.Weight.DemiBold)
        needed = QFontMetrics(bold).horizontalAdvance(button.text())
        assert button.width() >= needed + 16, button.text()


def assert_tinted(icon, expected: str) -> None:
    image = icon.pixmap(20, 20).toImage()
    target = QColor(expected)
    opaque = [
        QColor(image.pixelColor(x, y))
        for x in range(image.width()) for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 200
    ]
    assert opaque, "the glyph must have visible pixels"
    for colour in opaque:
        assert abs(colour.red() - target.red()) <= 2, colour.name()
        assert abs(colour.green() - target.green()) <= 2, colour.name()
        assert abs(colour.blue() - target.blue()) <= 2, colour.name()


def test_icons_are_tinted_with_the_theme_text_colour(themed):
    theme.apply(themed, Mode.DARK)
    assert_tinted(icons.icon("search"), DARK.text)


def test_icons_accept_a_token_colour_string(themed):
    theme.apply(themed, Mode.LIGHT)
    assert_tinted(icons.icon("search", color=LIGHT.muted), LIGHT.muted)


def test_the_arrow_images_the_stylesheet_points_at_exist():
    """Restyled combo/spin/check boxes lose Qt's glyphs: the QSS supplies its own."""
    urls = re.findall(r"url\(([^)]+)\)", theme.build_qss(DARK))
    assert len(set(urls)) == 3
    for url in urls:
        assert Path(url).is_file(), url
        colour = "#" + Path(url).stem.rsplit("-", 1)[1]
        assert colour.upper() in (DARK.muted, DARK.on_accent), "glyphs are token-coloured"


@pytest.fixture
def glyph_dir(tmp_path, monkeypatch):
    """``theme_qss.glyph`` writing into a private temp folder."""
    from qtrequestory.ui import theme_qss

    monkeypatch.setattr(theme_qss.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(theme_qss, "_warned", False)
    return tmp_path / "qtrequestory-theme"


@pytest.mark.parametrize("garbage", [b"", b"<svg", b"\x00\xff not an svg"])
def test_an_existing_empty_or_garbage_glyph_file_is_rewritten(glyph_dir, garbage):
    """A file left half-written by a crash (or by another process) must not
    stick: the name alone does not prove the content."""
    from qtrequestory.ui import theme_qss

    glyph_dir.mkdir()
    target = glyph_dir / "check-ffffff.svg"
    target.write_bytes(garbage)

    path = Path(theme_qss.glyph("check", "#FFFFFF"))

    assert path == target
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<svg") and text.endswith("</svg>") and "#FFFFFF" in text
    assert [p.name for p in glyph_dir.iterdir()] == ["check-ffffff.svg"], "no temp file left"


def test_a_glyph_that_cannot_be_written_warns_once(glyph_dir, monkeypatch, caplog):
    from qtrequestory.ui import theme_qss

    def refuse(*_args, **_kw):
        raise PermissionError("in uso")

    monkeypatch.setattr(theme_qss.os, "replace", refuse)
    with caplog.at_level("WARNING", logger="qtrequestory.ui.theme_qss"):
        theme_qss.glyph("check", "#FFFFFF")
        theme_qss.glyph("chevron-up", "#000000")
    assert len(caplog.records) == 1
    assert [p for p in glyph_dir.iterdir()] == [], "the temp file is cleaned up"


def test_no_temp_folder_is_not_fatal(monkeypatch, caplog):
    from qtrequestory.ui import theme_qss

    def boom():
        raise OSError("nessuna cartella temporanea")

    monkeypatch.setattr(theme_qss.tempfile, "gettempdir", boom)
    monkeypatch.setattr(theme_qss, "_warned", False)
    with caplog.at_level("WARNING", logger="qtrequestory.ui.theme_qss"):
        assert isinstance(theme_qss.glyph("check", "#FFFFFF"), str)
    assert len(caplog.records) == 1


def test_the_shell_widgets_have_their_rules():
    qss = theme.build_qss(LIGHT)
    for needle in ("QPushButton#statusChip", 'QLabel[dot="ok"]', 'QLabel[dot="warn"]',
                   'QLabel[dot="neutral"]', "QFrame#toast", 'QPushButton[role="icon"]:checked'):
        assert needle in qss, needle


def test_data_tables_get_the_flat_look(qtbot):
    from PySide6.QtWidgets import QTableView

    view = QTableView()
    qtbot.addWidget(view)
    theme.set_table_look(view)
    assert not view.showGrid()
    assert view.horizontalHeader().defaultAlignment() & Qt.AlignmentFlag.AlignLeft


def test_the_stacked_banners_share_the_spacing_scale(qtbot, fake_core, runner):
    """Final review M5: the three banners of Ricerca line up on theme.SPACE."""
    from qtrequestory.ui import theme as theme_mod
    from qtrequestory.ui.pages.import_banner import ImportBanner
    from qtrequestory.ui.pages.mirror_banner import MirrorRootBanner
    from qtrequestory.ui.pages.search_meta import GapBanner

    expected = (theme_mod.SPACE[2], theme_mod.SPACE[0], theme_mod.SPACE[1], theme_mod.SPACE[0])
    for banner in (ImportBanner(fake_core, runner, None), MirrorRootBanner(fake_core, None), GapBanner()):
        qtbot.addWidget(banner)
        m = banner.layout().contentsMargins()
        assert (m.left(), m.top(), m.right(), m.bottom()) == expected, type(banner).__name__
