"""Placeholders of a target (phase 2.5, spec §3.3, §3.7; task A4).

A customer target often marks where a value goes: ``[xx]``, ``XXXX``,
``X,XXXX``, ``gg/mm/aaaa``, a leader of dots or underscores, or — in the
HTML mockups of an email — ``{{…}}``. :func:`is_placeholder` recognises a
word that is one (the ``segnaposto`` proof of ``variables``).

``{{…}}`` comes in two kinds (research C):

* a **value**: ``{{NOME}}``, ``{{CODICE_CLIENTE}}``, ``{{X,XXXX}}``,
  ``{{gg mese aaaa}}`` — capitals, digits, underscores and separators, or a
  format mask. :func:`rewrite` turns it into a dot leader in the target's
  keys, so the slots stage (``slots``) makes it a sure slot that swallows the
  generated value (a ``variabile`` with proof ``segnaposto``);
* a **conditional text**: ``{{Modulo Acme}}`` — the expected text, present
  only under some condition. :func:`rewrite` drops its braces, so the text
  compares as it is; when the generated document leaves it out, the second
  pass (``variables``) makes the missing text a ``variabile`` too.

Braces nest (``{{Quota fissa {{X_QF/X_QV}}}}``: a conditional
holding a value). Only the comparison KEYS change: the words keep their
original text (``{{NOME}}``), which is what ``Diff.nome`` shows.

Pure; stdlib only, no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
from collections.abc import Sequence

__all__ = ["LEADER", "is_conditional", "is_placeholder", "rewrite"]

#: What a value placeholder becomes in the keys: a leader (``slots``' sure slot).
LEADER = "...."

#: A word that is a placeholder (whole word, surrounding punctuation allowed).
_PLACEHOLDER = re.compile(
    r"^[(\[«\"']*(?:"
    r"\[[^\]\s]{0,12}\]"                         # [xx], [X], [ ]
    r"|X{3,}"                                    # XXXX
    r"|X+(?:[.,/]X+)+"                           # X,XXXX, XX.XXX,XX
    r"|(?:gg|dd)[/.\-](?:mm)[/.\-](?:aa|aaaa|yyyy)"  # gg/mm/aaaa
    r"|[._…]{4,}"                                # a leader
    r"|\{\{[^{}]*\}\}"                           # {{…}}
    r")[)\]»\"'.,;:]*$", re.IGNORECASE)
#: The inside of a VALUE placeholder: capitals, digits, underscores, separators, or a mask.
_VALUE = re.compile(r"^[A-Z0-9_/\s,.\-:€%]+$")
_MASK_WORDS = frozenset({"gg", "mm", "aa", "aaaa", "mese", "anno", "giorno", "xx", "xxx", "xxxx"})


def is_placeholder(text: str) -> bool:
    """Whether a target word marks where a value goes (module doc). The
    ``X`` masks must be capitals (a word «xxx» of a text is not one)."""
    text = text.strip()
    if not _PLACEHOLDER.match(text):
        return False
    core = text.strip("([«\"')]».,;:")
    if core[:1] in "xX" and text.lstrip("(«\"'")[:1] in "xX":   # an X mask, not [xx] or {{…}}
        return core.startswith("X")
    return True


def is_conditional(inner: str) -> bool:
    """Whether the inside of ``{{…}}`` is a conditional text (not a value)."""
    inner = " ".join(inner.split())
    if not inner:
        return False
    if _VALUE.match(inner) and any(c.isalnum() for c in inner):
        return False
    words = [w.casefold() for w in re.split(r"[\s/.\-]+", inner) if w]
    return not (words and all(w in _MASK_WORDS or set(w) <= set("x,.") for w in words))


def rewrite(keys: Sequence[str]) -> list[str]:
    """``keys`` (a target's comparison keys, in order) with each value
    ``{{…}}`` made a leader and the braces of each conditional one dropped
    (module doc). Keys without braces come back unchanged; a key that would
    be left empty keeps a lone leader character so no key disappears."""
    if not any("{{" in k or "}}" in k for k in keys):
        return list(keys)
    text = "\x00".join(keys)
    drop = [False] * len(text)
    value = [False] * len(text)
    stack: list[int] = []
    i = 0
    while i < len(text) - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            stack.append(i)
            i += 2
            continue
        if pair == "}}" and stack:
            start = stack.pop()
            inner = text[start + 2:i].replace("\x00", " ")
            if is_conditional(re.sub(r"\{\{.*?\}\}", "", inner)) or "{{" in inner:
                drop[start] = drop[start + 1] = drop[i] = drop[i + 1] = True
            else:
                for k in range(start, i + 2):
                    value[k] = True
            i += 2
            continue
        i += 1
    out: list[str] = []
    pos = 0
    for key in keys:
        chars: list[str] = []
        in_value = False
        for k in range(pos, pos + len(key)):
            if value[k]:
                if not in_value:
                    chars.append(LEADER)
                in_value = True
                continue
            in_value = False
            if not drop[k]:
                chars.append(text[k])
        out.append("".join(chars) or LEADER)
        pos += len(key) + 1
    return out
