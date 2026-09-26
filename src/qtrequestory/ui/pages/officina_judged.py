"""The comparison without verdicts drawn by the phase-2 viewer and list (the
AS-IS view, a core that cannot judge): only what the case's effective
profile counts, each row named by its operation and class — a style or
spacing change or a move is never shown as «x» → «x». The judged list itself
is ``officina_diffs.DiffPanel.show_judged`` (U3). Split from ``officina_case``
(size)."""
from __future__ import annotations

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Diff, Judged
from qtrequestory.ui.pages.officina_format import QUOTE_CHARS, elide
from qtrequestory.ui.pages.officina_rows import class_glyph, where_text

__all__ = ["count_line", "difference_lines", "unjudged"]


def unjudged(d: Diff) -> Judged:
    """An engine difference as a verdict-less :class:`Judged` (neutral look;
    variables and noise keep their class look)."""
    return Judged(d, None)


def count_line(diffs) -> str:
    """"3 differenze di testo", or "3 differenze" when some are not text
    (style, spacing, composition, links: a Stretto profile)."""
    n, text = len(diffs), all(d.klass == "testo" for d in diffs)
    if text:
        return strings.OFFICINA_DIFF_COUNT_ONE if n == 1 else strings.OFFICINA_DIFF_COUNT.format(n=n)
    return strings.OFFICINA_DIFF_COUNT_ANY_ONE if n == 1 else strings.OFFICINA_DIFF_COUNT_ANY.format(n=n)


def difference_lines(diff: Diff) -> tuple[str, str]:
    """Where and what, for the list without verdicts: ("pag. 1 · cambiato",
    "«a» → «b»"); a class other than testo is named ("pag. 1 · cambiato ·
    stile"), a difference with the same text on both sides (style, spacing,
    a move) quotes it once, the page count gives its detail."""
    _glyph, klass = class_glyph(diff)
    where = where_text(diff) + (f" · {klass}" if diff.klass != "testo" or diff.op == "spostato" else "")
    left, right = " ".join(diff.left_text.split()), " ".join(diff.right_text.split())
    if diff.op == "pagine" or (diff.detail and not (left or right)):
        what = diff.detail or strings.OFFICINA_DIFF_CHANGE.format(left=left, right=right)
    elif left == right or diff.klass in ("stile", "spaziatura"):
        what = strings.OFFICINA_DIFF_SAME_TEXT.format(text=elide(left or right))
    elif left and right:
        what = strings.OFFICINA_DIFF_CHANGE.format(left=elide(left, QUOTE_CHARS // 2),
                                                   right=elide(right, QUOTE_CHARS // 2))
    elif left:
        what = strings.OFFICINA_DIFF_ONLY_LEFT.format(text=elide(left))
    else:
        what = strings.OFFICINA_DIFF_ONLY_RIGHT.format(text=elide(right))
    return where, what
