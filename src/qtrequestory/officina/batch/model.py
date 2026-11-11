"""The data of a Genera run: what is asked, what is called, what came of it.

Every class is a frozen dataclass so a request, a call or an outcome can be
handed between threads (three lanes, then the GUI thread) without copying.

``BatchStarted`` / ``BatchItemDone`` are core :class:`~qtrequestory.core.events.Event`
subclasses, so they fit an ``EventSink`` and pass through the UI's
``QtEventSink`` like every other event. Their timestamp is left out of ``==``
(``compare=False``): two progress events with the same content are equal,
which is what a test or a de-duplicating consumer expects.

Stdlib + core only, Qt-free.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from qtrequestory.core.events import Event
from qtrequestory.core.index.search import SearchHit
from qtrequestory.officina.generator import DocType

Status = Literal["ok", "html_skipped", "no_call", "failed", "cancelled"]


@dataclass(frozen=True)
class Target:
    """One thing the user asked for: a template key, an FDI, or one exact call.

    ``folders`` are the output folders of a key (its packages, or
    ``NO_PACKAGE``) or of an exact call (its FDI, or ``NO_PACKAGE``); for an
    ``"fdi"`` target they are ignored, the folder is the FDI itself.

    ``keys`` narrows an ``"fdi"`` target to those template keys of THAT FDI
    (a retry of the rows of an FDI that did not end well); ``()`` = the
    whole FDI. Ignored for the other kinds.

    ``hit`` is the logged call of a ``"call"`` target (Ricerca's "Genera
    documento"): THAT call is sent as it is in the log — nothing is looked
    up, never the newest call of its key. ``value`` is its template key.
    Ignored (``None``) for the other kinds.
    """
    kind: Literal["key", "fdi", "call"]
    value: str
    folders: tuple[str, ...]
    keys: tuple[str, ...] = ()
    hit: SearchHit | None = None


@dataclass(frozen=True)
class BatchRequest:
    generator: str                          # name of the generator to send to
    source_env: str                         # the logs the payloads come from ("Chiamate dai log di")
    targets: tuple[Target, ...]
    header_rows: tuple[tuple[str, str], ...]  # the whole header table (see headers.build_headers)
    destination: Path
    save_html: bool
    make_zip: bool


@dataclass(frozen=True)
class Call:
    """One call to make: the payload is ``hit``'s body; ``hit is None`` means
    no call was found in the logs (nothing is sent). ``exact``: the call of
    a ``"call"`` target, asked for as such (its outcome remembers it)."""
    key: str                    # the spelling of the logs when found, else as asked ("" for an empty FDI)
    folders: tuple[str, ...]    # every folder the document is written to
    fdi: str | None             # the FDI target, or the FDI of the source call of a key
    hit: SearchHit | None
    exact: bool = False

    @property
    def sendable(self) -> bool:
        """A logged call WITH a template key. Without a hit, or an exact call
        logged with an empty key (no ``template_key`` header to send), it is
        "nessuna chiamata", as an empty key is on the key path."""
        return self.hit is not None and bool(self.key.strip())


@dataclass(frozen=True)
class Outcome:
    """``exact_hit``: the logged call of a ``"call"`` target (``None`` for
    the other kinds), so a retry re-sends that very call."""
    key: str
    folders: tuple[str, ...]
    fdi: str | None
    status: Status
    doc_type: DocType | None
    files: tuple[Path, ...]
    duration_ms: int
    http_status: int | None
    reason: str                 # Italian, masked; "" when ok
    exact_hit: SearchHit | None = None


@dataclass(frozen=True)
class BatchReport:
    run_dir: Path
    outcomes: tuple[Outcome, ...]   # in the order of the calls
    zips: tuple[Path, ...]
    cancelled: bool


@dataclass(frozen=True)
class BatchStarted(Event):
    """The calls are resolved; ``total`` of them will be reported."""
    total: int
    ts: float = field(default_factory=time.time, kw_only=True, compare=False)


@dataclass(frozen=True)
class BatchItemDone(Event):
    """One call finished (``done`` of ``total``, in completion order)."""
    outcome: Outcome
    done: int
    total: int
    ts: float = field(default_factory=time.time, kw_only=True, compare=False)
