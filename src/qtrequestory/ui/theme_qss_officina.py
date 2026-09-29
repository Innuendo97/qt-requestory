"""The Officina phase 2.5 blocks of the application stylesheet.

Kept apart from :mod:`qtrequestory.ui.theme_qss` only for size (both are
templates of ``theme.build_qss``, which formats them together): the compact
case bar (U2) and the side panel (U3). Every colour is a ``{token}``
placeholder, braces doubled as in the main template.
"""
from __future__ import annotations

__all__ = ["QSS_OFFICINA_25"]

QSS_OFFICINA_25 = """
/* -- Officina: the compact case bar (phase 2.5, U2) -- */
QFrame#caseBar {{ background: {surface}; border: none; border-bottom: 1px solid {border}; }}
QFrame#caseBar QPushButton, QFrame#caseBar QToolButton {{ padding: 2px 10px; min-height: 20px; }}
QFrame#caseBar QPushButton[segment="true"] {{ padding: 2px 8px; }}
QFrame#caseBar QPushButton[role="primary"] {{ padding: 2px 14px; }}
QFrame#caseBar QToolButton[role="barBack"] {{ background: transparent; border: 1px solid transparent;
    color: {muted}; font-size: 13pt; padding: 0 6px; min-height: 0; }}
QFrame#caseBar QToolButton[role="barBack"]:hover {{ background: {surface2}; color: {text};
    border-color: {border}; }}
QFrame#caseBar QToolButton[role="stripButton"] {{ padding: 1px 6px; min-height: 0; }}
QToolButton[barChip] {{ border: none; border-radius: 8px; padding: 1px 8px; min-height: 0;
    font-weight: 600; font-size: 8.5pt; }}
QToolButton[barChip="warn"] {{ background: {warn_bg}; color: {warn}; }}
QToolButton[barChip="bad"] {{ background: {bad_bg}; color: {bad}; }}
QToolButton[barChip="ok"] {{ background: {ok_bg}; color: {ok}; }}
QToolButton[barChip][clickable="true"]:hover {{ text-decoration: underline; }}
QToolButton[barChip][clickable="true"]:focus {{ border: 1px solid {accent}; }}
QFrame#caseBar QLabel[pill] {{ padding: 1px 7px; font-size: 8.5pt; border-radius: 8px; }}
/* -- Officina: the side panel (phase 2.5, U3) -- */
QWidget#sidePanel {{ background: {surface}; border-left: 1px solid {border}; }}
QWidget#sidePanel QToolButton[diffTab="true"] {{ padding: 1px 1px; min-height: 16px; font-size: 8pt;
    border-radius: 9px; background: {neutral_bg}; color: {text}; }}
QWidget#sidePanel QLabel[pill] {{ padding: 0 2px; }}
QToolButton[chipMore="true"] {{ background: transparent; border: 1px dashed {border}; border-radius: 10px;
    color: {muted}; font-size: 8pt; padding: 0 7px; min-height: 16px; }}
QToolButton[chipMore="true"]:hover, QToolButton[chipMore="true"]:focus {{ color: {text}; border-color: {accent}; }}
QWidget#sidePanel QToolButton[diffTab="true"]:checked {{ background: {accent}; color: {on_accent}; }}
QWidget#sidePanel QToolButton[diffTab="true"]:focus {{ border: 1px solid {accent}; }}
QToolButton[role="panelTool"] {{ background: transparent; border: 1px solid transparent; border-radius: 4px;
    color: {muted}; font-weight: 700; padding: 0 5px; min-height: 0; }}
QToolButton[role="panelTool"]:hover, QToolButton[role="panelTool"]:focus {{ background: {surface2};
    border-color: {border}; color: {text}; }}
QFrame#panelRail QToolButton[role="panelRailButton"] {{ background: {neutral_bg}; border: 1px solid transparent;
    border-radius: 6px; color: {text}; font-weight: 700; padding: 0; }}
QFrame#panelRail QToolButton[role="panelRailButton"]:hover,
QFrame#panelRail QToolButton[role="panelRailButton"]:focus {{ border-color: {accent}; }}
QFrame#panelFooter {{ border: none; border-top: 1px solid {border}; }}
QLabel[role="panelZones"] {{ color: {muted}; font-size: 8pt; }}
QLabel[role="diffTypeGroup"] {{ color: {text}; background: {surface2}; font-size: 8pt;
    font-weight: 700; padding: 2px 8px; }}
QLabel[role="typeBadge"] {{ background: {neutral_bg}; border-radius: 9px; color: {text}; }}
QFrame#panelLegend {{ background: {surface}; border: 1px solid {border}; border-radius: 6px; }}
"""
