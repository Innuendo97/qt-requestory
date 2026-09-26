"""The board's "TO-BE contro target" pill of one case (spec §7.4).

Read from ``case.review.summary`` (``caso.json`` → ``riepilogo``, saved by
``compare_case`` whenever the case is compared) — the board never runs a
comparison of its own. Like ``sync_badge.badge_for``: one pure function,
:func:`board_badge`, returns what the cell shows.

* the **worst state** present (regressione > non risolta > da fare > in corso
  > da verificare > fatta), counted like the case bar (``board_counts``, R15:
  a mark is "da verificare", not also its verdict), with its count and the
  percentage: "▲ 1 regressione · 60%", in the state's tone (``Look.pill``);
* a **tooltip** with the full breakdown, in the case bar's order and words;
* "vN · da riconfrontare" (neutral) when the summary is of an older TO-BE
  than the latest one, or when the target or the AS-IS changed after it (an
  AS-IS generated after a two-way summary, a newer AS-IS or target), its
  tooltip still the breakdown of vN;
* no pill — a muted "nessuna differenza che conta" — when nothing counts;
* the phase-1 texts when there is no target or no TO-BE yet, and "da
  confrontare" when there are both but nothing was ever compared.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CaseSummary
from qtrequestory.ui.pages.officina_progress import PILL_ORDER, count_text, glyph_html, percent
from qtrequestory.ui.pages.officina_verdict_style import LOOKS, board_counts, worst

__all__ = ["BoardBadge", "board_badge", "breakdown_html", "plain"]


@dataclass(frozen=True)
class BoardBadge:
    """What the "TO-BE contro target" cell shows."""

    state: str      # a WORST_ORDER key, or "" (stale, never compared, nothing counts, no docs)
    tone: str       # the QSS pill tone
    text: str       # plain text (glyphs included)
    tooltip: str    # rich text
    pill: bool = True  # False: a muted label, not a pill


def breakdown_html(summary: CaseSummary, head: str | None = None) -> str:
    """Every non-zero count, one per line, in the case bar's order (the
    dimmed ones last), under ``head`` ("vN contro target · P%" by default)."""
    counts = board_counts(summary)
    if head is None:
        head = strings.BACHECA_TIP_HEAD.format(version=summary.version,
                                               pct=percent(summary.avanzamento))
    lines = [html.escape(head)]
    if summary.two_way:
        lines.append(glyph_html(strings.BACHECA_TIP_TWO_WAY))
    lines += [glyph_html(count_text(state, counts[state]))
              for state, _field, _prefix, _dim in PILL_ORDER if counts[state]]
    if counts["non_risolta"]:  # R44: also in their verdict's total
        lines.append(html.escape(strings.AVANZAMENTO_NON_RISOLTA_TIP))
    return "<br>".join(lines)


def plain(rich: str) -> str:
    """The text of a :func:`breakdown_html` tooltip, one line per line."""
    return html.unescape(re.sub(r"<[^>]+>", "", rich.replace("<br>", "\n")))


def board_badge(case) -> BoardBadge:
    """The pill of ``case`` (a ``Case``: ``target()``, ``latest_tobe()``,
    ``review.summary``)."""
    if case.target() is None:
        return BoardBadge("", "neutral", strings.OFFICINA_PILL_NO_TARGET, "")
    latest = case.latest_tobe()
    if latest is None:
        return BoardBadge("", "neutral", strings.OFFICINA_PILL_NO_TOBE, "")
    summary: CaseSummary | None = case.review.summary
    if summary is None:
        return BoardBadge("", "neutral", strings.BACHECA_NOT_COMPARED,
                          strings.BACHECA_NOT_COMPARED_TIP.format(latest=latest.number))
    head = None
    if summary.version < latest.number:
        head = strings.BACHECA_STALE_TIP.format(version=summary.version, latest=latest.number)
    elif _inputs_changed(case, summary):
        head = strings.BACHECA_STALE_INPUTS_TIP.format(version=summary.version)
    if head is not None:
        return BoardBadge("", "neutral", strings.BACHECA_STALE.format(version=summary.version),
                          breakdown_html(summary, head))
    state = worst(summary)
    tip = breakdown_html(summary)
    if not state:
        return BoardBadge("", "neutral", strings.BACHECA_NOTHING, tip, pill=False)
    counts = board_counts(summary)
    text = strings.BACHECA_PILL.format(counts=count_text(state, counts[state]),
                                       pct=percent(summary.avanzamento))
    return BoardBadge(state, LOOKS[state].pill, text, tip)


def _inputs_changed(case, summary: CaseSummary) -> bool:
    """The target or the AS-IS is not the one ``summary`` was computed with:
    an AS-IS exists now for a two-way summary (or is gone for a three-way
    one), or one of them was created after the summary (to the second: the
    summary's time has no fraction)."""
    asis = case.asis()
    if summary.two_way != (asis is None):
        return True
    try:
        when = datetime.fromisoformat(summary.when)
    except (TypeError, ValueError):
        return False
    for version in (case.target(), asis):
        created = getattr(version, "created", None)
        if created is None:
            continue
        try:
            if created.replace(microsecond=0, tzinfo=None) > when.replace(tzinfo=None):
                return True
        except (AttributeError, TypeError):
            continue
    return False
