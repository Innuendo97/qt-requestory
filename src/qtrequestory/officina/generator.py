"""The generator client: headers, upload-link policy, and the HTTP call to the
Inspire Scaler ``documentGenerator`` (spec §5, §9, §11).

Three steps, kept separate so each can be tested and so the service (Task 5)
can refuse before anything leaves the machine:

1. :func:`resolve_headers` — the headers of one call. Precedence, the last
   layer winning: automatic values, the Impostazioni header profile, the
   initiative defaults, the case overrides. Names compare case-insensitively
   (HTTP does), and a header whose final value is empty is not sent — except
   ``Postman-Token``, which only the case's explicit toggle removes.
2. :func:`prepare_payload` — applies the upload-link policy. Whatever the
   policy, a still-valid upload link is never sent (a SAS link with write
   permission on a real customer's blob).
3. :func:`send` — POSTs the JSON and sniffs the answer from the bytes: svil
   sends **no Content-Type** (probe, spec §11). A 200 that is not a document,
   a suspiciously tiny HTML, an HTTP error, a timeout or a network error are all
   a failed run (``ok=False``) with a readable Italian reason, never a version.

Every URL that could reach a message, a log or ``headers_sent`` goes through
``links.mask`` first. Stdlib only.
"""
from __future__ import annotations

import copy
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
from typing import TYPE_CHECKING, Any, Literal

from qtrequestory.core.config import (
    OfficinaSettings,
    generator_url_problem,
    header_name_problem,
    header_value_problem,
)
from qtrequestory.officina.links import (
    UploadLink,
    find_links,
    mask,
    mask_bytes,
    mask_text,
    remove_links,
    signed_links,
)

if TYPE_CHECKING:
    from qtrequestory.officina.model import Case, Initiative

DocType = Literal["pdf", "html"]

POSTMAN_TOKEN = "Postman-Token"
#: Below this an "HTML document" is a gateway error page, not an email body.
MIN_HTML_BYTES = 512
#: How much of a failed answer is kept to show the user (spec §5).
PREVIEW_BYTES = 4096
SNIFF_BYTES = 1024
POLICIES = ("remove", "keep_if_expired")

REASON_NOT_A_DOCUMENT = "la risposta non è un PDF né un HTML"
REASON_TINY_HTML = "risposta HTML sospetta: troppo corta"

#: Header names whose value is a credential: shown as ``***`` in headers_sent.
_SECRET_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "x-api-key", "api-key", "apikey",
    "ocp-apim-subscription-key", "x-functions-key",
})
_CHUNK = 65536
#: An answer larger than this is discarded, never written as a version.
MAX_BODY_BYTES = 200 * 1024 * 1024


class HeaderError(ValueError):
    """The headers of a case cannot be built (message in Italian, for the user)."""


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status: int | None  # None when no HTTP answer arrived (timeout, network)
    doc_type: DocType | None
    #: The document when ``ok``; otherwise the first 4 KB of the answer, with
    #: URLs masked, to show the user (``b""`` when nothing arrived).
    content: bytes
    duration_ms: int
    reason: str  # "" when ok; Italian, URLs masked
    headers_sent: dict[str, str]  # credentials as "***", URLs masked


# ------------------------------------------------------------------- headers ---


class _FromCase:
    def __repr__(self) -> str:
        return "<case.source_fdi>"


_FROM_CASE: Any = _FromCase()


def resolve_headers(
    case: Case,
    ini: Initiative,
    settings: OfficinaSettings,
    *,
    now_ms: int,
    new_uuid: Callable[[], str],
    source_fdi: str | None = _FROM_CASE,
) -> dict[str, str]:
    """The headers of one call for ``case`` (see the module docstring for the
    precedence). ``source_fdi`` defaults to ``case.source_fdi``.

    Raises :class:`HeaderError` when ``correlation_id`` cannot be resolved
    (mode "source" without a known FDI, "fixed" without a value) and no layer
    sets it explicitly, or when a header name/value is malformed.
    """
    fdi = case.source_fdi if source_fdi is _FROM_CASE else source_fdi
    automatic: dict[str, str] = {
        "current_timestamp": str(int(now_ms)),
        "template_key": case.key,
    }
    correlation_problem = ""
    if case.correlation == "source":
        if fdi and fdi.strip():
            automatic["correlation_id"] = fdi.strip()
        else:
            correlation_problem = ("il caso usa l'FDI della chiamata di origine come correlation_id, "
                                   "ma l'FDI non è noto: impostare un correlation_id")
    elif case.correlation == "fixed":
        if case.correlation_value.strip():
            automatic["correlation_id"] = case.correlation_value.strip()
        else:
            correlation_problem = "il caso usa un correlation_id fisso, ma il valore è vuoto"
    else:
        automatic["correlation_id"] = new_uuid()
    automatic[POSTMAN_TOKEN] = settings.postman_token

    merged: dict[str, tuple[str, str]] = {}  # lower name -> (name, value)
    origin: dict[str, str] = {}  # lower name -> the layer that set it (for the message)
    layers = ((automatic, "valori automatici"), (settings.header_profile, "profilo in Impostazioni"),
              (ini.header_defaults, "iniziativa"), (case.headers, "caso"))
    for layer, where in layers:
        for name, value in layer.items():
            name = str(name).strip()
            if not name:
                continue
            merged[name.lower()] = (name, "" if value is None else str(value).strip())
            origin[name.lower()] = where

    token_key = POSTMAN_TOKEN.lower()
    if case.drop_postman_token:
        merged.pop(token_key, None)
    elif not merged.get(token_key, ("", ""))[1]:
        # emptying it in a layer does NOT remove it: only the toggle does
        value = settings.postman_token.strip() or OfficinaSettings().postman_token
        merged[token_key] = (POSTMAN_TOKEN, value)

    headers = {name: value for name, value in merged.values() if value}
    if not any(k.lower() == "correlation_id" for k in headers):
        raise HeaderError(correlation_problem or "correlation_id vuoto: impostare un valore")
    for name, value in headers.items():
        # The same rules as the Impostazioni profile (``officina_errors``).
        problem = header_name_problem(name) or header_value_problem(name, value)
        if problem:
            raise HeaderError(f"intestazioni ({origin.get(name.lower(), 'caso')}): {problem}")
    return headers


def shown_headers(headers: dict[str, str]) -> dict[str, str]:
    """``headers`` safe to store in a version's meta or show: credentials
    become ``***`` and every URL is masked."""
    return {
        name: "***" if name.lower() in _SECRET_HEADERS else mask_text(value)
        for name, value in headers.items()
    }



# ----------------------------------------------------------- payload policy ---


def prepare_payload(payload: dict, policy: str, *, now: datetime) -> tuple[dict | None, str]:
    """``(payload to send, "")`` or ``(None, refusal reason)``. Never raises.

    * ``remove``: a copy without the attachmentUrl/attachmentId attributes;
    * ``keep_if_expired``: an unchanged copy, only when every upload link has
      a single readable ``se=`` at least ``links.CLOCK_SKEW`` in the past.

    Then, whatever the policy, every string left anywhere in the payload is
    checked: one carrying a SAS signature (``sig=``, in any encoding) that is
    not provably expired refuses the send. The input is never modified.
    """
    now = now if now.tzinfo is not None else now.astimezone()
    if policy == "remove":
        out = remove_links(payload)
    elif policy == "keep_if_expired":
        for link in find_links(payload):
            if not link.expired(now):
                return None, _still_valid_reason(link)
        out = copy.deepcopy(payload)
    else:
        return None, f"politica dei link di caricamento sconosciuta: '{policy}'; invio rifiutato"
    for link in signed_links(out):
        if not link.expired(now):
            return None, _still_valid_reason(link)
    return out, ""


def _still_valid_reason(link: UploadLink) -> str:
    shown = link.masked
    if len(shown) > 160:
        shown = shown[:157] + "..."
    where = f"il link di caricamento in {link.path} ({shown})"
    if link.expires is None:
        return (f"{where} non ha una scadenza leggibile (se=): non si può escludere che sia ancora "
                "valido, invio rifiutato")
    until = link.expires.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M")
    return f"{where} è ancora valido fino al {until} UTC: invio rifiutato"


# --------------------------------------------------------------------- sniff ---

#: ``%PDF-`` at the very start; at most 8 bytes of BOM/whitespace before it.
_PDF_START = re.compile(rb"\A[\xef\xbb\xbf \t\r\n\f]{0,8}%PDF-")


def sniff(content: bytes) -> DocType | None:
    """The document type from the bytes alone: ``%PDF-`` at the start → pdf;
    an answer that starts with markup and has ``<!doctype html`` or ``<html``
    in its first KB → html; anything else (JSON, text, empty) → None."""
    if _PDF_START.match(content):
        return "pdf"
    lower = content[:SNIFF_BYTES].lstrip(b"\xef\xbb\xbf").lstrip().lower()
    if lower.startswith(b"<") and (b"<!doctype html" in lower or b"<html" in lower):
        return "html"
    return None


# ---------------------------------------------------------------------- send ---


class _TooLarge(Exception):
    pass


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A 3xx is never followed: it would take the payload (and its headers)
    to a host nobody checked. Returning None makes urllib raise the 3xx as an
    HTTPError, which ``send`` turns into a failed run."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


_OPENER = urllib.request.build_opener(_RefuseRedirects)


def _open(request: urllib.request.Request, timeout: float) -> Any:
    return _OPENER.open(request, timeout=timeout)


def send(
    url: str,
    payload: dict,
    headers: dict[str, str],
    *,
    timeout_s: int,
    opener: Callable[..., Any] | None = None,
) -> SendResult:
    """POST ``payload`` as JSON to ``url``. Never raises: every problem comes
    back as ``ok=False`` with a masked Italian reason. ``opener`` defaults to
    an opener that refuses redirects."""
    started = time.monotonic()
    try:
        shown = shown_headers(headers)
    except Exception:  # noqa: BLE001 - headers of the wrong type
        shown = {}
    try:
        return _send(url, payload, headers, timeout_s=timeout_s, opener=opener or _open, started=started)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raises"
        return SendResult(ok=False, status=None, doc_type=None, content=b"",
                          duration_ms=int((time.monotonic() - started) * 1000),
                          reason=mask_text(f"errore inatteso: {type(exc).__name__}: {exc}"),
                          headers_sent=shown)


def _send(url: str, payload: dict, headers: dict[str, str], *, timeout_s: int,
          opener: Callable[..., Any], started: float) -> SendResult:
    to_send = dict(headers)
    if not any(k.lower() == "content-type" for k in to_send):
        to_send["Content-Type"] = "application/json"
    shown = shown_headers(to_send)

    def result(ok: bool, status: int | None, doc_type: DocType | None, content: bytes,
               reason: str) -> SendResult:
        return SendResult(ok=ok, status=status, doc_type=doc_type, content=content,
                          duration_ms=int((time.monotonic() - started) * 1000),
                          reason=mask_text(reason), headers_sent=shown)

    problem = generator_url_problem(url, allow_loopback_http=True)
    if problem:
        return result(False, None, None, b"", f"generatore {mask(url)}: {problem}; invio rifiutato")
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return result(False, None, None, b"", f"il payload non è un JSON valido: {exc}")

    # urllib title-cases header names on the wire (template_key -> Template_Key);
    # HTTP names are case-insensitive and the probe of spec §11 went out that way.
    request = urllib.request.Request(url, data=body, headers=to_send, method="POST")
    deadline = started + timeout_s
    try:
        with opener(request, timeout=timeout_s) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            if 300 <= status < 400:
                return result(False, status, None, b"", _redirect_reason(status))
            content = _read_until(response, deadline, MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        try:
            preview = exc.read(PREVIEW_BYTES) or b""
        except (OSError, HTTPException, ValueError):
            preview = b""
        finally:
            exc.close()
        if 300 <= exc.code < 400:
            return result(False, exc.code, None, b"", _redirect_reason(exc.code))
        return result(False, exc.code, None, mask_bytes(preview[:PREVIEW_BYTES]),
                      f"il generatore ha risposto HTTP {exc.code}")
    except _TooLarge:
        return result(False, None, None, b"",
                      f"risposta troppo grande (oltre {_size(MAX_BODY_BYTES)}): scartata")
    except TimeoutError:
        return result(False, None, None, b"", _timeout_reason(timeout_s))
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return result(False, None, None, b"", _timeout_reason(timeout_s))
        return result(False, None, None, b"", f"errore di rete: {exc.reason}")
    except (OSError, HTTPException, ValueError) as exc:
        return result(False, None, None, b"", f"errore di rete: {type(exc).__name__}: {exc}")

    preview = mask_bytes(content[:PREVIEW_BYTES])
    if status >= 400:
        return result(False, status, None, preview, f"il generatore ha risposto HTTP {status}")
    doc_type = sniff(content)
    if doc_type is None:
        return result(False, status, None, preview, REASON_NOT_A_DOCUMENT)
    if doc_type == "html" and len(content) < MIN_HTML_BYTES:
        return result(False, status, doc_type, preview, REASON_TINY_HTML)
    return result(True, status, doc_type, content, "")


def _read_until(response: Any, deadline: float, limit: int) -> bytes:
    """The whole body, but never past ``deadline`` nor over ``limit`` bytes.

    ``read1`` returns whatever arrived instead of waiting for a full chunk, and
    the socket timeout is shrunk to the time left before every read, so a
    server trickling bytes cannot stretch the overall timeout.
    """
    declared = _content_length(response)
    if declared is not None and declared > limit:
        raise _TooLarge
    read = getattr(response, "read1", None) or response.read
    chunks: list[bytes] = []
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        sock = _socket_of(response)  # gone once http.client has read the whole body
        if sock is not None:
            try:
                sock.settimeout(remaining)
            except OSError:
                pass  # already closed: the next read returns b""
        chunk = read(_CHUNK)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > limit:
            raise _TooLarge
        chunks.append(chunk)


def _content_length(response: Any) -> int | None:
    try:
        value = response.headers.get("Content-Length")
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _socket_of(response: Any) -> Any:
    """The socket under an ``http.client.HTTPResponse`` (``fp`` is a buffered
    ``SocketIO``), or None for anything else — e.g. a test double."""
    raw = getattr(getattr(response, "fp", None), "raw", None)
    sock = getattr(raw, "_sock", None)
    return sock if hasattr(sock, "settimeout") else None


def _size(n: int) -> str:
    mb = 1024 * 1024
    return f"{n // mb} MB" if n >= mb else f"{n} byte"


def _redirect_reason(status: int) -> str:
    return f"reindirizzamento non consentito (HTTP {status}): il generatore deve rispondere direttamente"


def _timeout_reason(timeout_s: int) -> str:
    return f"nessuna risposta completa dal generatore entro {timeout_s} s (tempo scaduto)"
