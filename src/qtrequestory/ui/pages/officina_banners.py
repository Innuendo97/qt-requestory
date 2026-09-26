"""The review strips and the profile menu of the case view (spec §5.3, §7.1).

Two compact one-line strips (R28: at most :data:`STRIP_MAX_H` px, small flat
buttons), each hidden while it has nothing to say:

* **da verificare** (blue) while the case holds "segna fatta" marks: "N
  modifiche da verificare: pubblica su <generatore> e rigenera il TO-BE (F5)"
  with a flat "Annulla i segni";
* **esito della verifica** after the first comparison of a TO-BE newer than
  the marks: "**vM: verificate N modifiche segnate** — X risolte, Y non
  risolte" (zero parts left out; green when every mark was resolved, amber
  otherwise). The outcome is kept while the case stays open, on that version
  only; after the user's next action in the case (:meth:`ReviewBanners.collapse`)
  the strip folds into a small pill of the progress bar
  (:meth:`ReviewBanners.collapsed_outcome`). Leaving the case forgets it.

The two-way warning is a pill of the progress bar (``officina_progress``).

The profile menu ("Tollerante / Stretto / Solo testo / Come l'iniziativa")
emits the profile chosen (``None`` = follow the initiative); the page saves
it (``OfficinaApi.set_profile``) and compares again.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CaseComparison, Verification

__all__ = ["PROFILES", "STRIP_MAX_H", "ProfileButton", "ReviewBanners", "Strip", "live_marks", "marks_text",
           "outcome_parts", "outcome_text", "profile_name"]

#: The tallest a review strip may be (R28), in logical px.
STRIP_MAX_H = 28

#: (profile, its name) in menu order.
PROFILES: tuple[tuple[str, str], ...] = (
    ("tollerante", strings.PROFILO_TOLLERANTE),
    ("stretto", strings.PROFILO_STRETTO),
    ("solo_testo", strings.PROFILO_SOLO_TESTO),
)


def profile_name(profile: str | None) -> str:
    return dict(PROFILES).get(profile or "tollerante", strings.PROFILO_TOLLERANTE)


def _form(name: str, n: int, **fields) -> str:
    return getattr(strings, f"{name}_{'ONE' if n == 1 else 'MANY'}").format(n=n, **fields)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def outcome_parts(v: Verification | None) -> tuple[str, list[str], str] | None:
    """``(head, parts, tone)`` of a verification (zero parts left out), or
    None when nothing was checked."""
    if v is None or v.checked <= 0:
        return None
    head = _form("REVISIONE_OUTCOME_HEAD", v.checked, version=v.version)
    parts = [_form(name, n) for name, n in (("REVISIONE_OUTCOME_RESOLVED", v.resolved),
                                            ("REVISIONE_OUTCOME_UNRESOLVED", v.unresolved),
                                            ("REVISIONE_OUTCOME_CHANGED", v.changed)) if n]
    tone = "ok" if not (v.unresolved or v.changed) else "warn"
    return head, parts, tone


def outcome_text(v: Verification | None) -> tuple[str, str] | None:
    """``(plain text, tone)`` of a verification, or None when nothing was checked."""
    got = outcome_parts(v)
    if got is None:
        return None
    head, parts, tone = got
    return strings.REVISIONE_OUTCOME.format(head=head, parts=", ".join(parts)), tone


def live_marks(case, docs) -> int:
    """How many marks the "da verificare" strip counts: the summary's
    ``da_verificare`` of the comparison on screen (else the case's saved
    one), never more than the marks in the file. A mark on a difference that
    does not count right now is dormant (R32): it waits in ``caso.json`` but
    is not "da verificare"."""
    if case is None:
        return 0
    judged = docs.judged if docs is not None else None
    summary = judged.summary if judged is not None else case.review.summary
    marks = len(case.review.marks)
    return marks if summary is None else min(marks, summary.da_verificare)


def marks_text(n: int, env: str) -> str:
    """The "da verificare" strip for ``n`` marks ("" for none)."""
    if n <= 0:
        return ""
    if env:
        return _form("REVISIONE_MARKS", n, env=env)
    return getattr(strings, f"REVISIONE_MARKS_{'ONE' if n == 1 else 'MANY'}_NO_ENV").format(n=n)


class Strip(QFrame):
    """A one-line tinted strip (``banner`` QSS tone), hidden while it has no
    text; an optional small flat button sits on its right. A text too long
    for the width is clipped; the tooltip has all of it."""

    def __init__(self, tone: str, button: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("banner", tone)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumHeight(STRIP_MAX_H)
        self.label = QLabel()
        self.label.setTextFormat(Qt.TextFormat.RichText)
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._plain = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE[2], 0, theme.SPACE[1], 0)
        row.setSpacing(theme.SPACE[1])
        row.addWidget(self.label, 1)
        self.button: QToolButton | None = None
        if button:
            self.button = QToolButton()
            self.button.setText(button)
            self.button.setAutoRaise(True)
            theme.set_role(self.button, "stripButton")
            row.addWidget(self.button)
        self.setVisible(False)

    def set_text(self, plain: str, rich: str | None = None, tone: str | None = None) -> None:
        """``plain`` ("" hides the strip); ``rich`` is what is drawn when given."""
        if tone is not None and tone != self.property("banner"):
            self.setProperty("banner", tone)
            theme.repolish(self)
            for child in self.findChildren(QWidget):
                theme.repolish(child)
        self._plain = plain
        self.label.setText(rich if rich is not None else _escape(plain))
        self.setToolTip(plain)
        self.setVisible(bool(plain))

    def text(self) -> str:
        """The plain text on show ("" while hidden)."""
        return self._plain if not self.isHidden() else ""


@dataclass
class _Outcome:
    key: tuple[Path, int]           # (case folder, TO-BE number) it belongs to
    plain: str
    rich: str
    tone: str
    short: str
    collapsed: bool = False


class ReviewBanners(QWidget):
    """The two strips, stacked; zero height when both are hidden."""

    unmark_all_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.marks = Strip("progress", strings.REVISIONE_UNMARK_ALL)
        self.unmark_button = self.marks.button
        self.unmark_button.setToolTip(strings.REVISIONE_UNMARK_ALL_TIP)
        self.unmark_button.clicked.connect(self.unmark_all_requested)
        self.outcome = Strip("ok")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        for strip in (self.marks, self.outcome):
            layout.addWidget(strip)
        self._outcome: _Outcome | None = None
        self._key: tuple[Path, int | None] | None = None

    def show_marks(self, n: int, env: str, *, enabled: bool = True) -> None:
        """``n`` marks still waiting for a newer TO-BE."""
        self.marks.set_text(marks_text(n, env))
        self.unmark_button.setEnabled(enabled)

    def show_judged(self, folder: Path | None, judged: CaseComparison | None,
                    version: int | None) -> None:
        """The outcome strip for the comparison on screen (``judged`` None:
        the AS-IS, or nothing judged; ``version`` = the one shown)."""
        v = judged.verification if judged is not None else None
        got = outcome_parts(v)
        if folder is not None and got is not None:
            head, parts, tone = got
            joined = ", ".join(parts)
            self._outcome = _Outcome(
                (folder, judged.version),
                strings.REVISIONE_OUTCOME.format(head=head, parts=joined),
                strings.REVISIONE_OUTCOME.format(head=f"<b>{_escape(head)}</b>", parts=_escape(joined)),
                tone,
                strings.REVISIONE_OUTCOME_SHORT.format(version=v.version, resolved=v.resolved,
                                                       checked=v.checked))
        self._key = (folder, version) if folder is not None else None
        self._refresh()

    def collapse(self) -> None:
        """The user did something else in the case: the outcome folds into the bar."""
        if self._outcome is not None and not self._outcome.collapsed:
            self._outcome.collapsed = True
            self._refresh()

    def collapsed_outcome(self) -> tuple[str, str, str] | None:
        """``(short text, full text, tone)`` of a folded outcome on screen, else None."""
        shown = self._shown()
        return (shown.short, shown.plain, shown.tone) if shown and shown.collapsed else None

    def forget(self) -> None:
        """A new visit of a case: an earlier outcome is not this one's."""
        self._outcome = None
        self._refresh()

    def marks_text(self) -> str:
        return self.marks.text()

    def outcome_text(self) -> str:
        return self.outcome.text()

    def _shown(self) -> _Outcome | None:
        if self._outcome is None or self._key is None or self._outcome.key != self._key:
            return None
        return self._outcome

    def _refresh(self) -> None:
        shown = self._shown()
        if shown is None or shown.collapsed:
            self.outcome.set_text("")
        else:
            self.outcome.set_text(shown.plain, shown.rich, shown.tone)


class ProfileButton(QToolButton):
    """"Profilo: Tollerante ▾" with the three profiles and "Come l'iniziativa"."""

    #: The profile chosen: "tollerante" | "stretto" | "solo_testo" | None (the initiative's).
    profile_chosen = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.setToolTip(strings.PROFILO_TIP)
        theme.set_role(self, "menuButton")  # the ▾ is in the text
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        self._actions: dict[str | None, QAction] = {}
        for profile, name in PROFILES:
            self._actions[profile] = self._add(menu, group, name, profile)
        menu.addSeparator()
        self._actions[None] = self._add(menu, group, "", None)
        self.setMenu(menu)
        self._current: str | None = None
        self._inherited = "tollerante"
        self.set_profile(None, "tollerante")

    def _add(self, menu: QMenu, group: QActionGroup, text: str, profile: str | None) -> QAction:
        action = QAction(text, menu)
        action.setCheckable(True)
        group.addAction(action)
        menu.addAction(action)
        action.triggered.connect(lambda _checked=False, p=profile: self._chosen(p))
        return action

    def set_profile(self, profile: str | None, initiative: str | None) -> None:
        """The case's own ``profile`` (None = the initiative's, ``initiative``)."""
        self._current = profile
        self._inherited = initiative or "tollerante"
        inherited = profile_name(self._inherited)
        self._actions[None].setText(strings.PROFILO_INIZIATIVA.format(profile=inherited))
        self._actions[profile if profile in self._actions else None].setChecked(True)
        self.setText(strings.PROFILO_BUTTON.format(profile=profile_name(profile)) if profile
                     else strings.PROFILO_BUTTON_INHERITED.format(profile=inherited))

    def current(self) -> str | None:
        return self._current

    def action_for(self, profile: str | None) -> QAction:
        return self._actions[profile]

    def _chosen(self, profile: str | None) -> None:
        if profile != self._current:
            self.profile_chosen.emit(profile)
        else:
            self.set_profile(self._current, self._inherited)
