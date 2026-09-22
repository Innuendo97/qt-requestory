"""HTTP access for the sync engine: one small Protocol and its stdlib implementation.

``HttpClient`` is a Protocol so the sync engine can be tested with fakes and so
the real client stays swappable. ``UrllibHttpClient`` deliberately uses only
``urllib.request`` with the *default* opener and SSL context: on Windows that
means the system certificate store (corporate CAs installed by IT) and the
system/IE proxy settings are honoured without any configuration — the same
behaviour the previous PowerShell script relied on.
"""
from __future__ import annotations

import http.client
import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from qtrequestory import __version__
from qtrequestory.core.events import CancelToken

log = logging.getLogger(__name__)

USER_AGENT = f"qtRequestory/{__version__}"

ProgressCallback = Callable[[int, int | None], None]


class HttpUnreachable(Exception):
    """The endpoint could not be read (DNS, connect, timeout, HTTP error status).

    The sync engine treats this as "skip the environment this round".
    """


class HttpDownloadError(Exception):
    """A file download failed for a network reason. The partial file is gone."""


class HttpClient(Protocol):
    def get_text(self, url: str, timeout: float) -> str:
        """Fetch a small text resource (the autoindex page)."""
        ...

    def download(
        self,
        url: str,
        dest_part: Path,
        *,
        timeout: float,
        chunk_size: int,
        on_progress: ProgressCallback,
        cancel: CancelToken,
    ) -> int:
        """Stream ``url`` into ``dest_part``; return the number of bytes written."""
        ...


class UrllibHttpClient(HttpClient):
    """``HttpClient`` on top of ``urllib.request`` (default opener: system proxy,
    Windows certificate store)."""

    def _request(self, url: str) -> urllib.request.Request:
        return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    def get_text(self, url: str, timeout: float) -> str:
        try:
            with urllib.request.urlopen(self._request(url), timeout=timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read().decode(charset, errors="replace")
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
            # HTTPError (4xx/5xx) is a URLError; socket.timeout is TimeoutError;
            # both are OSErrors — listed anyway to make the intent explicit.
            raise HttpUnreachable(str(e)) from e

    def download(
        self,
        url: str,
        dest_part: Path,
        *,
        timeout: float,
        chunk_size: int,
        on_progress: ProgressCallback,
        cancel: CancelToken,
    ) -> int:
        """Stream ``url`` to ``dest_part`` (parent directory created as needed).

        ``cancel.check()`` runs before every chunk; a ``Cancelled`` propagates
        after the partial file has been removed. ``on_progress(done, total)``
        is called after every chunk, ``total`` being ``Content-Length`` or
        ``None`` when the server did not send one.

        Truncated responses (the server closes the connection before
        ``Content-Length`` bytes arrived) do NOT raise: the bytes received so
        far stay in ``dest_part`` and their count is returned. The sync engine
        already knows the expected size from the autoindex and compares
        ``written == size`` itself, so raising here would only duplicate that
        check while hiding the exact byte count from the caller.

        Any other network failure raises ``HttpDownloadError`` with the
        partial file removed.
        """
        cancel.check()
        written = 0
        keep_file = False
        try:
            with urllib.request.urlopen(self._request(url), timeout=timeout) as resp:
                total = _content_length(resp)
                dest_part.parent.mkdir(parents=True, exist_ok=True)
                with open(dest_part, "wb") as out:
                    while True:
                        cancel.check()
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out.write(chunk)
                        written += len(chunk)
                        on_progress(written, total)
            if total is not None and written < total:
                # debug only: the sync engine reports the truncation itself (FileFailed)
                log.debug("download truncated: %d of %d bytes from %s", written, total, url)
            keep_file = True
            return written
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as e:
            raise HttpDownloadError(str(e)) from e
        finally:
            if not keep_file:
                _remove_quietly(dest_part)


def _content_length(resp: http.client.HTTPResponse) -> int | None:
    value = resp.headers.get("Content-Length")
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _remove_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:  # pragma: no cover - best effort, e.g. AV holding the file
        log.warning("could not remove partial file %s: %s", path, e)
