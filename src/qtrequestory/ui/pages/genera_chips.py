"""The outcome chips over the Genera results: counts that are also filters.

::

    (Tutti 22)  (✓ 15 generati)  (⊘ 2 email saltate)  (○ 3 senza chiamata)  (✕ 2 non riusciti)  (↻ 5 da riprovare)

One chip per outcome that occurred (a zero count has no chip), in
``CHIP_ORDER``, coloured by the outcome's tone (``theme_qss_genera``:
``outcomeChip``), glyph + words so colour is never the only channel. The
chips are exclusive: a click shows only that outcome's rows, a click on the
chip already chosen (or on "Tutti") shows them all again. Every chip is a
button: Tab reaches it, Space toggles it. On a narrow pane the chips wrap
(Officina's ``FlowLayout``) instead of widening the window.

**↻ da riprovare** (:data:`RETRY`) is every row "Riprova" sends again
(``genera_retry.RETRY_STATUSES``: non riusciti, senza chiamata, annullati
together — the old "Solo non riusciti"), with the glyph of the Riprova
button's icon and the button named in its tooltip. It is shown only when
those rows are of more than one kind: with one kind it would repeat that
kind's chip.

**A new run keeps the choice.** While a run goes the rows arrive as they
finish and every one is shown (:meth:`OutcomeChips.begin_run`; a chip picked
meanwhile is the new choice). With the run's report (``set_counts(…,
final=True)``) the choice comes back if the new rows still have some for it
(the retry chip's rows shown by their single kind's chip when there is only
one); otherwise the filter falls back to "Tutti" and the choice is forgotten.
"""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QToolButton, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.genera_outcomes import CHIP_ORDER, STATUS_LOOK, SUMMARY_WORDS
from qtrequestory.ui.pages.genera_retry import RETRY_STATUSES
from qtrequestory.ui.pages.officina_type_chips import FlowLayout

__all__ = ["ALL", "RETRY", "OutcomeChips", "chip_text", "statuses_of"]

ALL = "all"
#: The rows "Riprova" sends again, as one chip.
RETRY = "retry"
#: The chip's own words where the summary's are too long for a chip.
_CHIP_WORDS = {"no_call": (strings.GENERA_CHIP_NO_CALL_ONE, strings.GENERA_CHIP_NO_CALL),
               RETRY: (strings.GENERA_CHIP_RETRY_ONE, strings.GENERA_CHIP_RETRY)}
_GLYPHS = {RETRY: strings.GENERA_GLYPH_RETRY}
_TIPS = {"html_skipped": strings.GENERA_CHIP_HTML_TIP, RETRY: strings.GENERA_CHIP_RETRY_TIP}


def statuses_of(key: str | None) -> frozenset[str] | None:
    """The outcomes a chip shows; None for "Tutti" (every row)."""
    if key is None or key == ALL:
        return None
    return RETRY_STATUSES if key == RETRY else frozenset({key})


def chip_text(status: str, n: int) -> str:
    """"✓ 15 generati"; "Tutti 22" for :data:`ALL`, "↻ 5 da riprovare" for :data:`RETRY`."""
    if status == ALL:
        return strings.GENERA_CHIP_ALL.format(n=n)
    one, many = _CHIP_WORDS.get(status) or SUMMARY_WORDS[status]
    glyph = _GLYPHS.get(status) or STATUS_LOOK[status][0]
    return strings.GENERA_CHIP.format(glyph=glyph, text=one if n == 1 else many.format(n=n))


def _count(key: str, counts: Mapping[str, int]) -> int:
    shown = statuses_of(key)
    return sum(counts.values()) if shown is None else sum(counts.get(s, 0) for s in shown)


class OutcomeChips(QWidget):
    """The band of chips (module docstring)."""

    #: The chip shown (a status, :data:`RETRY`), or None for every row.
    changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._chips: dict[str, QToolButton] = {}
        layout = FlowLayout(self, spacing=theme.SPACE[1] + theme.SPACE[0] // 2)  # wraps, never widens the window
        for status in (ALL, *CHIP_ORDER, RETRY):
            chip = QToolButton()
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            tone = {ALL: "all", RETRY: "warn"}.get(status) or STATUS_LOOK[status][2]
            chip.setProperty("outcomeChip", tone)
            chip.setToolTip(_TIPS.get(status, strings.GENERA_CHIP_TIP))
            chip.clicked.connect(lambda _c=False, s=status: self._clicked(s))
            self._group.addButton(chip)
            layout.addWidget(chip)
            self._chips[status] = chip
            chip.setVisible(False)
        self._chips[ALL].setChecked(True)
        self._last = ALL     # the chip shown
        self._choice = ALL   # the user's (module docstring: kept across a run)

    def set_counts(self, counts: Mapping[str, int], *, final: bool = False) -> None:
        """The chips of the outcomes with a count, and "Tutti". ``final``: the
        run's report — the user's choice comes back, or falls back to "Tutti"."""
        total = sum(counts.values())
        self._chips[ALL].setText(chip_text(ALL, total))
        self._chips[ALL].setVisible(total > 0)
        for status in CHIP_ORDER:
            n = counts.get(status, 0)
            chip = self._chips[status]
            if n:
                chip.setText(chip_text(status, n))
            chip.setVisible(bool(n))
        retry = self._chips[RETRY]
        n = _count(RETRY, counts)
        if n:
            retry.setText(chip_text(RETRY, n))
        retry.setVisible(self._retry_differs(counts))
        if final:
            key = self._shown_for(self._choice, counts)
            self._choice = self._choice if key != ALL else ALL
            self._show(key)
        elif self._last != ALL and self._chips[self._last].isHidden():
            self._show(ALL)  # its rows are gone (a run starting): the choice waits for the report

    def begin_run(self) -> None:
        """A new run: every row is shown as it arrives; the choice is kept."""
        self._show(ALL)

    def select(self, status: str | None) -> None:
        """Show ``status`` alone (None: everything), as a click would."""
        key = status or ALL
        self._choice = key
        self._show(key)

    def current(self) -> str:
        """The chip shown."""
        return self._last

    def chip(self, status: str) -> QToolButton:
        return self._chips[status]

    def shown(self) -> list[str]:
        """The chips on screen, in order (tests, accessibility)."""
        return [s for s, chip in self._chips.items() if not chip.isHidden()]

    # -- internals ---------------------------------------------------------------------

    @staticmethod
    def _retry_differs(counts: Mapping[str, int]) -> bool:
        """The retry chip says something no single chip says: two kinds or more."""
        return sum(1 for s in RETRY_STATUSES if counts.get(s)) > 1

    def _shown_for(self, choice: str, counts: Mapping[str, int]) -> str:
        """The chip that shows ``choice``'s rows among ``counts`` (ALL: none left)."""
        if choice == ALL or not _count(choice, counts):
            return ALL
        if choice == RETRY and not self._retry_differs(counts):
            return next(s for s in CHIP_ORDER if s in RETRY_STATUSES and counts.get(s))
        return choice

    def _show(self, key: str) -> None:
        self._chips[key].setChecked(True)
        if key != self._last:
            self._last = key
            self.changed.emit(None if key == ALL else key)

    def _clicked(self, status: str) -> None:
        # a second click on the chosen chip shows everything again
        self.select(None if status == self._last else status)
