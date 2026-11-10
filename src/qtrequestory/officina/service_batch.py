"""Genera on ``OfficinaService`` (spec "Genera"): the four calls the tab makes.

:meth:`BatchMixin.batch_run` binds the engine of ``officina.batch.runner`` to
the service's configuration (a source, read again before every send: an
Impostazioni change is seen at once, also during a run), its index, its
opener (the tests' in-process generator), its
clock and uuids, and ONE :class:`~qtrequestory.officina.batch.memory.HtmlMemory`
per service — thread-safe, built on first use from the path the service was
given (``AppPaths.genera_html_file`` in the app; ``None``: a memory of this
session only, never written).

Refusals are Italian ``ValueError`` before anything is created or sent: no
index (a service built without one), and every up-front problem of
``run_batch`` (no enabled generator, never PROD, a bad destination, a header
table that cannot be built, an index that cannot be searched).

Stdlib only, Qt-free.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from qtrequestory.core.events import CancelToken
from qtrequestory.officina.batch.elenco import Elenco, load_elenco
from qtrequestory.officina.batch.headers import default_rows
from qtrequestory.officina.batch.memory import HtmlMemory
from qtrequestory.officina.batch.model import BatchReport, BatchRequest
from qtrequestory.officina.batch.runner import count_calls, run_batch

__all__ = ["NO_INDEX", "BatchMixin"]

NO_INDEX = "ricerca non disponibile: impossibile trovare le chiamate da generare"


class BatchMixin:
    """Mixed into ``OfficinaService``; uses its ``_settings``, ``_index``,
    ``_opener``, ``_clock`` and ``_new_uuid``."""

    def _init_batch(self, memory_path: Path | None) -> None:
        self._batch_memory_path = Path(memory_path) if memory_path is not None else None
        self._batch_memory: HtmlMemory | None = None
        self._batch_lock = threading.Lock()

    def _html_memory(self) -> HtmlMemory:
        with self._batch_lock:
            if self._batch_memory is None:
                self._batch_memory = HtmlMemory(self._batch_memory_path)
            return self._batch_memory

    # ------------------------------------------------------------ contract ---

    def batch_load_elenco(self, path: Path) -> Elenco:
        """The CSV list at ``path``; ``ElencoError`` (a ``ValueError``, Italian)."""
        return load_elenco(Path(path))

    def batch_default_headers(self) -> list[tuple[str, str]]:
        """The automatic rows (``""``: computed per call), then the profile."""
        return default_rows(self._settings())  # type: ignore[attr-defined]

    def batch_count(self, request: BatchRequest, *, cancel: CancelToken | None = None) -> int:
        """How many calls ``batch_run(request)`` would send now
        (``runner.count_calls``: reads only). ``ValueError`` (Italian) for the
        up-front refusals; ``Cancelled`` when ``cancel`` is set."""
        index = self._index  # type: ignore[attr-defined]
        if index is None:
            raise ValueError(NO_INDEX)
        return count_calls(request, index=index, settings=self._settings(),  # type: ignore[attr-defined]
                           memory=self._html_memory(), cancel=cancel)

    def batch_run(self, request: BatchRequest, *, sink: Callable[[Any], None] | None = None,
                  cancel: CancelToken | None = None) -> BatchReport:
        """Run ``request`` (``officina.batch.runner``). ``ValueError`` with an
        Italian reason for the up-front refusals; never ``Cancelled``. The
        settings are passed as a SOURCE: each row checks the generator in
        the configuration of the moment it is sent."""
        index = self._index  # type: ignore[attr-defined]
        if index is None:
            raise ValueError(NO_INDEX)
        return run_batch(request, index=index, settings=self._settings,  # type: ignore[attr-defined]
                         memory=self._html_memory(), clock=self._clock,  # type: ignore[attr-defined]
                         new_uuid=self._new_uuid, opener=self._opener,  # type: ignore[attr-defined]
                         sink=sink, cancel=cancel)
