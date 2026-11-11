"""Genera of exact calls: what Ricerca's "Genera documento" runs on the Genera page.

The calls the user selected in Ricerca are sent AS LOGGED (``Target("call")``,
``targets_from_hits``), through the Genera tab's own run machinery — the same
job (``GENERA_JOB``, so never two runs at once), the same results table, the
same "Riprova i non riusciti" (which re-sends those very calls, like every
retry to the generator the tab shows then), the same confirmation above
``CONFIRM_ABOVE`` calls.

What such a run takes from the tab: the header rows on screen (edits of this
session included) and the destination folder. What it does not: the HTML
switch (an e-mail the user asked for is always saved, and the HTML memory
follows the answers as in a "Salva anche le email (HTML)" run) and the zip (never).
The generator is the caller's choice, among the enabled ones (never PROD:
``config`` refuses it, ``run_batch`` checks again).

:class:`GeneraCalls` is a mixin of :class:`~qtrequestory.ui.pages.genera_page.GeneraPage`;
the pure parts (:func:`calls_request`, :func:`calls_problems`,
:func:`generator_order`) take the presenter and are tested without a page.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import BatchReport, BatchRequest, SearchHit, targets_from_hits
from qtrequestory.ui.pages import officina_dialogs as ask

__all__ = ["CallsNotify", "GeneraCalls", "calls_problems", "calls_request", "generator_order"]

#: ``notify(report, problem)``: once per run, with its report (``problem`` "")
#: or, when the core refused it, ``(None, Italian reason)``.
CallsNotify = Callable[[BatchReport | None, str], None]


def _envs(hits: Sequence[SearchHit]) -> list[str]:
    seen: list[str] = []
    for hit in hits:
        if hit.env not in seen:
            seen.append(hit.env)
    return seen


def calls_request(presenter, hits: Sequence[SearchHit], generator: str) -> BatchRequest:
    """The request that sends ``hits`` as logged to ``generator`` (module docstring)."""
    return BatchRequest(
        generator=generator, source_env=", ".join(_envs(hits)), targets=targets_from_hits(hits),
        header_rows=tuple(presenter.header_rows), destination=presenter.destination or Path(),
        save_html=True, make_zip=False)


def calls_problems(presenter, generator: str) -> list[str]:
    """What stops sending exact calls to ``generator`` now; empty = ready."""
    found: list[str] = []
    if generator not in presenter.generators:
        found.append(strings.GENERA_CALLS_GENERATOR_OFF.format(name=generator))
    destination = presenter.destination
    if destination is None or not Path(destination).is_absolute():
        found.append(strings.GENERA_CALLS_NEED_DESTINATION)
    header = next((p for row in presenter.header_row_problems() for p in row), None)
    if header:
        found.append(strings.GENERA_CALLS_HEADER_PROBLEM.format(problem=header))
    return found


def generator_order(generators: Sequence[str], env: str, remembered: str) -> list[str]:
    """The enabled ``generators``, the default first: ``env`` (where the calls
    come from) when it is one of them, else ``remembered`` (the Genera tab's
    generator), else the configured order."""
    order = list(generators)
    first = env if env in order else (remembered if remembered in order else "")
    if first:
        order.remove(first)
        order.insert(0, first)
    return order


class GeneraCalls:
    """The exact-call entry of the Genera page (module docstring). Uses the
    page's ``presenter``, ``_running`` and ``_run`` (``genera_run``)."""

    def headers_note(self) -> str:
        """What Ricerca adds to its tooltip while this tab's headers differ from
        Impostazioni (they are sent with the calls too); "" when they do not."""
        if not self.presenter.activated:
            return ""
        m = self.presenter.modified_headers()
        return strings.GENERA_CALLS_HEADERS_EDITED.format(m=m) if m else ""

    def calls_generators(self, hits: Sequence[SearchHit]) -> list[str]:
        """The generators a "Genera documento" of ``hits`` can use, the default first."""
        envs = _envs(hits)
        return generator_order(self.presenter.generators, envs[0] if envs else "",
                               self.presenter.generator)

    def generate_calls(self, hits: Sequence[SearchHit], generator: str, *, parent=None,
                       notify: CallsNotify | None = None) -> tuple[bool, str]:
        """Send ``hits`` as logged to ``generator``: ``(True, "")`` when the
        run started (``notify`` hears how it ended), ``(False, "")`` when the
        user said no to the confirmation, ``(False, reason)`` when nothing can
        be sent now (a run going, no folder, a bad header, a generator that
        is not enabled). ``parent`` holds the confirmation (default: the page)."""
        hits = list(hits)
        if self._running:
            return False, strings.GENERA_ALREADY_RUNNING
        if not hits:
            return False, ""
        self.presenter.activate()  # the header table of a tab never shown (once; quick)
        self._commit_edits()  # a header cell left open on the tab: what it shows is sent
        problems = calls_problems(self.presenter, generator)
        if problems:
            return False, problems[0]
        request = calls_request(self.presenter, hits, generator)
        count = len(request.targets)
        if self.presenter.needs_confirmation(count):
            title, text = self.presenter.confirmation(request, count)
            if not ask.confirm(parent if parent is not None else self, title, text,
                               yes=self.presenter.confirm_yes(count), no=strings.BTN_CANCEL):
                return False, ""
        if not self._run(request, notify=notify):
            return False, strings.GENERA_ALREADY_RUNNING
        return True, ""
