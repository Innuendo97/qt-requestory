"""Smart paste: recognise an entry name and split it into FDI + template key.

Pasting into the FDI field is how people actually arrive on this page. What
they have on the clipboard is almost never a bare uuid: it is a line copied out
of a daily log (``### <fdi>_<KEY>_<call id>.json``), a file name a colleague
sent, or the same thing without the header. Filling *both* filters from that one
paste removes the step where the key is retyped by hand — and mistyped.

The parsing itself is the core's (``core.daily.parse_entry_name``, re-exported
by ``ui/contracts.py``): the log's naming rules live there, with their edge
cases (keys containing underscores, keys starting with a digit,
``correlationId_vuoto`` entries with no FDI), and a second implementation here
would drift from them. This module only decides *whether* what was pasted is an
entry name at all.

Pure Python, no Qt: the widget calls it, the tests call it directly.
"""
from __future__ import annotations

from qtrequestory.ui.contracts import parse_entry_name

__all__ = ["parse_pasted_entry"]

#: The ``### `` a daily file puts in front of every entry name.
HEADER_PREFIX = "### "
SUFFIX = ".json"


def parse_pasted_entry(text: str) -> tuple[str | None, str] | None:
    """``(fdi, template_key)`` for an entry name, else None.

    Accepts ``<fdi>_<KEY>_<call id>`` with an optional ``### `` header, an
    optional ``.json`` suffix and any trailing lines (pasting a header *and* its
    body is one gesture). ``fdi`` is None for an entry that has none.

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
    return name.fdi, name.template_key
