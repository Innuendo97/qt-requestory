"""The application theme: one token table, three things derived from it.

Every colour the UI shows comes from a :class:`Tokens` instance — ``LIGHT`` or
``DARK`` — and reaches the widgets through exactly three channels, all built by
:func:`apply` from the same tokens so they can never disagree:

* the **Fusion** style with a ``QPalette`` filled from the tokens. Fusion is
  the one built-in style that paints everything from the palette; the native
  ``windows11`` style takes its accent from Windows (teal on some machines),
  paints a selected table row as one pill per cell and ignores most of the
  palette in dark mode;
* an application **stylesheet** (:func:`build_qss`, template in ``theme_qss``)
  for what a palette cannot express: radii, the primary button, pills,
  segmented buttons, tabs, a quiet table header, slim scroll bars. Widgets opt into a look with a dynamic
  property — ``set_role(label, "pageTitle")``, ``label.setProperty("pill",
  "warn")`` — so no module outside this one writes a colour or a stylesheet;
* :func:`tokens`, for the few things that paint themselves (icon tint, JSON
  highlighter), which re-derive on :data:`signals` ``.changed``.

The accent is fixed (``#0F6CBD``, the app icon's blue) and does not follow the
Windows accent colour. Palette B (D13): the app bar is the icon's blue
gradient (``header_*``, :func:`header_stops`) with white ink at >= 4.5:1 on
every point, and the icon's amber (``identity``) is an accent there — the
active tab, the sync attention dot — never text on a light surface. The *mode* — Sistema / Chiaro / Scuro — is the user's,
stored under :data:`MODE_SETTING`. In ``SYSTEM`` mode the theme follows the
desktop and re-applies itself when Windows switches between light and dark.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import Enum

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QAbstractButton, QApplication, QStyleFactory, QTableView, QWidget

from qtrequestory.ui import icons, theme_qss

__all__ = [
    "DARK", "HEADER_STOPS", "LIGHT", "MODE_SETTING", "SPACE", "Mode", "ThemeSignals", "Tokens",
    "apply", "build_palette", "build_qss", "header_stops", "mono_font", "repolish", "reset", "resolved_scheme", "save_mode",
    "saved_mode", "set_role", "set_segmented", "set_table_look", "signals", "tokens",
]

log = logging.getLogger(__name__)


class Mode(str, Enum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


#: QSettings key (through ``actions.user_settings()``) of the chosen mode.
MODE_SETTING = "ui/theme"

#: The spacing scale, in pixels: margins and gaps use these and nothing else.
SPACE = (4, 8, 12, 16, 24)

#: The UI font; Qt falls through the list (Segoe UI Variable is Windows 11 only).
UI_FAMILIES = ("Segoe UI Variable Text", "Segoe UI")
#: The code font of the JSON preview and the logs.
MONO_FAMILIES = ("Cascadia Mono", "Consolas")

#: Horizontal padding of a segmented button, per side (also in the QSS).
SEGMENT_PADDING = 12

#: Positions of ``header_start`` / ``header_mid`` / ``header_end`` on the app bar.
HEADER_STOPS = (0.0, 0.55, 1.0)


@dataclass(frozen=True)
class Tokens:
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    on_accent: str
    selection: str
    selection_text: str
    ok: str
    ok_bg: str
    warn: str
    warn_bg: str
    bad: str
    bad_bg: str
    neutral_bg: str
    #: Officina phase 2: "in corso" and the progress bar (strong / soft).
    progress: str
    progress_bg: str
    #: Officina phase 2: variables recognised in the target (strong / soft).
    variable: str
    variable_bg: str
    #: Officina phase 2: the changed characters inside a word — a bright fill under
    #: dark ink in BOTH modes (the page is always white; a chip carries dark text).
    mark_yellow: str
    #: The drop shadow of floating chrome (the Officina mini-bar); its alpha is per mode there.
    shadow: str
    code_key: str
    code_string: str
    code_number: str
    code_literal: str
    #: Palette B: "non risolta" (vermilion) and "da verificare" (cyan), strong / soft.
    flag: str
    flag_bg: str
    verify: str
    verify_bg: str
    #: Action roles (QSS ``role="danger"`` / ``"positive"``): the red and green of the
    #: states, named for what the button does (elimina / aggiungi).
    danger: str
    danger_bg: str
    positive: str
    positive_bg: str
    #: The app bar: the icon's blue gradient, a raised chip on it, white ink.
    header_start: str
    header_mid: str
    header_end: str
    header_raise: str
    on_header: str
    on_header_muted: str
    #: The icon's amber: identity accents on the header only, never text on light.
    identity: str
    header_ok: str
    header_bad: str


LIGHT = Tokens(
    bg="#F3F4F6", surface="#FFFFFF", surface2="#F8F9FB", border="#E1E4E8",
    text="#1B1F24", muted="#5F6B78",
    accent="#0F6CBD", accent_hover="#115EA3", on_accent="#FFFFFF",
    selection="#DCEBFA", selection_text="#1B1F24",
    ok="#0E7A0D", ok_bg="#DFF6DD", warn="#8A5300", warn_bg="#FFF4CE",
    bad="#B42318", bad_bg="#FDE7E4", neutral_bg="#EDEFF2",
    progress="#0F6CBD", progress_bg="#E6F0FB", variable="#6B5BB5", variable_bg="#EEEBFA",
    mark_yellow="#FFD24D", shadow="#000000",
    code_key="#0B5CAD", code_string="#A31515", code_number="#0E7A0D", code_literal="#8250DF",
    flag="#B3400C", flag_bg="#FBE4D3", verify="#0B7285", verify_bg="#DDF3F6",
    danger="#B42318", danger_bg="#FDE7E4", positive="#0E7A0D", positive_bg="#DFF6DD",
    header_start="#1766B8", header_mid="#115AA6", header_end="#0B4F94", header_raise="#2A6AAD",
    on_header="#FFFFFF", on_header_muted="#E3EEFA",
    identity="#FFC857", header_ok="#A8F0A0", header_bad="#FFC2B8",
)

DARK = Tokens(
    bg="#1C1F24", surface="#24282E", surface2="#282C33", border="#363C45",
    text="#EEF1F4", muted="#A3ACB7",
    accent="#4CA0E0", accent_hover="#6BB3E8", on_accent="#0B1520",
    selection="#1F4468", selection_text="#EEF1F4",
    ok="#6CCB5F", ok_bg="#1F3A1D", warn="#F2C661", warn_bg="#433519",
    bad="#FF8A7A", bad_bg="#4A1F1A", neutral_bg="#3A3F47",
    progress="#6BB3E8", progress_bg="#1B3A5C", variable="#B8A9F5", variable_bg="#2F2A4D",
    mark_yellow="#E8C04A", shadow="#000000",
    code_key="#8CC4F2", code_string="#E9A27A", code_number="#9BD48F", code_literal="#C4A7F5",
    flag="#F0975A", flag_bg="#4A2A14", verify="#4FD1DE", verify_bg="#123138",
    danger="#FF8A7A", danger_bg="#4A1F1A", positive="#6CCB5F", positive_bg="#1F3A1D",
    header_start="#1B5FA3", header_mid="#124A86", header_end="#0A3A6E", header_raise="#23609E",
    on_header="#FFFFFF", on_header_muted="#E3EEFA",
    identity="#FFC857", header_ok="#A8F0A0", header_bad="#FFC2B8",
)


class ThemeSignals(QObject):
    changed = Signal()  # after every apply()


_signals: ThemeSignals | None = None
_applied: Tokens | None = None
_mode: Mode | None = None
_applying = False
_following_system = False


def __getattr__(name: str) -> object:
    """``theme.signals`` — created on first use, not at import time."""
    if name == "signals":
        global _signals
        if _signals is None:
            _signals = ThemeSignals()
        return _signals
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# -- mode ---------------------------------------------------------------------

def saved_mode() -> Mode:
    """The stored mode; ``SYSTEM`` when nothing (or something unknown) is stored."""
    from qtrequestory.ui.actions import user_settings  # actions imports widgets

    value = str(user_settings().value(MODE_SETTING, Mode.SYSTEM.value))
    try:
        return Mode(value)
    except ValueError:
        log.debug("tema sconosciuto nelle impostazioni: %r", value)
        return Mode.SYSTEM


def save_mode(mode: Mode) -> None:
    from qtrequestory.ui.actions import user_settings

    user_settings().setValue(MODE_SETTING, Mode(mode).value)


def resolved_scheme(mode: Mode) -> Qt.ColorScheme:
    """``LIGHT``/``DARK`` as they are; ``SYSTEM`` asks the style hints.

    A desktop that says nothing (``Unknown``: offscreen, old Windows) is light.
    """
    if mode is Mode.LIGHT:
        return Qt.ColorScheme.Light
    if mode is Mode.DARK:
        return Qt.ColorScheme.Dark
    hints = QGuiApplication.styleHints()
    if hints is not None and hints.colorScheme() == Qt.ColorScheme.Dark:
        return Qt.ColorScheme.Dark
    return Qt.ColorScheme.Light


def tokens() -> Tokens:
    """The tokens of the applied theme (before any ``apply``: the desktop's)."""
    if _applied is not None:
        return _applied
    return DARK if resolved_scheme(Mode.SYSTEM) == Qt.ColorScheme.Dark else LIGHT


# -- apply --------------------------------------------------------------------

def apply(app: QApplication, mode: Mode | None = None) -> None:
    """Style, palette, stylesheet and scheme hint for ``mode`` (default: saved)."""
    global _applied, _mode, _applying
    mode = saved_mode() if mode is None else Mode(mode)
    _applying = True
    try:
        _request_scheme(app, mode)
        chosen = DARK if resolved_scheme(mode) == Qt.ColorScheme.Dark else LIGHT
        _mode, _applied = mode, chosen
        if not _is_fusion(app):
            app.setStyle(QStyleFactory.create("Fusion"))
        font = QFont(app.font())
        rest = [f for f in (font.families() or [font.family()]) if f not in UI_FAMILIES]
        font.setFamilies([*UI_FAMILIES, *rest])
        app.setFont(font)
        app.setPalette(build_palette(chosen))
        app.setStyleSheet(build_qss(chosen))
        icons.clear_cache()
        _follow_system(app)
    finally:
        _applying = False
    __getattr__("signals").changed.emit()


def _is_fusion(app: QApplication) -> bool:
    """Fusion already set — directly, or under the stylesheet a previous
    ``apply`` installed (Qt's stylesheet wrapper has an empty ``name()``; only
    this module sets an application stylesheet)."""
    style = app.style()
    if style.name().lower() == "fusion":
        return True
    return style.metaObject().className() == "QStyleSheetStyle" and bool(app.styleSheet())


def reset() -> None:
    """Forget the applied theme (tests put the application back themselves)."""
    global _applied, _mode
    _applied, _mode = None, None


def _request_scheme(app: QApplication, mode: Mode) -> None:
    """Tell Qt (and so the native title bar) which scheme the window is in."""
    hints = app.styleHints()
    if not hasattr(hints, "setColorScheme"):  # pragma: no cover - Qt < 6.8
        return
    hints.setColorScheme({
        Mode.LIGHT: Qt.ColorScheme.Light,
        Mode.DARK: Qt.ColorScheme.Dark,
    }.get(mode, Qt.ColorScheme.Unknown))


def _follow_system(app: QApplication) -> None:
    """In ``SYSTEM`` mode, re-apply when the desktop switches light/dark."""
    global _following_system
    if _following_system:
        return
    app.styleHints().colorSchemeChanged.connect(_on_scheme_changed)
    _following_system = True


def _on_scheme_changed(_scheme: object) -> None:
    app = QApplication.instance()
    if _applying or _mode is not Mode.SYSTEM or app is None:
        return
    apply(app, Mode.SYSTEM)


def build_palette(t: Tokens) -> QPalette:
    palette = QPalette()
    roles = QPalette.ColorRole
    for role, value in (
        (roles.Window, t.bg), (roles.WindowText, t.text),
        (roles.Base, t.surface), (roles.AlternateBase, t.surface2),
        (roles.Text, t.text), (roles.BrightText, t.text), (roles.PlaceholderText, t.muted),
        (roles.Button, t.surface), (roles.ButtonText, t.text),
        (roles.Highlight, t.selection), (roles.HighlightedText, t.selection_text),
        (roles.ToolTipBase, t.surface), (roles.ToolTipText, t.text),
        (roles.Link, t.accent), (roles.LinkVisited, t.accent), (roles.Accent, t.accent),
        (roles.Light, t.surface), (roles.Midlight, t.surface2), (roles.Mid, t.border),
        (roles.Dark, t.border), (roles.Shadow, t.border),
    ):
        palette.setColor(role, QColor(value))
    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText):
        palette.setColor(disabled, role, QColor(t.muted))
    palette.setColor(disabled, roles.Button, QColor(t.bg))
    return palette


# -- widget helpers -----------------------------------------------------------

def set_role(widget: QWidget, role: str) -> None:
    """Give ``widget`` one of the QSS roles and restyle it now."""
    widget.setProperty("role", role)
    repolish(widget)


def bold_min_width(widget: QWidget, label: str, chrome_px: int) -> int:
    """``label``'s width at DemiBold plus ``chrome_px``: a checked tab or
    segment turns bold via QSS, but Qt sizes it for the regular weight."""
    bold = QFont(widget.font())
    bold.setWeight(QFont.Weight.DemiBold)
    return QFontMetrics(bold).horizontalAdvance(label) + chrome_px


def set_segmented(buttons: Sequence[QAbstractButton]) -> None:
    """Turn a row of checkable buttons into one segmented control.

    The layout holding them must have ``spacing 0``. The checked segment is
    drawn semibold, but Qt sizes a widget for its *unchecked* font, so each
    segment is given a minimum width that fits its label in semibold — without
    it the checked label is clipped at both ends.
    """
    last = len(buttons) - 1
    for index, button in enumerate(buttons):
        button.setProperty("segment", True)
        button.setProperty("segpos", "first" if index == 0 else "last" if index == last else "mid")
        needed = bold_min_width(button, button.text(), 2 * SEGMENT_PADDING + 2)
        button.setMinimumWidth(max(button.minimumWidth(), needed))
        repolish(button)


def set_table_look(view: QTableView) -> None:
    """The flat data-table look: no grid, left-aligned quiet header.

    What QSS cannot say: the grid is a view flag, the header alignment a
    header property, and a highlighted section would turn the header of the
    selected cell's column bold on every click.
    """
    view.setShowGrid(False)
    header = view.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setHighlightSections(False)


def mono_font(point_size: float | None = None) -> QFont:
    """Cascadia Mono, else Consolas, else whatever this system calls fixed.

    The families are a *list*, not probed against ``QFontDatabase.families()``:
    Qt falls through them itself, which also works where the database is empty
    (a headless test run).
    """
    fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font = QFont(fixed)
    font.setFamilies([*MONO_FAMILIES, fixed.family()])
    font.setStyleHint(QFont.StyleHint.TypeWriter)
    size = point_size if point_size is not None else QGuiApplication.font().pointSizeF()
    if size > 0:
        font.setPointSizeF(size)
    return font


def repolish(widget: QWidget) -> None:
    """Re-evaluate the stylesheet after a dynamic property changed."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


# -- stylesheet ---------------------------------------------------------------

def header_stops(t: Tokens) -> tuple[tuple[float, str], ...]:
    """``((position, colour), ...)`` of the app bar gradient (left to right)."""
    return tuple(zip(HEADER_STOPS, (t.header_start, t.header_mid, t.header_end)))


def build_qss(t: Tokens) -> str:
    """The application stylesheet for ``t``: every role the pages may set."""
    return theme_qss.QSS.format(
        seg_pad=SEGMENT_PADDING,
        header_gradient=", ".join(f"stop:{x} {c}" for x, c in header_stops(t)),
        arrow_down=theme_qss.glyph("chevron-down", t.muted),
        arrow_up=theme_qss.glyph("chevron-up", t.muted),
        check=theme_qss.glyph("check", t.on_accent),
        **asdict(t),
    )
