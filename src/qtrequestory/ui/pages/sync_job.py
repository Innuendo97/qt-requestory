"""The sync job as the window runs it: the page's sink AND ``sync.log``.

``sync.log`` is the record of every sync, whoever started it. The headless
``--sync`` of the scheduled task writes it through the core's ``LoggingSink``;
a sync started from the window used to reach only the registro panel, so the
file silently missed every run the user made by hand. Here the worker's own
sink (the ``QtEventSink`` feeding the page) is teed with that same
``LoggingSink``, so the file reads the same whoever ran the sync.

Like :mod:`~qtrequestory.ui.pages.sync_format`, this is a documented exception
to "the UI only sees ``ui/contracts.py``": the two core imports below are the
stdlib-only log plumbing the CLI itself uses, not core behaviour.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

from qtrequestory.core.events import LoggingSink  # see the module docstring
from qtrequestory.core.logsetup import sync_logger  # see the module docstring
from qtrequestory.ui.contracts import CancelToken, Event, EventSink, JobReport

__all__ = ["run_logged", "sync_log_sink", "tee"]


def tee(*sinks: EventSink) -> EventSink:
    """One sink that hands every event to each of ``sinks``, in order."""

    def sink(ev: Event) -> None:
        for target in sinks:
            target(ev)

    return sink


def sync_log_sink() -> EventSink:
    """The sink the headless ``--sync`` writes ``sync.log`` with."""
    return LoggingSink(sync_logger())


def run_logged(
    run: Callable[..., JobReport],
    envs: Sequence[str] | None,
    *,
    force: bool,
    dry_run: bool,
    sink: EventSink,
    cancel: CancelToken,
) -> JobReport:
    """``run`` (``services.sync.run``) with ``sink`` teed into ``sync.log``.

    Runs on the worker thread; it declares ``sink``/``cancel`` so the
    ``JobRunner`` injects the job's own, exactly as for ``sync.run`` itself.
    The page's sink goes first: the window is what the user is watching.
    """
    return run(envs, force=force, dry_run=dry_run, sink=tee(sink, sync_log_sink()),
               cancel=cancel)
