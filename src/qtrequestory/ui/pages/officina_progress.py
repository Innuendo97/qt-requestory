"""The compact progress of the case bar (spec §5 and §7.1; phase 2.5 U2, draft "f25-caso-v2").

::

    60%  ▲ 1  ○! 1  ○ 3  ◐ 1  ✓? 1  ✓ 6 | ⊘ 3  {x} 14  ~ 2   ⚠ a due vie  v2: 1/2 risolte

* the **percentage** is ``CaseSummary.avanzamento`` (fatte over what counts;
  a "da verificare" still counts with its verdict, spec §5.1); its tooltip
  says the formula and "vN contro target";
* the **pills** (glyph and number; the full words — "3 da fare" — are the
  tooltip), in the spec's order — regressioni · non risolte · da fare ·
  in corso · da verificare · fatte — then, apart and dimmed, tollerate ·
  variabili · rumore; a zero count has no pill. With the judged differences
  at hand the pills count each difference in its verdict (a marked one as
  "da verificare" only: the summary, R15, counts a mark in both), and the
  "non risolte" pill counts every flagged difference whatever its verdict
  (R44: it may be in two totals; its tooltip says so). Tones are
  ``officina_verdict_style.Look.pill`` (R14), so a verdict has the same
  colour here, in the list and on the board;
* the AS-IS view (:meth:`ProgressBar.show_total`) has one "da fare" pill:
  its differences from the target are the whole work (same visual language);
* the verdict strip of phase 2 (``officina_strip.VerdictStrip``) is no longer
  in the bar: the minimap beside each document does its job.

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
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CaseSummary, Judged
from qtrequestory.ui.pages.officina_strip import VerdictStrip, document_order  # re-exported
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
    """The compact progress of the case bar (phase 2.5, U2), on one line:
    the percentage (its tooltip: the formula and "vN contro target"), one
    small pill per non-zero state (glyph and number; the full words are its
    tooltip), the dimmed ones apart, the two-way pill with "Genera l'AS-IS",
    and the outcome of a verification (short; the whole sentence as its
    tooltip). Hidden while there is nothing to show (a TO-BE not judged)."""

    asis_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.percent = QLabel()
        theme.set_role(self.percent, "section")
        self.nothing = QLabel(strings.AVANZAMENTO_NOTHING)
        theme.set_role(self.nothing, "muted")
        self._pills: dict[str, QLabel] = {}
        self._plain: dict[str, str] = {}
        self._extra_tip: dict[str, str] = {"non_risolta": strings.AVANZAMENTO_NON_RISOLTA_TIP}
        for state, *_rest in PILL_ORDER:
            label = pill("", LOOKS[state].pill)
            label.setTextFormat(Qt.TextFormat.RichText)
            self._pills[state] = label
        self.separator = QFrame()
        self.separator.setFixedSize(1, 16)
        theme.set_role(self.separator, "vrule")
        self.dimmed_box = QWidget()
        effect = QGraphicsOpacityEffect(self.dimmed_box)
        effect.setOpacity(DIMMED_OPACITY)
        self.dimmed_box.setGraphicsEffect(effect)
        self.two_way = pill("", "warn", strings.REVISIONE_TWO_WAY)
        self.two_way.setAccessibleName(strings.REVISIONE_TWO_WAY)
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
        mid = Qt.AlignmentFlag.AlignVCenter  # pills keep their height in the 36 px bar
        dimmed = QHBoxLayout(self.dimmed_box)
        dimmed.setContentsMargins(0, 0, 0, 0)
        dimmed.setSpacing(theme.SPACE[0])
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE[0])
        row.addWidget(self.percent, 0, mid)
        row.addSpacing(theme.SPACE[0])
        for state, _field, _prefix, dim in PILL_ORDER:
            (dimmed if dim else row).addWidget(self._pills[state], 0, mid)
        row.addWidget(self.nothing, 0, mid)
        row.addSpacing(theme.SPACE[0])
        row.addWidget(self.separator, 0, mid)
        row.addSpacing(theme.SPACE[0])
        row.addWidget(self.dimmed_box, 0, mid)
        row.addSpacing(theme.SPACE[1])
        for widget in (self.two_way, self.asis_button, self.outcome):
            row.addWidget(widget, 0, mid)

    def show_summary(self, summary: CaseSummary | None, judged: Sequence[Judged], *,
                     can_generate_asis: bool = True) -> None:
        """``summary`` of the judged version (None hides the bar) and its differences."""
        if summary is None:
            self.setVisible(False)
            return
        self.percent.setText(strings.AVANZAMENTO_PERCENT.format(pct=percent(summary.avanzamento)))
        self.percent.setToolTip(strings.AVANZAMENTO_VERSION.format(version=summary.version)
                                + "\n" + strings.AVANZAMENTO_TOOLTIP)
        self.percent.setAccessibleName(strings.BARRA_PERCENT_NAME.format(
            pct=percent(summary.avanzamento), version=summary.version))
        self.percent.setVisible(True)
        self._set_counts(_counts(summary, judged))
        self.two_way.setVisible(summary.two_way)
        self.asis_button.setVisible(summary.two_way)
        self.asis_button.setEnabled(can_generate_asis)
        self.setVisible(True)

    def show_total(self, n: int) -> None:
        """The AS-IS view (same visual language, spec §5): its ``n`` differences
        from the target are the whole work, one "da fare" pill; no percentage."""
        counts = dict.fromkeys(LOOKS, 0)
        counts["da_fare"] = n
        self.percent.setVisible(False)
        self._set_counts(counts)
        if n:
            self._pills["da_fare"].setToolTip(strings.BARRA_ASIS_TOTAL_TIP.format(n=n))
        for widget in (self.two_way, self.asis_button, self.outcome):
            widget.setVisible(False)
        self.setVisible(True)

    def _set_counts(self, shown: dict[str, int]) -> None:
        for state, _field, prefix, _dim in PILL_ORDER:
            n = shown[state]
            plain = _count_text(prefix, LOOKS[state].icon, n) if n else ""
            self._plain[state] = plain
            label = self._pills[state]
            label.setText(glyph_html(strings.BARRA_PILL.format(icon=LOOKS[state].icon, n=n)) if n else "")
            tip = "\n".join(t for t in (plain, self._extra_tip.get(state, "")) if t)
            label.setToolTip(tip)
            label.setAccessibleName(_count_text(prefix, "", n).strip() if n else "")  # "3 da fare"
            label.setVisible(bool(n))
        main, dim = self.pill_groups()
        self.nothing.setVisible(not main)
        self.separator.setVisible(bool(dim))
        self.dimmed_box.setVisible(bool(dim))

    def set_marks_tip(self, text: str) -> None:
        """The "da verificare" sentence (publish and regenerate) under that pill's tooltip."""
        if text:
            self._extra_tip["da_verificare"] = text
        else:
            self._extra_tip.pop("da_verificare", None)
        label = self._pills["da_verificare"]
        label.setToolTip("\n".join(t for t in (self._plain.get("da_verificare", ""), text) if t))

    def set_outcome(self, folded: tuple[str, str, str] | None) -> None:
        """The verification outcome ``(short, full, tone)``, or None."""
        if folded is None:
            self.outcome.setVisible(False)
            return
        short, full, tone = folded
        self.outcome.setText(short)
        self.outcome.setToolTip(full)
        self.outcome.setAccessibleName(full)
        self.outcome.setProperty("pill", tone)
        theme.repolish(self.outcome)
        self.outcome.setVisible(True)

    def pill_groups(self) -> tuple[list[QLabel], list[QLabel]]:
        """The pills on show: (the counted ones, the dimmed ones)."""
        main = [self._pills[s] for s, _f, _p, dim in PILL_ORDER if not dim]
        dimmed = [self._pills[s] for s, _f, _p, dim in PILL_ORDER if dim]
        return ([p for p in main if not p.isHidden()], [p for p in dimmed if not p.isHidden()])

    def pill_texts(self) -> list[str]:
        """The full words of the pills on show (their tooltips' first line), in order."""
        by_label = {id(label): self._plain.get(state, "") for state, label in self._pills.items()}
        main, dimmed = self.pill_groups()
        return [by_label[id(p)] for p in (*main, *dimmed)]

    def pill_for(self, state: str) -> QLabel:
        return self._pills[state]
