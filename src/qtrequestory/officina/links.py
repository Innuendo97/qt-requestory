"""Masking signed links (Azure Blob SAS URLs) before they are shown or logged.

A documentGenerator payload may carry signed upload links (``attachmentUrl``
attributes, ``customData`` fields...). The payload itself is sent exactly as
it is — svil and coll hold only test data — but a signature (``sig=``) never
reaches a log, a message or a header shown to the user:

* :func:`mask` / :func:`mask_text` / :func:`mask_bytes` hide the signature
  (and the query) of any URL in a text shown to the user;
* :func:`host_only` / :func:`mask_text_for_log` reduce a URL to its host for
  the log.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

#: Any http(s) URL inside free text, up to the first whitespace or quote.
_URL_IN_TEXT = re.compile(r"""https?://[^\s"'<>]+""", re.IGNORECASE)
_MASKED_QUERY = "sig=***"
#: A SAS signature in any spelling a payload or an answer may carry it:
#: plain, percent-encoded, JSON-escaped, HTML-escaped. Masking is blunt on
#: purpose — hiding a little too much is harmless, showing a signature is not.
_SIG_ANY = re.compile(
    r"""sig(?:=|%3D|\\u003d|&#0*61;|&#x0*3d;|&equals;)[^&\s"'\\<>]+""", re.IGNORECASE)


def mask(url: str) -> str:
    """Scheme, host and path only; any query becomes ``sig=***``. Never raises."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return "<url non leggibile>"
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc = f"{netloc}:{port}"
    query = _MASKED_QUERY if parts.query else ""
    return _SIG_ANY.sub(_MASKED_QUERY, urlunsplit((parts.scheme, netloc, parts.path, query, "")))


def mask_text(text: str) -> str:
    """``text`` with every URL in it passed through :func:`mask`, then any
    signature left, in any encoding, replaced by ``sig=***``."""
    return _SIG_ANY.sub(_MASKED_QUERY, _URL_IN_TEXT.sub(lambda m: mask(m.group(0)), text))


def host_only(url: str) -> str:
    """Scheme and host only (``https://host/…``): for the log, where even a
    masked path may name a customer's container or document. Never raises."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return "<url non leggibile>"
    return f"{parts.scheme}://{host}/…" if host else "<url>"


def mask_text_for_log(text: str) -> str:
    """``text`` with every URL reduced to :func:`host_only` and any signature
    left, in any encoding, replaced by ``sig=***``."""
    return _SIG_ANY.sub(_MASKED_QUERY, _URL_IN_TEXT.sub(lambda m: host_only(m.group(0)), text))


def mask_bytes(data: bytes) -> bytes:
    """:func:`mask_text` for a raw body shown to the user (decoded leniently)."""
    return mask_text(data.decode("utf-8", errors="replace")).encode("utf-8")
