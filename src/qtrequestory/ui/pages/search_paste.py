"""Smart paste: recognise an entry name and split it into FDI + template key.

Pasting into the omnibox is how people actually arrive on this page. What they
have on the clipboard is almost never a bare uuid: it is a line copied out of a
daily log (``### <fdi>_<KEY>_<call id>.json``), a file name a colleague sent,
or the same thing without the header. Filling *both* filters from that one
paste removes the step where the key is retyped by hand — and mistyped.

The parsing itself is the core's (``core.daily.parse_entry_name``, re-exported
by ``ui/contracts.py``): the log's naming rules live there, with their edge
cases (keys containing underscores, keys starting with a digit,
``correlationId_vuoto`` entries with no FDI), and a second implementation here
would drift from them. This module only decides *whether* what was pasted is an
entry name at all, whether its FDI really is one, and — for a single typed
token — whether it reads as an FDI or as a template key.

Pure Python, no Qt: the widget calls it, the tests call it directly.
"""
from __future__ import annotations

import re

from qtrequestory.ui.contracts import parse_entry_name

__all__ = ["classify_token", "parse_pasted_entry"]

#: The ``### `` a daily file puts in front of every entry name.
HEADER_PREFIX = "### "
SUFFIX = ".json"
#: What an FDI token starts with: eight hex digits (a uuid, or a test-suffixed
#: uuid such as ``<uuid>-t15``). ``parse_entry_name`` splits on the first
#: underscore whatever is on its left, so ``2_KEY_ALPHA_<call id>`` — a key
#: that starts with a digit, logged without an FDI — would otherwise come back
#: as FDI "2".
_FDI_TOKEN = re.compile(r"[0-9a-f]{8}[0-9a-z-]*")
#: A dash-less hex token this long is an FDI prefix even without digits.
FDI_MIN_HEX = 8
#: Typed FDI (or FDI prefix): hex digits and dashes only.
_FDI_LIKE = re.compile(r"[0-9a-fA-F-]+")
#: Typed template key (or part of one): letters, digits, underscores.
_KEY_LIKE = re.compile(r"[A-Za-z0-9_]+")


def parse_pasted_entry(text: str) -> tuple[str | None, str] | None:
    """``(fdi, template_key)`` for an entry name, else None.

    Accepts ``<fdi>_<KEY>_<call id>`` with an optional ``### `` header, an
    optional ``.json`` suffix and any trailing lines (pasting a header *and* its
    body is one gesture). ``fdi`` is None for an entry that has none — and for
    one whose "FDI" is not shaped like one, in which case the whole name before
    the call id is the key.

    Returns None — meaning "let the field paste this as it is" — for anything
    else: a bare uuid, a bare template key, a sentence, and notably a name
    *without* a call id, which is not something the log ever produces and is
    more likely a key the user typed.
    """
    line = next((s for s in text.splitlines() if s.strip()), "").strip()
    if line.startswith(HEADER_PREFIX):
        line = line[len(HEADER_PREFIX):].strip()
    if line.lower().endswith(SUFFIX):
        line = line[: -len(SUFFIX)]
    if not line or any(c.isspace() for c in line):
        return None

    name = parse_entry_name(line)
    if name.call_id is None or not name.template_key:
        return None
    if name.fdi is not None and _FDI_TOKEN.fullmatch(name.fdi) is None:
        return None, line[: -(len(name.call_id) + 1)]
    return name.fdi, name.template_key


def _looks_like_fdi(token: str) -> bool:
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c.isalpha() for c in token)
    return "-" in token or len(token) >= FDI_MIN_HEX or (has_digit and has_letter)


def classify_token(text: str, *, prefer_key: bool = False) -> tuple[str, str] | None:
    """``("fdi", value)`` / ``("key", value)`` for one typed token, else None.

    An FDI (lowercased, the index stores FDIs that way) is hex digits and
    dashes that read like the start of a uuid: a dash, eight or more hex
    digits, or digits AND hex letters mixed. So "1a2b3c4d" is an FDI while
    "386" (a price-list key) and "CAFE" are keys. Letters, digits and
    underscores are a template key or part of one (uppercased).
    ``prefer_key`` (after Ctrl+K) makes every key-shaped token a key. Anything
    with a space or punctuation is neither and stays plain text.
    """
    token = text.strip()
    if not token:
        return None
    if not prefer_key and _FDI_LIKE.fullmatch(token) and _looks_like_fdi(token):
        return "fdi", token.lower()
    if _KEY_LIKE.fullmatch(token):
        return "key", token.upper()
    return None
