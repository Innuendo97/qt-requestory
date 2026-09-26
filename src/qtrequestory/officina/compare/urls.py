"""URL normalisation for the critical HTML attributes (spec §6).

``href`` and ``src`` are compared EXACTLY after :func:`normalise`: scheme and
host lower-cased, query parameters sorted, the keys ``drop`` says so removed.
Path, fragment, userinfo and the raw parameter text are kept as written (a
path is case-sensitive; decoding and re-encoding a value could hide a real
change). ``mailto:``, ``tel:``, ``data:`` and the other opaque schemes only
get their scheme lower-cased: the address is data.

``drop`` is the tracking rule: :func:`tracking_drop` when the noise preset
"Parametri di tracciamento" is on, :func:`keep_all` when it is off. A key
nobody recognises is always kept (a real link change must never hide).

Never raises: a URL the stdlib cannot split comes back stripped, as written.
Stdlib only.
"""
from __future__ import annotations

from collections.abc import Callable
from urllib.parse import unquote_plus, urlsplit, urlunsplit

__all__ = ["TRACKING_KEYS", "keep_all", "normalise", "tracking_drop"]

#: Query keys added by mailers and ad platforms, not by the document; a
#: trailing ``*`` is a prefix. Matched case-insensitively.
TRACKING_KEYS: tuple[str, ...] = (
    "utm_*", "gclid", "fbclid", "msclkid", "mkt_tok", "mc_cid", "mc_eid", "_hsenc", "_hsmktg",
)
_EXACT = frozenset(k for k in TRACKING_KEYS if not k.endswith("*"))
_PREFIXES = tuple(k[:-1] for k in TRACKING_KEYS if k.endswith("*"))


def tracking_drop(key: str) -> bool:
    """Whether ``key`` (a decoded query key) is a tracking parameter."""
    key = key.lower()
    return key in _EXACT or key.startswith(_PREFIXES)


def keep_all(key: str) -> bool:
    """The rule with the tracking preset off: no key is dropped."""
    return False


def normalise(url: str, drop: Callable[[str], bool]) -> str:
    """``url`` in its comparison form (see the module docstring)."""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    scheme = parts.scheme.lower()
    if scheme and not parts.netloc and not url[len(scheme) + 1:].startswith("//"):
        # opaque (mailto:, tel:, data:…) — only the scheme is case-insensitive
        return scheme + url[len(scheme):]
    return urlunsplit((scheme, _netloc(parts.netloc), parts.path, _query(parts.query, drop), parts.fragment))


def _netloc(netloc: str) -> str:
    user, at, host = netloc.rpartition("@")
    return user + at + host.lower()


def _query(query: str, drop: Callable[[str], bool]) -> str:
    kept = [p for p in query.split("&") if p and not drop(unquote_plus(p.partition("=")[0]))]
    return "&".join(sorted(kept))
