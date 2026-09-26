"""The progress bar of the case view (spec §7.1, approved draft "caso-fase2").

::

    60%        ▲ 1 regressione  ○ 2 da fare  ◐ 1 in corso  ✓ 6 fatte  |  ⊘ 3 tollerate  {x} 14 variabili
    v3 contro target   ▮▮▮▮▮▮▮▮▮▮▮▮▮  (the verdict strip: one segment per difference)

* the **percentage** is ``CaseSummary.avanzamento`` (fatte over what counts;
  a "da verificare" still counts with its verdict, spec §5.1);
* the **pills**, in the spec's order — regressioni · non risolte · da fare ·
  in corso · da verificare · fatte — then, apart and dimmed, tollerate ·
  variabili · rumore; a zero count has no pill. With the judged differences
  at hand the pills count each difference in its verdict (a marked one as
  "da verificare" only: the summary, R15, counts a mark in both), and the
  "non risolte" pill counts every flagged difference whatever its verdict
  (R44: it may be in two totals; its tooltip says so). Tones are
  ``officina_verdict_style.Look.pill`` (R14), so a verdict has the same
  colour here, in the list and on the board;
* the **verdict strip** draws the judged differences that have a verdict
  (variables and noise have none), in document order, coloured like
  ``coverage_strip`` squares; a click emits the difference's id.

The chrome follows the theme (R13: only the overlays ON the page use paper colours).
"""
from __future__ import annotations

import math
from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CaseSummary, Judged
from qtrequestory.ui.pages.officina_strip import VerdictStrip, document_order
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, board_counts, pill_counts, state_of
from qtrequestory.ui.pages.officina_widgets import pill

__all__ = ["PILL_ORDER", "ProgressBar", "VerdictStrip", "count_text", "document_order",
           "glyph_html",
           "percent", "pill_texts", "remaining_text", "state_counts"]

#: (look state, CaseSummary field, strings prefix, dimmed) in the spec's order.
PILL_ORDER: tuple[tuple[str, str, str, bool], ...] = (
    ("regressione", "regressioni", "REGRESSIONE", False),
    ("non_risolta", "non_risolte", "NON_RISOLTA", False),
    ("da_fare", "da_fare", "DA_FARE", False),
    ("in_corso", "in_corso", "IN_CORSO", False),
    ("da_verificare", "da_verificare", "DA_VERIFICARE", False),
    ("fatta", "fatte", "FATTA", False),
    ("tollerata", "tollerate", "TOLLERATA", True),
    ("variabile", "variabili", "VARIABILE", True),
    ("rumore", "rumore", "RUMORE", True),
)
#: Opacity of the tollerate / variabili / rumore pills (they do not count).
DIMMED_OPACITY = 0.72
#: The UI font draws some verdict glyphs as specks (◐ looked like a dot in a
#: pill): they are drawn from a symbol font that has them at full size.
GLYPH_FONT = "Segoe UI Symbol"
GLYPH_FONTS = {"⊘": "Cambria Math"}
#: U+FE0E: draw the glyph before it as text (monochrome), not as a colour emoji.
TEXT_PRESENTATION = "︎"


def _count_text(prefix: str, icon: str, n: int) -> str:
    form = "ONE" if n == 1 else "MANY"
    return getattr(strings, f"AVANZAMENTO_{prefix}_{form}").format(icon=icon, n=n)


def percent(avanzamento: float) -> int:
    """0..100, rounded DOWN: 100 only when everything is done (0.995 is 99).
    Total: NaN and anything below 0 are 0, anything from 1 up (+inf) is 100."""
    if math.isnan(avanzamento) or avanzamento <= 0:
        return 0
    if avanzamento >= 1.0:
        return 100
    return max(0, min(99, math.floor(avanzamento * 100 + 1e-9)))


def glyph_html(text: str) -> str:
    """``text`` as rich text, its non-ASCII glyphs in a symbol font. A glyph
    followed by U+FE0E (text presentation, e.g. the link's 🔗) keeps it in
    the same span, so the symbol font draws it in the text colour instead of
    the colour-emoji font."""
    out = []
    for i, ch in enumerate(text):
        if ch == TEXT_PRESENTATION:
            continue  # joined to the glyph before it
        safe = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}.get(ch, ch)
        if ord(ch) > 0x2000:
            family = GLYPH_FONTS.get(ch, GLYPH_FONT)
            tail = TEXT_PRESENTATION if text[i + 1:i + 2] == TEXT_PRESENTATION else ""
            out.append(f"<span style='font-family:\"{family}\"'>{safe}{tail}</span>")
        else:
            out.append(safe)
    return "".join(out)


def state_counts(judged: Sequence[Judged]) -> dict[str, int]:
    """How many judged differences are in each look state (one state each)."""
    counts = dict.fromkeys(LOOKS, 0)
    for j in judged:
        counts[state_of(j)] += 1
    return counts


def _counts(summary: CaseSummary, judged: Sequence[Judged] | None) -> dict[str, int]:
    if judged:
        return pill_counts(judged)
    return board_counts(summary)  # R15/R44: the same totals from the summary


def remaining_text(counts: dict[str, int]) -> str:
    """The "Segna accettato" confirmation (spec §5.4) for what is still open
    in ``counts`` (``pill_counts`` / ``board_counts``) — regressioni, non
    risolte, da fare, in corso, da verificare, in the case bar's order and
    words, without glyphs — or ""."""
    open_states = ("regressione", "non_risolta", "da_fare", "in_corso", "da_verificare")
    parts = [_count_text(prefix, "", counts[state]).strip()
             for state, _field, prefix, _dim in PILL_ORDER if state in open_states and counts[state]]
    return strings.OFFICINA_ACCEPT_REMAINING.format(parts=", ".join(parts)) if parts else ""


def count_text(state: str, n: int) -> str:
    """"▲ 2 regressioni": the pill text of ``n`` differences in ``state``."""
    prefix = next(p for s, _f, p, _d in PILL_ORDER if s == state)
    return _count_text(prefix, LOOKS[state].icon, n)


def pill_texts(summary: CaseSummary,
               judged: Sequence[Judged] | None = None) -> list[tuple[str, str, bool]]:
    """``[(text, pill tone, dimmed), ...]`` for the non-zero counts, in spec
    order: of ``judged`` by state when given, else of ``summary`` as the
    board reads it (``board_counts``: a mark counted once, as "da verificare")."""
    out = []
    counts = _counts(summary, judged)
    for state, _field, prefix, dimmed in PILL_ORDER:
        n = counts[state]
        if n:
            look = LOOKS[state]
            out.append((_count_text(prefix, look.icon, n), look.pill, dimmed))
    return out


class ProgressBar(QFrame):
    """Percentage, "vN contro target", the pills and the strip; hidden
    while nothing is judged (the AS-IS, or a core that cannot judge).

    On the strip's row: the two-way pill ("a due vie", the full warning as its
    tooltip) with "Genera l'AS-IS", and the folded outcome of a verification
    (R28)."""

    diff_selected = Signal(int)
    asis_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.percent = QLabel()
        theme.set_role(self.percent, "pageTitle")
        self.percent.setToolTip(strings.AVANZAMENTO_TOOLTIP)
        self.version_label = QLabel()
        theme.set_role(self.version_label, "muted")
        self.nothing = QLabel(strings.AVANZAMENTO_NOTHING)
        theme.set_role(self.nothing, "muted")
        self.strip = VerdictStrip()
        self.strip.diff_selected.connect(self.diff_selected)
        self._pills: dict[str, QLabel] = {}
        self._plain: dict[str, str] = {}
        for state, *_rest in PILL_ORDER:
            label = pill("", LOOKS[state].pill)
            label.setTextFormat(Qt.TextFormat.RichText)
            if state == "non_risolta":
                label.setToolTip(strings.AVANZAMENTO_NON_RISOLTA_TIP)
            self._pills[state] = label
        self.separator = QFrame()
        self.separator.setFixedSize(1, 16)
        theme.set_role(self.separator, "vrule")
        self.dimmed_box = QWidget()
        effect = QGraphicsOpacityEffect(self.dimmed_box)
        effect.setOpacity(DIMMED_OPACITY)
        self.dimmed_box.setGraphicsEffect(effect)
        self.two_way = pill("", "warn", strings.REVISIONE_TWO_WAY)
        self.two_way.setTextFormat(Qt.TextFormat.RichText)
        self.two_way.setText(glyph_html(strings.AVANZAMENTO_TWO_WAY))
        self.asis_button = QToolButton()
        self.asis_button.setText(strings.AVANZAMENTO_GENERATE_ASIS)
        self.asis_button.setAutoRaise(True)
        theme.set_role(self.asis_button, "stripButton")
        self.asis_button.clicked.connect(self.asis_requested)
        self.outcome = pill("", "ok")
        for widget in (self.two_way, self.asis_button, self.outcome):
            widget.setVisible(False)
        self._build()
        self.setVisible(False)

    def _build(self) -> None:
        figures = QVBoxLayout()
        figures.setSpacing(0)
        figures.addWidget(self.percent)
        figures.addWidget(self.version_label)
        pills = QHBoxLayout()
        pills.setSpacing(theme.SPACE[1])
        dimmed = QHBoxLayout(self.dimmed_box)
        dimmed.setContentsMargins(0, 0, 0, 0)
        dimmed.setSpacing(theme.SPACE[1])
        for state, _field, _prefix, dim in PILL_ORDER:
            (dimmed if dim else pills).addWidget(self._pills[state])
        pills.addWidget(self.nothing)
        pills.addSpacing(theme.SPACE[1])
        pills.addWidget(self.separator)
        pills.addSpacing(theme.SPACE[1])
        pills.addWidget(self.dimmed_box)
        pills.addStretch(1)
        below = QHBoxLayout()
        below.setSpacing(theme.SPACE[1])
        below.addWidget(self.strip, 1)
        below.addSpacing(theme.SPACE[2])
        for widget in (self.two_way, self.asis_button, self.outcome):
            below.addWidget(widget)
        below.addStretch(0)
        column = QVBoxLayout()
        column.setSpacing(theme.SPACE[1])
        column.addLayout(pills)
        column.addLayout(below)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[1], 0, theme.SPACE[1], 0)
        layout.setSpacing(theme.SPACE[3])
        layout.addLayout(figures)
        layout.addLayout(column, 1)

    def show_summary(self, summary: CaseSummary | None, judged: Sequence[Judged], *,
                     can_generate_asis: bool = True) -> None:
        """``summary`` of the judged version (None hides the bar) and its differences."""
        if summary is None:
            self.strip.set_judged([])
            self.setVisible(False)
            return
        self.percent.setText(strings.AVANZAMENTO_PERCENT.format(pct=percent(summary.avanzamento)))
        self.version_label.setText(strings.AVANZAMENTO_VERSION.format(version=summary.version))
        shown = _counts(summary, judged)
        for state, _field, prefix, _dim in PILL_ORDER:
            n = shown[state]
            plain = _count_text(prefix, LOOKS[state].icon, n) if n else ""
            self._plain[state] = plain
            self._pills[state].setText(glyph_html(plain))
            self._pills[state].setVisible(bool(n))
        main, dim = self.pill_groups()
        self.nothing.setVisible(not main)
        self.separator.setVisible(bool(dim))
        self.dimmed_box.setVisible(bool(dim))
        self.strip.set_judged(judged)
        self.strip.setVisible(bool(self.strip.segments()))
        self.two_way.setVisible(summary.two_way)
        self.asis_button.setVisible(summary.two_way)
        self.asis_button.setEnabled(can_generate_asis)
        self.setVisible(True)

    def set_outcome(self, folded: tuple[str, str, str] | None) -> None:
        """The folded verification outcome ``(short, full, tone)``, or None."""
        if folded is None:
            self.outcome.setVisible(False)
            return
        short, full, tone = folded
        self.outcome.setText(short)
        self.outcome.setToolTip(full)
        self.outcome.setProperty("pill", tone)
        theme.repolish(self.outcome)
        self.outcome.setVisible(True)

    def pill_groups(self) -> tuple[list[QLabel], list[QLabel]]:
        """The pills on show: (the counted ones, the dimmed ones)."""
        main = [self._pills[s] for s, _f, _p, dim in PILL_ORDER if not dim]
        dimmed = [self._pills[s] for s, _f, _p, dim in PILL_ORDER if dim]
        return ([p for p in main if not p.isHidden()], [p for p in dimmed if not p.isHidden()])

    def pill_texts(self) -> list[str]:
        """The plain texts of the pills on show, in order."""
        by_label = {id(label): self._plain.get(state, "") for state, label in self._pills.items()}
        main, dimmed = self.pill_groups()
        return [by_label[id(p)] for p in (*main, *dimmed)]
