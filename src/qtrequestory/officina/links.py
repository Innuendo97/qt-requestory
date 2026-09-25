"""Upload links (Azure Blob SAS URLs) inside a documentGenerator payload.

A real payload carries, in ``documents[].attributes[]`` and in the nested
``dossierItems[].childItems[].documents[].attributes[]``, a pair of attributes
``{"key": "attachmentId"}`` / ``{"key": "attachmentUrl", "value": <SAS URL>}``.
The SAS URL is a *write* permission on a real blob: replaying a payload whose
link is still valid would overwrite a real customer's document. So:

* :func:`find_links` finds every such link, wherever it sits, with its expiry
  (``se=``) and whether it grants writing (``sp=``);
* :func:`remove_links` returns a copy without those attributes (policy
  "Rimuovi", the default after the probe of spec §11);
* :func:`mask` / :func:`mask_text` hide the signature of any URL before it
  reaches a log, a message or a header shown to the user.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import copy
import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit, urlunsplit

#: The attribute keys :func:`remove_links` drops (compared case-insensitively).
LINK_KEY = "attachmenturl"
LINK_KEYS = frozenset({LINK_KEY, "attachmentid"})

#: Any http(s) URL inside free text, up to the first whitespace or quote.
_URL_IN_TEXT = re.compile(r"""https?://[^\s"'<>]+""", re.IGNORECASE)
_MASKED_QUERY = "sig=***"
#: A SAS signature in any spelling a payload or an answer may carry it:
#: plain, percent-encoded, JSON-escaped, HTML-escaped. Masking is blunt on
#: purpose — hiding a little too much is harmless, showing a signature is not.
_SIG_ANY = re.compile(
    r"""sig(?:=|%3D|\\u003d|&#0*61;|&#x0*3d;|&equals;)[^&\s"'\\<>]+""", re.IGNORECASE)
#: After :func:`_normalise`: a ``sig=`` / ``se=`` / ``sp=`` query parameter.
_SIG_PARAM = re.compile(r"(?<![A-Za-z0-9_])sig=", re.IGNORECASE)
_SE_PARAM = re.compile(r"""(?<![A-Za-z0-9_])se=([^&\s"'<>#]*)""", re.IGNORECASE)
_SP_PARAM = re.compile(r"""(?<![A-Za-z0-9_])sp=([^&\s"'<>#]*)""", re.IGNORECASE)
_JSON_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")
#: A link counts as expired only this long after its ``se=``: the local clock
#: and Azure's may disagree by a few minutes.
CLOCK_SKEW = timedelta(minutes=5)
#: SAS permission letters that allow changing the blob.
_WRITE_PERMS = frozenset("wcad")


@dataclass(frozen=True)
class UploadLink:
    path: str  # where it sits, e.g. "documents[0].attributes[1]"
    #: The full URL (or the string that carries it) — kept out of repr() and
    #: str(); never log or show it, use :attr:`masked`.
    url: str = field(repr=False)
    expires: datetime | None = None  # ``se=`` (UTC); None if absent, repeated or unreadable
    writable: bool = True  # ``sp=`` grants write/create/add/delete (True when unknown)

    @property
    def masked(self) -> str:
        return mask_text(self.url)

    def expired(self, now: datetime) -> bool:
        """True only when the link provably expired, at least :data:`CLOCK_SKEW`
        ago: a missing, repeated or unreadable ``se=`` counts as still valid."""
        return self.expires is not None and self.expires + CLOCK_SKEW <= _aware(now)


def find_links(payload: Any) -> list[UploadLink]:
    """Every non-empty ``attachmentUrl`` attribute, at any depth, in document order."""
    found: list[UploadLink] = []
    for path, item in _walk_attribute_items(payload, ""):
        if _key_of(item) == LINK_KEY:
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                found.append(parse_link(path, value.strip()))
    return found


def remove_links(payload: dict) -> dict:
    """A deep copy of ``payload`` without any ``attachmentUrl`` / ``attachmentId``
    attribute. The input is never modified."""
    return _without_links(copy.deepcopy(payload))


def parse_link(path: str, url: str) -> UploadLink:
    """Never raises: a URL that cannot be parsed gives ``expires=None`` (so it
    is treated as still valid, hence refused) and ``writable=True``."""
    try:
        parts = urlsplit(url)
        parts.hostname, parts.port  # noqa: B018 - both raise ValueError when malformed
        pairs = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return UploadLink(path=path, url=url)
    se = [v for k, v in pairs if k.lower() == "se"]
    sp = [v for k, v in pairs if k.lower() == "sp"]
    return UploadLink(path=path, url=url,
                      expires=_parse_expiry(se[0]) if len(se) == 1 else None,
                      writable=_writable(sp))


def signed_links(payload: Any) -> list[UploadLink]:
    """Every string of ``payload``, at any depth, that carries a SAS signature
    (``sig=``) in any encoding — plain, percent-encoded, JSON- or HTML-escaped,
    protocol-relative or with no scheme at all. ``url`` is the whole string;
    the expiry is read only when exactly one ``se=`` is present.

    The defence in depth behind the attribute-based :func:`find_links`: no
    policy may send a signed link that is not provably expired.
    """
    found: list[UploadLink] = []
    for path, value in _walk_strings(payload, ""):
        text = _normalise(value)
        if not _SIG_PARAM.search(text):
            continue
        se = _SE_PARAM.findall(text)
        found.append(UploadLink(path=path, url=value,
                                expires=_parse_expiry(se[0]) if len(se) == 1 else None,
                                writable=_writable(_SP_PARAM.findall(text))))
    return found


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


# ------------------------------------------------------------------ helpers ---


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.astimezone()


def _normalise(text: str) -> str:
    """Undo the escapings a URL may hide behind (HTML entities, JSON ``\\uXXXX``
    and ``\\/``, percent-encoding) until nothing changes (at most 4 rounds)."""
    for _ in range(4):
        before = text
        text = html.unescape(text).replace("\\/", "/")
        text = unquote(_JSON_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text))
        if text == before:
            break
    return text


def _writable(perms: list[str]) -> bool:
    """Unknown (absent or repeated ``sp=``) counts as writable."""
    if len(perms) != 1:
        return True
    return bool(set(perms[0].lower()) & _WRITE_PERMS)


def _parse_expiry(raw: str) -> datetime | None:
    raw = unquote(raw).strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _key_of(item: Any) -> str | None:
    if isinstance(item, dict):
        key = item.get("key")
        if isinstance(key, str):
            return key.strip().lower()
    return None


def _walk_attribute_items(node: Any, path: str):
    """``(path, item)`` for every dict that is an element of a list, anywhere."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_attribute_items(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            item_path = f"{path}[{i}]"
            if isinstance(v, dict):
                yield item_path, v
            yield from _walk_attribute_items(v, item_path)


def _walk_strings(node: Any, path: str):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}[{i}]")


def _without_links(node: Any) -> Any:
    if isinstance(node, dict):
        for k in list(node):
            node[k] = _without_links(node[k])
        return node
    if isinstance(node, list):
        return [_without_links(v) for v in node if _key_of(v) not in LINK_KEYS]
    return node
