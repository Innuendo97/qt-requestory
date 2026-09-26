"""The application stylesheet template of :mod:`qtrequestory.ui.theme`.

Kept apart only for size: ``theme.build_qss`` is the public entry point and
the only caller. Every colour here is a ``{token}`` placeholder filled from a
``theme.Tokens``; the one thing QSS cannot express — a tinted image for the
arrows and ticks of restyled combo, spin and check boxes — is written as tiny
SVG files by :func:`glyph`.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

__all__ = ["QSS", "glyph"]

log = logging.getLogger(__name__)

QSS = """
QMainWindow, QDialog, QWizard {{ background: {bg}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border};
    border-radius: 4px; padding: 4px 8px; }}

QLabel[role="pageTitle"] {{ font-size: 15pt; font-weight: 600; }}
QLabel[role="section"] {{ font-size: 10.5pt; font-weight: 600; }}
QLabel[role="muted"] {{ color: {muted}; }}
QLabel[pill] {{ border-radius: 9px; padding: 1px 8px; font-weight: 600; }}
QLabel[pill="ok"] {{ background: {ok_bg}; color: {ok}; }}
QLabel[pill="warn"] {{ background: {warn_bg}; color: {warn}; }}
QLabel[pill="bad"] {{ background: {bad_bg}; color: {bad}; }}
QLabel[pill="neutral"] {{ background: {neutral_bg}; color: {muted}; }}
QLabel[pill="progress"] {{ background: {progress_bg}; color: {progress}; }}
QLabel[pill="variable"] {{ background: {variable_bg}; color: {variable}; }}

QFrame[role="card"] {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; }}

QWidget#appBar {{ background: {surface}; border-bottom: 1px solid {border}; }}
QPushButton[tab="true"] {{ background: transparent; border: none; border-radius: 0;
    border-bottom: 3px solid transparent; color: {muted}; padding: 6px 12px 3px 12px;
    font-weight: 500; }}
QPushButton[tab="true"]:hover {{ color: {text}; }}
QPushButton[tab="true"]:checked {{ color: {text}; border-bottom: 3px solid {accent}; }}
QLabel#appBarBrand {{ font-weight: 600; }}
QPushButton#statusChip {{ background: {surface2}; border: 1px solid {border};
    border-radius: 12px; padding: 0 10px; min-height: 22px; max-height: 22px; }}
QPushButton#statusChip:hover {{ border-color: {accent}; }}
QPushButton#statusChip QLabel {{ background: transparent; }}
QLabel[dot] {{ font-size: 10pt; }}
QLabel[dot="ok"] {{ color: {ok}; }}
QLabel[dot="warn"] {{ color: {warn}; }}
QLabel[dot="bad"] {{ color: {bad}; }}
QLabel[dot="neutral"] {{ color: {muted}; }}

QFrame#toast {{ background: {text}; border: none; border-radius: 6px; }}
QFrame#toast QLabel {{ color: {bg}; background: transparent; }}
QFrame#toast[tone="ok"] QLabel#toastMark {{ color: {ok_bg}; }}
QFrame#toast[tone="warn"] QLabel#toastMark {{ color: {warn_bg}; }}
QFrame#toast[tone="bad"] QLabel#toastMark {{ color: {bad_bg}; }}
QFrame#toast QPushButton#toastAction {{ background: transparent; color: {selection}; border: none;
    padding: 0 2px; min-height: 0; font-weight: 700; text-decoration: underline; }}
QFrame#toast QPushButton#toastAction:hover {{ background: transparent; color: {bg}; }}
QFrame#toast QLabel#toastHint {{ color: {border}; }}

QPushButton, QToolButton {{ background: {surface}; color: {text}; border: 1px solid {border};
    border-radius: 4px; padding: 4px 12px; min-height: 20px; }}
QPushButton:hover, QToolButton:hover {{ background: {surface2}; border-color: {muted}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {neutral_bg}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {muted}; background: {bg};
    border-color: {border}; }}
QPushButton:default {{ border-color: {accent}; }}
QToolButton[popupMode="1"] {{ padding-right: 22px; }}
QToolButton::menu-button {{ border: none; border-left: 1px solid {border}; width: 18px; }}

QPushButton[role="primary"] {{ background: {accent}; color: {on_accent}; border: 1px solid {accent};
    font-weight: 600; padding: 5px 18px; }}
QPushButton[role="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QPushButton[role="primary"]:disabled {{ background: {neutral_bg}; color: {muted};
    border-color: {neutral_bg}; }}

QPushButton[role="icon"], QToolButton[role="icon"] {{ background: transparent;
    border: 1px solid transparent; border-radius: 4px; padding: 0; min-width: 28px;
    max-width: 28px; min-height: 28px; max-height: 28px; }}
QPushButton[role="icon"]:hover, QToolButton[role="icon"]:hover {{ background: {surface2};
    border-color: {border}; }}
QPushButton[role="icon"]:checked {{ background: {selection}; border-color: {selection}; }}

QPushButton[segment="true"] {{ border-radius: 0; padding: 4px {seg_pad}px; color: {muted}; }}
QPushButton[segment="true"][segpos="mid"], QPushButton[segment="true"][segpos="last"] {{
    border-left-color: transparent; }}
QPushButton[segment="true"][segpos="first"] {{ border-top-left-radius: 4px;
    border-bottom-left-radius: 4px; }}
QPushButton[segment="true"][segpos="last"] {{ border-top-right-radius: 4px;
    border-bottom-right-radius: 4px; }}
QPushButton[segment="true"]:hover {{ color: {text}; }}
QPushButton[segment="true"]:checked {{ background: {selection}; color: {selection_text};
    border-color: {accent}; font-weight: 600; }}

QLineEdit, QComboBox, QDateEdit, QTimeEdit, QSpinBox {{ background: {surface}; color: {text};
    border: 1px solid {border}; border-radius: 4px; padding: 3px 8px; min-height: 22px;
    selection-background-color: {selection}; selection-color: {selection_text}; }}
QSpinBox, QTimeEdit {{ padding-right: 20px; }}
QLineEdit:hover, QComboBox:hover, QDateEdit:hover, QTimeEdit:hover, QSpinBox:hover {{
    border-color: {muted}; }}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus, QSpinBox:focus {{
    border-color: {accent}; }}
QLineEdit:disabled, QComboBox:disabled, QDateEdit:disabled, QTimeEdit:disabled,
QSpinBox:disabled {{ background: {bg}; color: {muted}; }}
QComboBox::drop-down, QDateEdit::drop-down {{ subcontrol-origin: padding;
    subcontrol-position: center right; width: 20px; border: none; }}
QComboBox::down-arrow, QDateEdit::down-arrow {{ image: url({arrow_down}); width: 10px;
    height: 10px; }}
QAbstractSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right;
    width: 18px; border: none; background: transparent; }}
QAbstractSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: none; background: transparent; }}
QAbstractSpinBox::up-arrow {{ image: url({arrow_up}); width: 8px; height: 8px; }}
QAbstractSpinBox::down-arrow {{ image: url({arrow_down}); width: 8px; height: 8px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::down-arrow:disabled {{ image: none; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border};
    selection-background-color: {selection}; selection-color: {selection_text}; outline: 0; }}

QTableView, QTreeView {{ background: {surface}; alternate-background-color: {surface2};
    border: 1px solid {border}; border-radius: 6px; gridline-color: {surface};
    selection-background-color: {selection}; selection-color: {selection_text}; outline: 0; }}
QTableView::item, QTreeView::item {{ padding: 0 6px; border: none; }}
QTableView::item:selected, QTreeView::item:selected {{
    background: {selection}; color: {selection_text}; }}
QHeaderView {{ background: {surface}; border: none; }}
QHeaderView::section {{ background: {surface}; color: {muted}; font-weight: 600;
    text-align: left; border: none; border-bottom: 1px solid {border}; padding: 5px 8px; }}
QTableCornerButton::section {{ background: {surface}; border: none; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTableView::indicator {{ width: 14px; height: 14px; border-radius: 3px;
    border: 1px solid {muted}; background: {surface}; }}
QCheckBox::indicator:hover, QTableView::indicator:hover {{ border-color: {accent}; }}
QCheckBox::indicator:checked, QTableView::indicator:checked {{ background: {accent};
    border-color: {accent}; image: url({check}); }}
QCheckBox::indicator:disabled, QTableView::indicator:disabled {{ border-color: {border};
    background: {bg}; }}

QPlainTextEdit, QTextEdit {{ background: {surface}; color: {text}; border: 1px solid {border};
    border-radius: 6px; selection-background-color: {selection};
    selection-color: {selection_text}; }}
QScrollArea {{ background: transparent; border: none; }}

QProgressBar {{ background: {neutral_bg}; border: none; border-radius: 2px; min-height: 4px;
    max-height: 4px; }}
QProgressBar::chunk {{ background: {accent}; border-radius: 2px; }}

QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {selection}; color: {selection_text}; }}
QMenu::item:disabled {{ color: {muted}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}

QStatusBar {{ background: {surface}; color: {muted}; border-top: 1px solid {border}; }}
QStatusBar::item {{ border: none; }}
QSplitter::handle {{ background: {bg}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle {{ background: {border}; border-radius: 4px; margin: 2px; }}
QScrollBar::handle:hover {{ background: {muted}; }}
QScrollBar::handle:vertical {{ min-height: 24px; }}
QScrollBar::handle:horizontal {{ min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* -- Impostazioni + Info (Task 18): section list, path fields, save bar, banner -- */
QListWidget#settingsNav {{ background: transparent; border: none; outline: 0; }}
QListWidget#settingsNav::item {{ padding: 6px 10px; margin: 1px 0; border-radius: 5px;
    color: {muted}; }}
QListWidget#settingsNav::item:hover {{ background: {surface2}; color: {text}; }}
QListWidget#settingsNav::item:selected {{ background: {selection}; color: {selection_text}; }}
QLabel#pathField {{ background: {surface}; color: {text}; border: 1px solid {border};
    border-radius: 4px; padding: 3px 8px; min-height: 22px; }}
QLabel#pathField[empty="true"] {{ color: {muted}; }}
QFrame#settingsSaveBar {{ background: {text}; border: none; border-radius: 6px; }}
QFrame#settingsSaveBar QLabel {{ color: {bg}; background: transparent; font-weight: 600; }}
QFrame#settingsSaveBar QPushButton {{ background: transparent; color: {bg}; border-color: {muted}; }}
QFrame#settingsSaveBar QPushButton:hover {{ border-color: {bg}; }}
QFrame#settingsSaveBar QPushButton[role="primary"] {{ background: {accent}; color: {on_accent};
    border-color: {accent}; }}
QFrame#settingsSaveBar QPushButton[role="primary"]:disabled {{ background: transparent;
    color: {muted}; border-color: {muted}; }}
QFrame#settingsBanner {{ background: {warn_bg}; border: none; border-radius: 6px; }}
QFrame#settingsBanner QLabel {{ color: {warn}; background: transparent; }}
/* -- Sync unit (Task 17): primary split button, warn banner, registro toggle -- */
QToolButton[role="primary"] {{ background: {accent}; color: {on_accent}; border: 1px solid {accent};
    font-weight: 600; padding: 5px 30px 5px 16px; }}
QToolButton[role="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
QToolButton[role="primary"]:disabled {{ background: {neutral_bg}; color: {muted};
    border-color: {neutral_bg}; }}
QToolButton[role="primary"]::menu-button {{ border: none; border-left: 1px solid {on_accent};
    width: 20px; }}
QToolButton[role="primary"]:disabled::menu-button {{ border-left-color: {border}; }}
QFrame[role="syncBanner"] {{ background: {warn_bg}; border: none; border-radius: 6px; }}
QFrame[role="syncBanner"] QLabel {{ color: {warn}; background: transparent; }}
QFrame[role="syncBannerBad"] {{ background: {bad_bg}; border: none; border-radius: 6px; }}
QFrame[role="syncBannerBad"] QLabel {{ color: {bad}; background: transparent; }}
QToolButton[role="syncDisclosure"] {{ background: transparent; border: none; color: {muted};
    font-weight: 600; padding: 4px 0; text-align: left; }}
QToolButton[role="syncDisclosure"]:hover {{ color: {text}; }}
QLabel[syncTone="ok"] {{ color: {ok}; font-weight: 600; }}
QLabel[syncTone="warn"] {{ color: {warn}; font-weight: 600; }}
/* -- Search unit (Ricerca page: omnibox, chips, banner, empty-state rows) -- */
QFrame#omnibox {{ background: {surface}; border: 1px solid {border}; border-radius: 4px;
    min-height: 28px; }}
QFrame#omnibox:hover {{ border-color: {muted}; }}
QFrame#omnibox[focused="true"] {{ border-color: {accent}; }}
QFrame#omnibox QLineEdit {{ background: transparent; border: none; padding: 0; min-height: 22px; }}
QFrame[chip="true"] {{ background: {selection}; border: none; border-radius: 4px; }}
QFrame[chip="true"] QLabel {{ background: transparent; color: {selection_text}; }}
QFrame[chip="true"] QLabel[chipCaption="true"] {{ color: {muted}; font-size: 7.5pt;
    font-weight: 600; }}
QFrame[chip="true"] QToolButton {{ background: transparent; border: none; padding: 0;
    min-height: 14px; max-height: 14px; min-width: 14px; max-width: 14px; }}
QFrame[chip="true"] QToolButton:hover {{ background: {neutral_bg}; }}
QFrame[banner="warn"] {{ background: {warn_bg}; border: none; border-radius: 6px; }}
QFrame[banner="warn"] QLabel {{ background: transparent; color: {warn}; }}
QFrame[banner="bad"] {{ background: {bad_bg}; border: none; border-radius: 6px; }}
QFrame[banner="bad"] QLabel {{ background: transparent; color: {bad}; }}
QFrame[banner="ok"] {{ background: {ok_bg}; border: none; border-radius: 6px; }}
QFrame[banner="ok"] QLabel {{ background: transparent; color: {ok}; }}
QFrame[banner="progress"] {{ background: {progress_bg}; border: none; border-radius: 6px; }}
QFrame[banner="progress"] QLabel {{ background: transparent; color: {text}; }}
QToolButton[role="menuButton"]::menu-indicator {{ image: none; width: 0px; }}
QFrame[role="vrule"] {{ background: {border}; border: none; }}
QToolButton[role="stripButton"] {{ background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 1px 6px; color: {accent}; font-weight: 600; }}
QToolButton[role="stripButton"]:hover {{ background: {surface}; border-color: {border}; }}
QToolButton[role="stripButton"]:disabled {{ color: {muted}; }}
QToolButton[diffTab="true"] {{ background: transparent; border: none; border-radius: 4px;
    padding: 3px 8px; color: {muted}; font-weight: 600; }}
QToolButton[diffTab="true"]:hover {{ color: {text}; background: {surface2}; }}
QToolButton[diffTab="true"]:checked {{ background: {selection}; color: {selection_text}; }}
QListWidget#diffList {{ outline: 0; }}
QListWidget#diffList::item {{ border-bottom: 1px solid {border}; padding: 0; }}
QListWidget#diffList::item:selected {{ background: {selection}; color: {selection_text}; }}
QLabel[role="diffGlyph"] {{ color: {muted}; font-weight: 700; border: 1px solid {border};
    border-radius: 3px; padding: 0 3px; }}
QLabel[role="diffNoteBad"] {{ color: {bad}; }}
QLabel[role="diffGroup"] {{ color: {muted}; background: {surface2}; font-size: 8pt;
    font-weight: 700; padding: 4px 8px; }}
QLabel[role="diffLegend"] {{ color: {muted}; font-size: 8pt; border-top: 1px solid {border};
    padding-top: 4px; }}
QFrame#actionsBar {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; }}
QFrame#actionsBar QToolButton {{ background: transparent; color: {text}; border: none;
    border-radius: 4px; padding: 3px 8px; min-height: 0; font-size: 8.5pt; }}
QFrame#actionsBar QToolButton:hover {{ background: {neutral_bg}; }}
QFrame#actionsBar QToolButton[barAction="fatta"] {{ background: {ok_bg}; color: {ok};
    font-weight: 700; }}
QFrame#actionsBar QToolButton[barAction="more"] {{ font-weight: 700; padding: 3px 6px; }}
QPushButton[role="row"] {{ background: transparent; border: 1px solid transparent;
    text-align: left; padding: 4px 8px; color: {text}; }}
QPushButton[role="row"]:hover {{ background: {surface2}; border-color: {border}; }}
QTreeView#results::item {{ padding: 5px 6px; }}
QPushButton[toggle="true"] {{ background: transparent; border: 1px solid transparent;
    color: {muted}; padding: 2px 8px; }}
QPushButton[toggle="true"]:hover {{ border-color: {border}; color: {text}; }}
QPushButton[toggle="true"]:checked {{ background: {selection}; color: {selection_text};
    border-color: {selection}; }}
"""


#: Stroked paths in a 10x10 box: the glyphs the stylesheet draws itself.
_GLYPHS = {
    "chevron-down": "M1.5 3.5 5 7l3.5-3.5",
    "chevron-up": "M1.5 6.5 5 3l3.5 3.5",
    "check": "M2 5.2 4.1 7.3 8 3",
}
_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">'
    '<path d="{d}" fill="none" stroke="{colour}" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)


#: One warning per process: the stylesheet is rebuilt on every theme switch
#: and a read-only temp folder would otherwise repeat itself each time.
_warned = False


def glyph(name: str, colour: str) -> str:
    """Path of a glyph image in ``colour``, for ``url()`` in the stylesheet.

    Once a combo box's drop-down, a spin box's buttons or a check box's
    indicator are restyled Qt stops drawing their arrows and ticks, and QSS
    cannot tint an image: so each glyph is written once per colour as a tiny
    SVG in the temp folder. The name carries the colour, but a file with that
    name is only trusted when its content is exactly the SVG: an empty or
    half-written one (a crash, a second instance writing at the same moment)
    is replaced. The write goes to a unique temporary name in the same folder
    and is then renamed onto the final one, so a reader never sees a partial
    file. Failing is harmless — no glyph, and one warning per process.
    """
    content = _SVG.format(d=_GLYPHS[name], colour=colour)
    file_name = f"{name}-{colour.lstrip('#').lower()}.svg"
    try:
        folder = Path(tempfile.gettempdir()) / "qtrequestory-theme"
        path = folder / file_name
        if not _holds(path, content):
            folder.mkdir(parents=True, exist_ok=True)
            _write_atomically(path, content)
    except OSError as exc:
        _warn_once(exc)
        return f"qtrequestory-theme/{file_name}"
    return path.as_posix()


def _holds(path: Path, content: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == content
    except (OSError, UnicodeDecodeError):
        return False


def _write_atomically(path: Path, content: str) -> None:
    fd, temp = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp, path)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def _warn_once(exc: OSError) -> None:
    global _warned
    if not _warned:
        _warned = True
        log.warning("impossibile scrivere i glifi del tema: %s", exc)
