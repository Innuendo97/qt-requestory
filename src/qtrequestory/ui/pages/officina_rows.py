"""What the differences list shows (spec §7.2): tabs, row order, and each
row's header, snippet and notes. No widgets here (``officina_diffs`` draws them).

Tabs, with their counts::

    Da guardare   regressioni, non risolte, da fare, in corso (unmarked); then a
                  "DA VERIFICARE" group with the marked ones (not counted)
    Da verificare the marked ones ("segnate fatte", waiting for a newer TO-BE)
    Fatte · Tollerate · Variabili · Tutte (everything, noise included)

In "Da guardare" the non risolte come first (spec §5.3: "in cima"), then
document order (page, top, left — the order of the verdict strip and of the
page); every other tab is in document order.

**The snippet** is where a tiny change must be unmissable: the target text
and the generated one are merged — the text around the change once, the
target's changed characters struck (``bad`` on ``bad_bg``), the generated
ones **bold**, and, when only PART of the text changed, on the ``mark_yellow``
of the page marks with the paper ink (dark in both modes: the yellow is bright
in both). So "abilitata" → "abilitato" reads ``abilitat~~a~~**o**``. The
characters come from ``Diff.left_spans`` / ``right_spans``; when the two sides'
unchanged parts do not line up, the two texts are shown one after the other
("target → generated"), each with its own changed characters marked; when
the two texts are equal (a link, an attribute) the text is shown plain and the
row's notes say what changed. Long unchanged stretches are elided around the
change.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html import escape

from PySide6.QtCore import Qt

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Anchor, Diff, Judged
from qtrequestory.ui.pages.officina_verdict_style import flagged, state_of

__all__ = ["CONTEXT_WORDS", "OPEN_STATES", "REVIEW_KEYS", "TABS", "actions_for", "class_glyph",
           "fit_context", "in_document_order", "notes_for", "row_plain", "snippet_html",
           "snippet_plain", "snippet_text", "snippet_width", "tab_counts", "tab_of", "tab_rows",
           "where_text"]

#: F / T / V with no modifier, in the list and in the viewers: what ``actions_for`` names.
REVIEW_KEYS = {Qt.Key.Key_F: "fatta", Qt.Key.Key_T: "tollera", Qt.Key.Key_V: "non_variabile"}

TABS = ("guardare", "verificare", "fatte", "tollerate", "variabili", "tutte")
#: The states "Da guardare" lists (the marked ones follow in their own group).
OPEN_STATES = ("non_risolta", "regressione", "da_fare", "in_corso")
_TAB_STATES = {
    "guardare": OPEN_STATES,
    "verificare": ("da_verificare",),
    "fatte": ("fatta",),
    "tollerate": ("tollerata",),
    "variabili": ("variabile",),
}
#: Characters of unchanged text kept on each side of a change.
CONTEXT = 24
#: A changed run longer than this keeps its head and tail.
LONG = 80
QUOTE = 40
#: Target words of context shown on each side of the change, at most (R33).
CONTEXT_WORDS = 4

_GLYPHS = {"testo": "Aa", "composizione": "▦", "stile": "¶", "spaziatura": "↔",
           "variabile": "{x}", "rumore": "~",
           "link": "🔗︎"}  # + U+FE0E: drawn as text in the chip's colour, not as an emoji
_CLASS_NAMES = {"testo": strings.ELENCO_CLASS_TESTO, "composizione": strings.ELENCO_CLASS_COMPOSIZIONE,
                "stile": strings.ELENCO_CLASS_STILE, "spaziatura": strings.ELENCO_CLASS_SPAZIATURA,
                "variabile": strings.ELENCO_CLASS_VARIABILE, "rumore": strings.ELENCO_CLASS_RUMORE,
                "link": strings.ELENCO_CLASS_LINK}
_OPS = {"mancante": strings.ELENCO_OP_MANCANTE, "in_piu": strings.ELENCO_OP_IN_PIU,
        "cambiato": strings.ELENCO_OP_CAMBIATO, "spostato": strings.ELENCO_OP_SPOSTATO,
        "sezione_assente": strings.ELENCO_OP_SEZIONE_ASSENTE,
        "sezione_in_piu": strings.ELENCO_OP_SEZIONE_IN_PIU, "pagine": strings.ELENCO_OP_PAGINE}


# -- tabs -------------------------------------------------------------------------

def _position(j: Judged) -> tuple[float, float, float]:
    words = j.diff.left or j.diff.right
    if not words:
        return (float("inf"), 0.0, 0.0)  # no place on the page (a link): at the end
    return (float(words[0].page), words[0].y0, words[0].x0)


def in_document_order(judged: Sequence[Judged]) -> list[Judged]:
    """All of ``judged`` by page, top, left (stable)."""
    ranked = sorted(enumerate(judged), key=lambda r: (_position(r[1]), r[0]))
    return [j for _i, j in ranked]


def tab_of(j: Judged) -> str:
    """The tab a difference belongs to besides "Tutte" ("tutte" for noise / no verdict)."""
    state = state_of(j)
    return next((tab for tab, states in _TAB_STATES.items() if state in states), "tutte")


def tab_counts(judged: Sequence[Judged]) -> dict[str, int]:
    counts = dict.fromkeys(TABS, 0)
    for j in judged:
        tab = tab_of(j)
        if tab != "tutte":
            counts[tab] += 1
    counts["tutte"] = len(judged)
    return counts


def tab_rows(tab: str, judged: Sequence[Judged]) -> list[Judged | None]:
    """The rows of ``tab``; ``None`` = the "DA VERIFICARE" group header."""
    ordered = in_document_order(judged)
    if tab == "tutte":
        return list(ordered)
    rows: list[Judged | None] = [j for j in ordered if tab_of(j) == tab]
    if tab == "guardare":
        rows.sort(key=lambda j: not flagged(j))  # stable: the non risolte in cima
        marked = [j for j in ordered if tab_of(j) == "verificare"]
        if marked:
            rows += [None, *marked]
    return rows


# -- header -------------------------------------------------------------------------

def class_glyph(diff: Diff) -> tuple[str, str]:
    """(glyph, class name) — a move is ⇄ whatever its class."""
    if diff.op == "spostato":
        return "⇄", strings.ELENCO_CLASS_SPOSTATO
    return _GLYPHS.get(diff.klass, "·"), _CLASS_NAMES.get(diff.klass, diff.klass)


def where_text(diff: Diff) -> str:
    """"pag. 1 · cambiato", or just the operation for a difference without boxes."""
    op = _OPS.get(diff.op, diff.op)
    words = diff.left or diff.right
    return strings.ELENCO_WHERE.format(page=words[0].page + 1, op=op) if words else op


# -- snippet ------------------------------------------------------------------------

def _clean(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ").replace("\t", " ")


def _split(text: str, spans: Sequence[tuple[int, int]]) -> list[str]:
    """``[same0, changed0, same1, ..., sameN]`` (always odd length)."""
    parts, pos = [], 0
    for start, end in sorted((max(0, s), min(len(text), e)) for s, e in spans):
        start = max(start, pos)
        if end < start:
            continue
        parts += [text[pos:start], text[start:end]]
        pos = end
    parts.append(text[pos:])
    return parts


def _pieces(diff: Diff) -> tuple[list[tuple[str, str]], bool]:
    """``([(kind, text)], partial)``: kinds "same", "del", "ins", "to" (the
    arrow between two unaligned texts); ``partial`` = some of the generated
    text is unchanged (then its changed characters go on yellow)."""
    left, right = _clean(diff.left_text), _clean(diff.right_text)
    if left == right:  # a link or attribute: the visible text did not change
        return ([("same", left)] if left else []), False
    lp, rp = _split(left, diff.left_spans), _split(right, diff.right_spans)
    if not left or not right:
        kind, text = ("del", left) if left else ("ins", right)
        return ([(kind, text)] if text else []), False
    partial = bool("".join(rp[0::2]).strip())
    if len(lp) == len(rp) and lp[0::2] == rp[0::2]:
        out: list[tuple[str, str]] = []
        for k in range(0, len(lp) - 1, 2):
            gone, made, after = lp[k + 1], rp[k + 1], lp[k + 2]
            out.append(("same", lp[k]))
            out.append(("del", gone))
            if gone and made and _word_edge(lp[k], True) and _word_edge(after, False):
                out.append(("same", " "))  # two whole words: "Acme-Servizi Acme"
            out.append(("ins", made))
        out.append(("same", lp[-1]))
        return [p for p in out if p[1]], partial
    out = [("del" if k % 2 else "same", t) for k, t in enumerate(lp)]
    out.append(("to", " → "))
    out += [("ins" if k % 2 else "same", t) for k, t in enumerate(rp)]
    return [p for p in out if p[1]], partial


def _word_edge(text: str, before: bool) -> bool:
    if not text:
        return True
    return (text[-1] if before else text[0]).isspace()


def _elide_same(pieces: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out = []
    last = len(pieces) - 1
    for i, (kind, text) in enumerate(pieces):
        if kind == "same" and len(text) > CONTEXT:
            if i == 0:
                text = "…" + text[-CONTEXT:]
            elif i == last:
                text = text[:CONTEXT] + "…"
            elif len(text) > 2 * CONTEXT + 3:
                text = text[:CONTEXT] + " … " + text[-CONTEXT:]
        elif kind in ("del", "ins") and len(text) > LONG:
            half = LONG // 2 - 2
            text = text[:half] + " … " + text[-half:]
        out.append((kind, text))
    return out


def _framed(diff: Diff, before: int, after: int) -> tuple[list[tuple[str, str]], bool]:
    """The change's pieces with up to ``before`` / ``after`` words of the
    target context around them (R33); "gap" = an ellipsis where words were cut."""
    pieces, partial = _pieces(diff)
    pieces = _elide_same(pieces)
    words_before, words_after = diff.context_before.split(), diff.context_after.split()
    shown_before = words_before[max(0, len(words_before) - before):] if before > 0 else []
    shown_after = words_after[:max(0, after)]
    out: list[tuple[str, str]] = []
    if len(shown_before) < len(words_before):
        out.append(("gap", "… "))
    if shown_before:
        out.append(("ctx", " ".join(shown_before) + " "))
    out += pieces
    if shown_after:
        out.append(("ctx", " " + " ".join(shown_after)))
    if len(shown_after) < len(words_after):
        out.append(("gap", " …"))
    return out, partial


def snippet_html(diff: Diff, t: theme.Tokens, *, before: int = CONTEXT_WORDS,
                 after: int = CONTEXT_WORDS) -> str:
    """Rich text of ``diff``'s snippet in the colours of ``t``: the context
    words in the normal ink, the struck target run in PAPER colours in both
    themes (R34: a lone struck letter must read on dark chrome too) right
    against the inserted run — no gap: a hair space rendered as wide as a
    space and "senpelmo a" read as two words (U4); the pink and the yellow
    tell the letters apart — bold (on yellow when partial); a link's own
    text is underlined, so it stands apart from the context around it."""
    pieces, partial = _framed(diff, before, after)
    paper = theme.LIGHT  # the struck run and the yellow carry paper colours in both modes
    link = diff.klass == "link"  # the link's own text underlined, the context not (U4)
    out = []
    for kind, text in pieces:
        safe = escape(text, quote=False)
        if link and kind in ("same", "del", "ins") and text.strip():
            safe = f"<u>{safe}</u>"
        if kind == "del":
            out.append(f"<s style='color:{paper.bad};background-color:{paper.bad_bg};"
                       f"font-weight:700'>{safe}</s>")
        elif kind == "ins" and partial:
            out.append(f"<b style='color:{paper.text};background-color:{t.mark_yellow}'>{safe}</b>")
        elif kind == "ins":
            out.append(f"<b>{safe}</b>")
        elif kind in ("to", "gap"):
            out.append(f"<span style='color:{t.muted}'>{safe}</span>")
        else:
            out.append(safe)
    return "".join(out)


def snippet_text(diff: Diff, *, before: int = CONTEXT_WORDS, after: int = CONTEXT_WORDS) -> str:
    """The visible characters of the snippet (to measure it against the row width)."""
    return "".join(text for _kind, text in _framed(diff, before, after)[0])


def snippet_width(diff: Diff, measure: Callable[[str], float],
                  measure_bold: Callable[[str], float] | None = None, *,
                  before: int = CONTEXT_WORDS, after: int = CONTEXT_WORDS) -> float:
    """The snippet's width, each piece measured in the weight it is drawn
    with: the changed runs (struck, inserted) in bold, the rest normal."""
    bold = measure_bold or measure
    return sum((bold if kind in ("del", "ins") else measure)(text)
               for kind, text in _framed(diff, before, after)[0])


def fit_context(diff: Diff, width: float, measure: Callable[[str], float],
                measure_bold: Callable[[str], float] | None = None) -> tuple[int, int]:
    """How many context words (before, after) keep the snippet within
    ``width`` (:func:`snippet_width`; ``measure_bold`` for the changed runs,
    ``measure`` for everything when omitted): words are dropped from the
    longer side first; the change itself always stays (it may wrap)."""
    before = after = CONTEXT_WORDS
    while (snippet_width(diff, measure, measure_bold, before=before, after=after) > width
           and (before or after)):
        if before >= after and before > 0:
            before -= 1
        else:
            after -= 1
    return before, after


def snippet_plain(diff: Diff, *, before: int = CONTEXT_WORDS, after: int = CONTEXT_WORDS) -> str:
    """The snippet as text: each change as ``[target→generated]``."""
    pieces = _framed(diff, before, after)[0]
    out: list[str] = []
    gone: list[str] = []
    made: list[str] = []

    def flush() -> None:
        if gone or made:
            out.append(f"[{''.join(gone)}→{''.join(made)}]")
            gone.clear()
            made.clear()

    for i, (kind, text) in enumerate(pieces):
        if kind == "del":
            if made:
                flush()
            gone.append(text)
        elif kind == "ins":
            made.append(text)
        elif (text == " " and gone and not made and i + 1 < len(pieces)
              and pieces[i + 1][0] == "ins"):
            continue  # the space between two whole words belongs to the change
        else:
            flush()
            out.append(text)
    flush()
    return "".join(out)


# -- notes -----------------------------------------------------------------------

def _quote(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTE else text[:QUOTE - 1] + "…"


def notes_for(j: Judged, version: int, unresolved_since: Mapping[Anchor, int]) -> list[tuple[str, str]]:
    """``[(text, tone)]`` under the snippet; tone "bad" or "muted"."""
    state = state_of(j)
    out: list[tuple[str, str]] = []
    if flagged(j):  # R31: on da fare, in corso or regressione
        since = unresolved_since.get(j.diff.anchor)
        out.append((strings.ELENCO_NON_RISOLTA.format(n=since, m=version) if since is not None
                    else strings.ELENCO_NON_RISOLTA_NO_N.format(m=version), "bad"))
    if j.verdict == "in_corso" and state in ("in_corso", "non_risolta") and j.previous_text:
        out.append((strings.ELENCO_IN_CORSO.format(before=_quote(j.previous_text),
                                                   now=_quote(j.diff.right_text)), "muted"))
    elif state == "regressione":
        out.append((strings.ELENCO_REGRESSIONE, "muted"))
    elif state == "tollerata" and j.tolerated_note:
        out.append((strings.ELENCO_TOLLERATA_NOTE.format(note=_quote(j.tolerated_note)), "muted"))
    if j.diff.detail:
        out.append((j.diff.detail, "muted"))
    if not (j.diff.left or j.diff.right):
        out.append((strings.ELENCO_ONLY_LIST, "muted"))
    return out


def row_plain(j: Judged, label: str, version: int, since: Mapping[Anchor, int]) -> str:
    """One row as text: header, snippet, notes (``DiffPanel.texts``)."""
    glyph, _name = class_glyph(j.diff)
    lines = [f"{label} · {glyph} · {where_text(j.diff)}", snippet_plain(j.diff)]
    return "\n".join(lines + [text for text, _tone in notes_for(j, version, since)])


# -- keyboard ----------------------------------------------------------------------

def actions_for(j: Judged) -> set[str]:
    """What F / T / V can do on ``j``: "fatta" (mark, or remove the mark),
    "tollera" (tolerate, or stop tolerating), "non_variabile" (a variable
    that is not one, or back to a variable)."""
    state = state_of(j)
    out = set()
    if state in OPEN_STATES or state == "da_verificare":
        out.add("fatta")
    if state in OPEN_STATES or state == "tollerata":
        out.add("tollera")
    if j.diff.klass == "variabile" or j.diff.anchor.klass == "variabile":
        out.add("non_variabile")
    return out
