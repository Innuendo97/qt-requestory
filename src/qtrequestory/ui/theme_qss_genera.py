"""The Genera blocks of the application stylesheet (release 1.5.0, redesign).

Kept apart from :mod:`qtrequestory.ui.theme_qss` only for size (both are
templates of ``theme.build_qss``, which formats them together): the setup
pane with its pinned footer, the outcome chips over the results, the package
list. Every colour is a ``{token}`` placeholder, braces doubled.
"""
from __future__ import annotations

__all__ = ["QSS_GENERA"]

QSS_GENERA = """
/* -- Genera: the setup pane (left, or on top when the window is narrow) -- */
QFrame#generaSetup {{ background: {surface}; border: none; border-right: 1px solid {border}; }}
QFrame#generaSetup[stacked="true"] {{ border-right: none; border-bottom: 1px solid {border}; }}
QFrame#generaSetup QScrollArea, QFrame#generaSetup QScrollArea > QWidget > QWidget {{
    background: transparent; }}
QFrame#generaSetup QFrame[role="hrule"] {{ background: {border}; border: none; min-height: 1px;
    max-height: 1px; }}
QFrame#generaActionBar {{ background: {surface}; border: none; border-top: 1px solid {border}; }}
QFrame#generaActionBar QPushButton[role="primary"] {{ padding: 7px 18px; font-size: 10pt; }}
QFrame#generaActionBar QPushButton[running="true"] {{ padding: 7px 18px; font-size: 10pt;
    font-weight: 600; }}
QLabel[role="fieldLabel"] {{ color: {muted}; font-size: 8.5pt; font-weight: 600; }}
QToolButton[role="stepToggle"] {{ background: transparent; border: none; padding: 2px 0;
    color: {text}; font-size: 10.5pt; font-weight: 600; text-align: left; }}
QToolButton[role="stepToggle"]:hover {{ color: {accent}; }}
QToolButton[role="stepToggle"]:focus {{ color: {accent}; text-decoration: underline; }}
/* -- Genera: the package list -- */
QListWidget#generaPackages {{ background: {surface}; border: 1px solid {border}; border-radius: 6px;
    outline: 0; }}
QListWidget#generaPackages::item {{ border-bottom: 1px solid {surface2}; }}
QListWidget#generaPackages::item:hover {{ background: {surface2}; }}
/* -- Genera: the results pane -- */
QTableWidget#generaResults::item {{ padding: 0 6px; }}
QToolButton[outcomeChip] {{ border: 1px solid transparent; border-radius: 12px; padding: 2px 11px;
    min-height: 18px; font-weight: 600; }}
QToolButton[outcomeChip="all"] {{ background: {neutral_bg}; color: {text}; }}
QToolButton[outcomeChip="ok"] {{ background: {ok_bg}; color: {ok}; }}
QToolButton[outcomeChip="warn"] {{ background: {warn_bg}; color: {warn}; }}
QToolButton[outcomeChip="muted"] {{ background: {neutral_bg}; color: {text}; }}
QToolButton[outcomeChip]:hover {{ border-color: {muted}; }}
QToolButton[outcomeChip]:focus {{ border-color: {accent}; }}
QToolButton[outcomeChip="all"]:checked {{ background: {accent}; color: {on_accent}; }}
QToolButton[outcomeChip="ok"]:checked {{ background: {ok}; color: {on_accent}; }}
QToolButton[outcomeChip="warn"]:checked {{ background: {warn}; color: {on_accent}; }}
QToolButton[outcomeChip="muted"]:checked {{ background: {muted}; color: {on_accent}; }}
QToolButton[outcomeChip]:checked:focus {{ border-color: {text}; }}
"""
