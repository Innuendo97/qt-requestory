"""How a judged difference looks, everywhere in Officina (spec §7.1).

One :class:`Look` per *state* a difference can be in — its verdict, refined
by the "da verificare" mark and the "non risolta" flag, or its class when it
has no verdict (variabile, rumore). A look names theme **tokens**, never
colours, so the viewer, the list and the board re-derive the colours on a
theme switch. Qt-free.

=============  ===============  ============  ====  =====  =====
state          fill             edge          dash  px     glyph
=============  ===============  ============  ====  =====  =====
regressione    ``bad_bg``       ``bad``       no    1.5    ▲
non risolta    ``warn_bg``      ``warn``      no    1.5    ○!
da fare        ``warn_bg``      ``warn``      no    1.5    ○
in corso       ``progress_bg``  ``accent``    no    1.5    ◐
da verificare  —                ``ok``        yes   **2**  ✓?
fatta          — (underline)    ``ok``        no    1      ✓
tollerata      —                ``muted``     yes   1      ⊘
rumore         —                ``muted``     yes   1      ~
variabile      — (underline)    ``variable``  yes   1      {x}
=============  ===============  ============  ====  =====  =====

**"non risolta" (R31, R42)** is a flag on an open verdict, not a verdict:
on "da fare" and "in corso" it is the state ``non_risolta`` (worse than
either: the difference was promised done and is still here); on a
"regressione" the state stays ``regressione`` (never downgraded) and its
look carries the flag (``▲!``, "regressione · non risolta"). A marked
difference is "da verificare" whatever its flag.

**Totals (R44)**: the verdict pills count verdicts (a mark as "da
verificare"), the "non risolte" pill counts EVERY flagged difference
whatever its verdict — so a difference can be in two totals (the pill's
tooltip says so), and the pill, the outcome strip and the board agree.

"fatta" is drawn only on the target side and only when the fatte are shown
(the viewer's ``set_show_done``). A difference without verdict that is not a
variable or noise (the AS-IS view, phase-1 comparison) is neutral.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import CaseSummary, Judged

__all__ = ["LOOKS", "WORST_ORDER", "Look", "board_counts", "flagged", "look_for", "pill_counts", "state_of",
           "worst"]

#: Verdicts a "da verificare" mark can sit on (the mark is a promise on an open difference).
_OPEN = ("da_fare", "in_corso", "regressione")


@dataclass(frozen=True)
class Look:
    """Token names (``theme.Tokens`` fields), not colours."""

    fill: str | None
    edge: str
    dash: bool
    width: float
    icon: str
    label: str
    #: Drawn as a line under the words instead of a box around them.
    underline: bool = False
    #: The QSS pill tone (``QLabel[pill=...]``) of this state in lists, strip and board (R14).
    pill: str = "neutral"


LOOKS: dict[str, Look] = {
    "regressione": Look("bad_bg", "bad", False, 1.5, strings.VERDETTO_ICON_REGRESSIONE,
                        strings.VERDETTO_REGRESSIONE, pill="bad"),
    "non_risolta": Look("warn_bg", "warn", False, 1.5, strings.VERDETTO_ICON_NON_RISOLTA,
                        strings.VERDETTO_NON_RISOLTA, pill="warn"),
    "da_fare": Look("warn_bg", "warn", False, 1.5, strings.VERDETTO_ICON_DA_FARE,
                    strings.VERDETTO_DA_FARE, pill="warn"),
    "in_corso": Look("progress_bg", "accent", False, 1.5, strings.VERDETTO_ICON_IN_CORSO,
                     strings.VERDETTO_IN_CORSO, pill="progress"),
    "da_verificare": Look(None, "ok", True, 2.0, strings.VERDETTO_ICON_DA_VERIFICARE,
                          strings.VERDETTO_DA_VERIFICARE, pill="ok"),
    "fatta": Look(None, "ok", False, 1.0, strings.VERDETTO_ICON_FATTA, strings.VERDETTO_FATTA,
                  underline=True, pill="ok"),
    "tollerata": Look(None, "muted", True, 1.0, strings.VERDETTO_ICON_TOLLERATA,
                      strings.VERDETTO_TOLLERATA, pill="neutral"),
    "rumore": Look(None, "muted", True, 1.0, strings.VERDETTO_ICON_RUMORE, strings.VERDETTO_RUMORE,
                   pill="neutral"),
    "variabile": Look(None, "variable", True, 1.0, strings.VERDETTO_ICON_VARIABILE,
                      strings.VERDETTO_VARIABILE, underline=True, pill="variable"),
    "nessuno": Look("neutral_bg", "muted", False, 1.0, strings.VERDETTO_ICON_NESSUNO,
                    strings.VERDETTO_NESSUNO, pill="neutral"),
}


def state_of(j: Judged) -> str:
    """The key of :data:`LOOKS` for ``j``."""
    if j.verdict is None:
        return j.diff.klass if j.diff.klass in ("variabile", "rumore") else "nessuno"
    if j.marked and j.verdict in _OPEN:
        return "da_verificare"
    if j.unresolved and j.verdict in ("da_fare", "in_corso"):
        return "non_risolta"
    return j.verdict


def flagged(j: Judged) -> bool:
    """``j`` shows the "non risolta" flag: an open, unmarked difference whose
    mark was verified and that is still there (R31)."""
    return j.unresolved and not j.marked and j.verdict in _OPEN


def look_for(j: Judged) -> Look:
    state = state_of(j)
    look = LOOKS[state]
    if state == "regressione" and flagged(j):
        return replace(look, icon=look.icon + "!", label=strings.VERDETTO_FLAGGED.format(state=look.label))
    return look


def pill_counts(judged) -> dict[str, int]:
    """The case bar's totals (R44): each difference in its verdict's pill
    ("da verificare" when marked), and every flagged one ALSO in "non
    risolte" — the counting of ``CaseSummary`` (so :func:`board_counts` of
    the summary agrees)."""
    counts = dict.fromkeys(LOOKS, 0)
    for j in judged:
        state = state_of(j)
        counts[j.verdict if state == "non_risolta" else state] += 1
        counts["non_risolta"] += bool(j.unresolved and j.verdict in _OPEN)
    return counts


#: Worst first (spec §7.4): the board pill shows the first state present.
WORST_ORDER = ("regressione", "non_risolta", "da_fare", "in_corso", "da_verificare", "fatta")


def board_counts(summary: CaseSummary) -> dict[str, int]:
    """The case bar's totals (:func:`pill_counts`) from ``summary`` alone.

    The summary counts a marked difference both in its verdict and in
    ``da_verificare`` (R15); here the marks come out of the open verdicts,
    the MILDEST first (in corso, da fare, regressione) — the summary does not
    say which verdict a mark sits on, so the board never shows a case better
    than it may be; exact when nothing is marked or one open verdict is
    present. "non risolte" is ``summary.non_risolte`` as it is: every flagged
    difference, whatever its verdict (R44).
    """
    counts = {"regressione": summary.regressioni, "non_risolta": summary.non_risolte,
              "da_fare": summary.da_fare, "in_corso": summary.in_corso}
    marks = summary.da_verificare
    for state in ("in_corso", "da_fare", "regressione"):
        taken = min(marks, counts[state])
        counts[state] -= taken
        marks -= taken
    counts.update(da_verificare=summary.da_verificare, fatta=summary.fatte,
                  tollerata=summary.tollerate, variabile=summary.variabili,
                  rumore=summary.rumore)
    return counts


def worst(summary: CaseSummary) -> str:
    """The worst state present in ``summary`` (a :data:`WORST_ORDER` key), or
    ``""`` when nothing counts (no difference, or only tolerated / variables /
    noise). Counted like the case bar (:func:`board_counts`, R15): a marked
    difference is "da verificare", not its verdict."""
    counts = board_counts(summary)
    return next((state for state in WORST_ORDER if counts[state]), "")
