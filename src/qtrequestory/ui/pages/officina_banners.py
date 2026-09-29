"""What the case bar says of the review, and its profile menu (spec §5, §5.3, §7.1).

Since phase 2.5 (U2, D15) there are no strips taking height over the
documents: everything is in the one case bar (``officina_case_bar``).

* **da verificare** while the case holds "segna fatta" marks: "N modifiche da
  verificare: pubblica su <generatore> e rigenera il TO-BE (F5)" is the
  tooltip of the bar's "✓? N" pill; "Annulla i segni" is in the "⋯" menu;
* **esito della verifica** after the first comparison of a TO-BE newer than
  the marks: a chip "vM: X/N risolte" (green when every mark was resolved,
  amber otherwise) whose tooltip is the whole sentence "vM: verificate N
  modifiche segnate — X risolte, Y non risolte" (zero parts left out). It is
  kept while the case stays open, on that version only; leaving the case
  forgets it.

The two-way warning is a pill of the progress (``officina_progress``).

The profile menu ("Tollerante / Stretto / Solo testo / Come l'iniziativa",
a submenu of "⋯") emits the profile chosen (``None`` = follow the
initiative); the page saves it (``OfficinaApi.set_profile``) and compares again.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CaseComparison, Verification

__all__ = ["PROFILES", "ProfileMenu", "ReviewBanners", "live_marks", "marks_text",
           "outcome_parts", "outcome_text", "profile_name"]

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


@dataclass
class _Outcome:
    key: tuple[Path, int]           # (case folder, TO-BE number) it belongs to
    plain: str
    tone: str
    short: str


class ReviewBanners:
    """What the case bar says of the review (no widget of its own since
    phase 2.5, U2): the marks' sentence (the "da verificare" pill's tooltip)
    and the verification outcome of the version on screen (a chip)."""

    def __init__(self) -> None:
        self._marks = ""
        self._outcome: _Outcome | None = None
        self._key: tuple[Path, int | None] | None = None

    def show_marks(self, n: int, env: str) -> None:
        """``n`` marks still waiting for a newer TO-BE."""
        self._marks = marks_text(n, env)

    def show_judged(self, folder: Path | None, judged: CaseComparison | None,
                    version: int | None) -> None:
        """The outcome for the comparison on screen (``judged`` None: the
        AS-IS, or nothing judged; ``version`` = the one shown). It is kept
        while the case stays open, on that version only."""
        v = judged.verification if judged is not None else None
        got = outcome_parts(v)
        if folder is not None and got is not None:
            head, parts, tone = got
            self._outcome = _Outcome(
                (folder, judged.version),
                strings.REVISIONE_OUTCOME.format(head=head, parts=", ".join(parts)),
                tone,
                strings.REVISIONE_OUTCOME_SHORT.format(version=v.version, resolved=v.resolved,
                                                       checked=v.checked))
        self._key = (folder, version) if folder is not None else None

    def outcome(self) -> tuple[str, str, str] | None:
        """``(short text, full text, tone)`` of the outcome on screen, else None."""
        shown = self._shown()
        return (shown.short, shown.plain, shown.tone) if shown else None

    def forget(self) -> None:
        """A new visit of a case: an earlier outcome is not this one's."""
        self._outcome = None

    def marks_text(self) -> str:
        return self._marks

    def outcome_text(self) -> str:
        shown = self._shown()
        return shown.plain if shown else ""

    def _shown(self) -> _Outcome | None:
        if self._outcome is None or self._key is None or self._outcome.key != self._key:
            return None
        return self._outcome


class ProfileMenu(QMenu):
    """"Profilo: Tollerante (iniziativa)" — a submenu of the case bar's "⋯":
    the three profiles and "Come l'iniziativa"."""

    #: The profile chosen: "tollerante" | "stretto" | "solo_testo" | None (the initiative's).
    profile_chosen = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTipsVisible(True)
        self.menuAction().setToolTip(strings.PROFILO_TIP)
        group = QActionGroup(self)
        group.setExclusive(True)
        self._actions: dict[str | None, QAction] = {}
        for profile, name in PROFILES:
            self._actions[profile] = self._add(group, name, profile)
        self.addSeparator()
        self._actions[None] = self._add(group, "", None)
        self._current: str | None = None
        self._inherited = "tollerante"
        self.set_profile(None, "tollerante")

    def _add(self, group: QActionGroup, text: str, profile: str | None) -> QAction:
        action = QAction(text, self)
        action.setCheckable(True)
        group.addAction(action)
        self.addAction(action)
        action.triggered.connect(lambda _checked=False, p=profile: self._chosen(p))
        return action

    def set_profile(self, profile: str | None, initiative: str | None) -> None:
        """The case's own ``profile`` (None = the initiative's, ``initiative``)."""
        self._current = profile
        self._inherited = initiative or "tollerante"
        inherited = profile_name(self._inherited)
        self._actions[None].setText(strings.PROFILO_INIZIATIVA.format(profile=inherited))
        self._actions[profile if profile in self._actions else None].setChecked(True)
        self.setTitle(strings.BARRA_PROFILE.format(profile=profile_name(profile)) if profile
                      else strings.BARRA_PROFILE_INHERITED.format(profile=inherited))

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt naming
        """The submenu's entry in "⋯" follows (a disabled QMenu alone still opens)."""
        super().setEnabled(enabled)
        self.menuAction().setEnabled(enabled)

    def current(self) -> str | None:
        return self._current

    def action_for(self, profile: str | None) -> QAction:
        return self._actions[profile]

    def _chosen(self, profile: str | None) -> None:
        if profile != self._current:
            self.profile_chosen.emit(profile)
        else:
            self.set_profile(self._current, self._inherited)
