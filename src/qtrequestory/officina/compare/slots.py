"""Variable slots in the TARGET (spec §4.2 step 4).

A customer target is often a blank form: ``Località ..........`` is a place
the generated document fills with a value. Such a place becomes a *slot*: a
wildcard key :data:`SLOT` in the target's key sequence that, in the word
diff, swallows what the generated side puts there (:func:`absorb`). What a
slot swallows becomes a ``variabile`` difference, which never counts.

Two kinds:

* **sicuro** — a leader: a run of ≥4 ``.`` or ``_`` (``…`` arrives as three
  dots after NFKC), also split over several tokens. Punctuation sticks to the
  previous word in :func:`~qtrequestory.officina.compare.normalise.units`, so
  a leader usually arrives INSIDE its label's key (``"Località.........."``):
  the key is split into the label (kept as a normal key) and the SLOT.
  Punctuation hugging the leader (``(..........)``, ``..........,``) goes with
  the slot.
* **probabile** — a label followed by a line end or by another label, where
  the label ends with ``:``, or is a known form label (``N°``, ``CAP``,
  ``Provincia``, ``Località``, ``Data``, capitalised), or is a word ending with
  ``,`` alone on its line (a letter heading like «Città, »). The SLOT goes
  right after the label and stands for no word.

Line ends come from the words' boxes (``normalise.line_end``). Words
without boxes (an HTML compared through its DOM alone, or a block the print
could not place) have none: the caller then passes the ends it knows — the
block boundaries — as ``line_ends`` (:func:`find_slots`) and ``line_starts``
(:func:`absorb`), so a label alone in its block is a probable slot and a
slot never swallows the next block (final review I1).

The anchors of slots the user said are "non è una variabile" (the case's
``not_variables``) switch those slots off: a sure slot goes back to a normal
key holding its leader, a probable one disappears. :func:`slot_anchor` is the
ONE place a slot's anchor is made (ruling R2): the word diff gives the same
anchor to the ``variabile`` difference, so switching it off sticks.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from qtrequestory.officina.compare.anchors import disambiguate
from qtrequestory.officina.compare.model import Anchor, Word
from qtrequestory.officina.compare.normalise import line_end, normalise_token

__all__ = ["CONTEXT_KEYS", "MAX_PROBABLE_WORDS", "SLOT", "Slot", "absorb", "find_slots", "slot_anchor"]

#: The wildcard key a slot puts in the target key sequence (U+2063 cannot come
#: out of a PDF word: normalisation keeps it, but no font draws it).
SLOT = "\u2063SLOT"
#: A probable slot swallows at most this many generated units (one line).
MAX_PROBABLE_WORDS = 6
#: Keys of context on each side of a slot in its anchor.
CONTEXT_KEYS = 3

SlotKind = Literal["sicuro", "probabile"]


@dataclass(frozen=True)
class Slot:
    """A slot at ``index`` in the key list :func:`find_slots` returns.

    ``label`` is the key before it that names it ("" when none); ``words`` are
    the leader's original words (for highlights; empty for a probable slot);
    ``leader`` the normalised leader text ("" for a probable slot);
    ``anchor`` the slot's anchor numbered by occurrence (set by :func:`find_slots`)."""

    index: int
    kind: SlotKind
    label: str
    words: tuple[Word, ...]
    leader: str = ""
    anchor: Anchor | None = None


#: A leader run inside a normalised key.
_LEADER = re.compile(r"[._]{4,}")
#: Known form labels (casefolded, trailing ``:``/``.`` removed); must be capitalised in the text.
_KNOWN_LABELS = frozenset({"n°", "cap", "provincia", "località", "data"})
#: Opening punctuation at the end of a label belongs to the leader: ``Nome (......)``.
_OPENING = "([{\"'"


@dataclass
class _Entry:
    key: str
    members: tuple[Word, ...]
    kind: SlotKind | None = None
    label: str = ""
    leader: str = ""
    original: str = ""           # the key restored when a sure slot is switched off
    anchor: Anchor | None = None


def find_slots(keys: list[str], members: list[tuple[Word, ...]], disabled: Collection[Anchor],
               line_ends: Collection[int] = ()) -> tuple[list[str], list[tuple[Word, ...]], list[Slot]]:
    """The target's keys and members with each slot as a :data:`SLOT` key, and the slots.

    Pure: the inputs are not modified. ``disabled`` holds anchors (as
    :func:`slot_anchor` gives them) of slots to leave out. A switched-off sure
    slot goes back to a normal key holding its leader text — for a leader that
    was glued to its label (``"Località.........."``) that is a SEPARATE key
    (``"Località"``, ``".........."``): the diff then shows the leader as a
    ``testo`` difference, the intended effect of "non è una variabile".

    Every candidate slot (switched off or not) gets its anchor numbered by
    occurrence in target order (:func:`~qtrequestory.officina.compare.anchors.disambiguate`),
    so identical form rows have distinct anchors and switching one row off
    does not renumber the others.

    ``line_ends``: indices of ``keys`` a line ends after, on top of those the
    words' boxes show (see module doc).
    """
    starts = frozenset(id(members[k + 1][0]) for k in line_ends if k + 1 < len(members) and members[k + 1])
    entries: list[_Entry] = []
    for key, group in zip(keys, members, strict=True):
        _split_leaders(key, group, entries, starts)
    entries = _merge_adjacent(entries, starts)
    entries = _add_probable(entries, starts)
    candidate_keys, candidates = _collect(entries)
    anchors = disambiguate([_base_anchor(candidate_keys, slot) for slot in candidates])
    for slot, anchor in zip(candidates, anchors, strict=True):
        entries[slot.index].anchor = anchor
    if disabled:
        kept: list[_Entry] = []
        for entry in entries:
            if not entry.kind or entry.anchor not in disabled:
                kept.append(entry)
            elif entry.kind == "sicuro":
                kept.append(_Entry(entry.original, entry.members))
            # a switched-off probable slot stands for no word: dropped
        entries = kept
    out_keys, slots = _collect(entries)
    return out_keys, [e.members for e in entries], slots


def slot_anchor(keys: Sequence[str], slot: Slot) -> Anchor:
    """The anchor of ``slot`` in ``keys`` (the key list :func:`find_slots`
    returned, BEFORE noise rules): ``slot.anchor`` as :func:`find_slots`
    numbered it; for a Slot built by hand, the plain anchor below."""
    return slot.anchor if slot.anchor is not None else _base_anchor(keys, slot)


def _base_anchor(keys: Sequence[str], slot: Slot) -> Anchor:
    """The anchor before occurrence numbering.

    ``context`` = the :data:`CONTEXT_KEYS` nearest keys before and after the
    slot, joined by single spaces; other slots and leader runs are skipped, so
    switching a NEIGHBOUR slot off does not change this anchor.
    ``target_text`` = label and leader, space-separated.
    """
    before = _context(keys[slot.index - 1::-1] if slot.index else ())
    after = _context(keys[slot.index + 1:])
    context = " ".join([*reversed(before), *after])
    target_text = " ".join(part for part in (slot.label, slot.leader) if part)
    return Anchor("cambiato", "variabile", context, target_text)


def absorb(slot: Slot, right_keys: list[str], j: int, next_left_key: str | None,
           right_members: list[tuple[Word, ...]], line_starts: Collection[int] = ()) -> int:
    """How many generated units, from ``j``, ``slot`` swallows (0 = none).

    It takes units up to ``next_left_key`` (the target key after the slot;
    None = no stop word) and never past a line end. A probable slot takes at
    most :data:`MAX_PROBABLE_WORDS` and only a value on the same line as the
    unit before it (the label); a longer run is not a value: 0, and it stays
    a normal difference. ``line_starts``: indices of ``right_keys`` that
    start a line, on top of those the words' boxes show (see module doc).
    """
    end = j
    while end < len(right_keys):
        if next_left_key is not None and right_keys[end] == next_left_key:
            break
        if end > j and (end in line_starts or _breaks(right_members[end - 1], right_members[end])):
            break
        end += 1
    count = end - j
    if slot.kind == "probabile":
        if count > MAX_PROBABLE_WORDS:
            return 0
        if count and j > 0 and (j in line_starts or _breaks(right_members[j - 1], right_members[j])):
            return 0
    return count


# ------------------------------------------------------------ helpers ---

def _collect(entries: list[_Entry]) -> tuple[list[str], list[Slot]]:
    keys = [e.key for e in entries]
    slots = [Slot(i, e.kind, e.label, e.members if e.kind == "sicuro" else (), e.leader, e.anchor)
             for i, e in enumerate(entries) if e.kind]
    return keys, slots


def _context(keys: Sequence[str]) -> list[str]:
    out: list[str] = []
    for key in keys:
        if len(out) == CONTEXT_KEYS:
            break
        text = "" if key == SLOT else _LEADER.sub("", key)
        if any(c.isalnum() for c in text):
            out.append(text)
    return out


def _breaks(left: tuple[Word, ...], right: tuple[Word, ...], starts: Collection[int] = ()) -> bool:
    """Whether a line (or page) ends between two units (False if either has
    no word); ``starts`` = ids of words known to start a line."""
    return bool(left and right) and (id(right[0]) in starts or line_end(left[-1], right[0]))


def _split_leaders(key: str, group: tuple[Word, ...], out: list[_Entry], starts: Collection[int]) -> None:
    """Append ``key`` to ``out``, split into label keys and sure-slot entries."""
    runs = list(_LEADER.finditer(key))
    if not runs:
        out.append(_Entry(key, group))
        return
    # Pieces: [start, end, is_leader]. Text pieces without a letter or digit
    # (punctuation around a leader) join the leader before them, else after.
    pieces: list[list] = []
    pos = 0
    for run in runs:
        if run.start() > pos:
            pieces.append([pos, run.start(), False])
        pieces.append([run.start(), run.end(), True])
        pos = run.end()
    if pos < len(key):
        pieces.append([pos, len(key), False])
    merged: list[list] = []
    for piece in pieces:
        if merged and merged[-1][2] and (piece[2] or not _has_alnum(key[piece[0]:piece[1]])):
            merged[-1][1] = piece[1]           # leader absorbs a following leader or punctuation
        elif merged and piece[2] and not _has_alnum(key[merged[-1][0]:merged[-1][1]]):
            merged[-1][1], merged[-1][2] = piece[1], True   # punctuation before a leader
        else:
            merged.append(piece)
    for index, piece in enumerate(merged):
        if not piece[2] and index + 1 < len(merged):
            # a label's trailing opening punctuation goes to the leader after it
            while piece[1] > piece[0] + 1 and key[piece[1] - 1] in _OPENING:
                piece[1] -= 1
                merged[index + 1][0] -= 1
    spans = _word_spans(key, group)
    for index, (start, end, is_leader) in enumerate(merged):
        words = group if spans is None else tuple(w for w, (s, e) in zip(group, spans) if s < end and e > start)
        if not words:
            words = group
        text = key[start:end]
        if not is_leader:
            out.append(_Entry(text, words))
            continue
        label = ""
        if index > 0:
            label = key[merged[index - 1][0]:merged[index - 1][1]]
        elif out and out[-1].kind is None and out[-1].members and not _breaks(out[-1].members, words, starts):
            label = out[-1].key                # "Nome" then a key "(......)" on the same line
        out.extend(_per_line(_Entry(SLOT, words, "sicuro", label, text, text), starts))


def _per_line(entry: _Entry, starts: Collection[int]) -> list[_Entry]:
    """A sure slot whose leader words run over several lines: one slot per
    line (a slot swallows one line at most). The label stays with the first.
    Left whole when the leader text cannot be split by word."""
    if len(entry.members) < 2:
        return [entry]
    lines: list[list[Word]] = [[entry.members[0]]]
    for previous, word in zip(entry.members, entry.members[1:]):
        if id(word) in starts or line_end(previous, word):
            lines.append([])
        lines[-1].append(word)
    if len(lines) == 1:
        return [entry]
    tails = ["".join(normalise_token(w.text) for w in line) for line in lines[1:]]
    head = len(entry.leader) - sum(map(len, tails))
    if head <= 0 or not entry.leader.endswith("".join(tails)):
        return [entry]
    texts = [entry.leader[:head], *tails]
    return [_Entry(SLOT, tuple(line), "sicuro", entry.label if n == 0 else "", text, text)
            for n, (line, text) in enumerate(zip(lines, texts))]


def _word_spans(key: str, group: tuple[Word, ...]) -> list[tuple[int, int]] | None:
    """Each word's character span in ``key``; None when the key is not their plain concatenation."""
    texts = [normalise_token(w.text) for w in group]
    if "".join(texts) != key:
        return None
    spans, pos = [], 0
    for text in texts:
        spans.append((pos, pos + len(text)))
        pos += len(text)
    return spans


def _merge_adjacent(entries: list[_Entry], starts: Collection[int]) -> list[_Entry]:
    """Two sure slots in a row on one line are one leader."""
    out: list[_Entry] = []
    for entry in entries:
        last = out[-1] if out else None
        if (last and last.kind == "sicuro" and entry.kind == "sicuro" and not entry.label
                and not _breaks(last.members, entry.members, starts)):
            words = last.members + tuple(w for w in entry.members if w not in last.members)
            out[-1] = _Entry(SLOT, words, "sicuro", last.label, last.leader + entry.leader,
                             last.original + entry.original)
        else:
            out.append(entry)
    return out


def _add_probable(entries: list[_Entry], starts: Collection[int]) -> list[_Entry]:
    out: list[_Entry] = []
    for index, entry in enumerate(entries):
        out.append(entry)
        if entry.kind or not _is_probable(entries, index, starts):
            continue
        out.append(_Entry(SLOT, (), "probabile", entry.key))
    return out


def _is_probable(entries: list[_Entry], index: int, starts: Collection[int]) -> bool:
    entry = entries[index]
    following = entries[index + 1] if index + 1 < len(entries) else None
    if following is not None and following.kind:
        return False                           # the label of a leader, or already a slot
    line_end = following is None or _breaks(entry.members, following.members, starts)
    if _is_label(entry.key):
        return line_end or _is_label(following.key)
    if entry.key.endswith(",") and _has_alnum(entry.key):
        line_start = index == 0 or _breaks(entries[index - 1].members, entry.members, starts)
        return line_start and line_end
    return False


def _is_label(key: str) -> bool:
    """A key that names a field: ends with ``:``, or a capitalised known form label."""
    if not _has_alnum(key):
        return False
    if key.endswith(":"):
        return True
    return key[:1].isupper() and key.rstrip(":.").casefold() in _KNOWN_LABELS


def _has_alnum(text: str) -> bool:
    return any(c.isalnum() for c in text)
