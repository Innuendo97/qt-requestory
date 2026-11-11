"""The template keys known to answer HTML (spec "HTML").

With "Salva anche le email (HTML)" off, an HTML answer is not saved and its key is
remembered here; later runs skip the remembered keys without calling them.
With the option on every key is called and the memory follows the answers:
an HTML answer adds the key, a PDF answer removes it.

The file is ``{"html_keys": [...]}``, rewritten atomically (``.part`` then
replace) on every change. A missing or unreadable file is an empty memory,
never an error: losing it costs a few extra calls, nothing else. A failed
save is logged and the change kept in memory for this session — a run is
never failed because the memory could not be written.

Thread-safe: the three lanes of a run record answers concurrently. Where the
file lives is the caller's choice (``AppPaths`` in the app); ``None`` is a
memory of this session only, never written (a service built without a
path: the tests, a portable run that did not ask for one). Stdlib only.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path

from qtrequestory.core.fsutil import remove_quietly, replace_with_retry
from qtrequestory.officina.generator import DocType
from qtrequestory.officina.links import mask_text_for_log

log = logging.getLogger(__name__)


class HtmlMemory:
    def __init__(self, path: Path | None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._keys: dict[str, str] = {}  # folded key -> spelling
        for key in _load(self._path) if self._path is not None else ():
            self._keys.setdefault(key.casefold(), key)

    def is_html(self, key: str) -> bool:
        """``key`` is remembered as HTML (case-insensitive)."""
        with self._lock:
            return key.strip().casefold() in self._keys

    def record(self, key: str, doc_type: DocType) -> None:
        """An answer of ``doc_type`` for ``key``: "html" remembers the key,
        "pdf" forgets it. The file is rewritten only when something changed."""
        key = key.strip()
        if not key:
            return
        folded = key.casefold()
        with self._lock:
            if doc_type == "html":
                if folded in self._keys:
                    return
                self._keys[folded] = key
            elif doc_type == "pdf":
                if self._keys.pop(folded, None) is None:
                    return
            else:
                return
            self._save()

    def _save(self) -> None:
        """Rewrite the file (called with the lock held); none: nothing to write."""
        if self._path is None:
            return
        data = {"html_keys": sorted(self._keys.values(), key=str.casefold)}
        tmp = self._path.with_name(f".{self._path.name}.{uuid.uuid4().hex[:12]}.part")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            replace_with_retry(tmp, self._path)
        except OSError as exc:
            log.warning("Genera: memoria degli HTML non salvata: %s", mask_text_for_log(str(exc)))
        finally:
            remove_quietly(tmp)


def _load(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        log.warning("Genera: memoria degli HTML non leggibile, si riparte da vuota: %s",
                    mask_text_for_log(type(exc).__name__))
        return []
    keys = data.get("html_keys") if isinstance(data, dict) else None
    if not isinstance(keys, list):
        return []
    return [k.strip() for k in keys if isinstance(k, str) and k.strip()]
