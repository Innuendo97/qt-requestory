"""The Genera tab's state: what to generate, where, with which headers — and
what still stops the button (spec "Genera"; plan Task 5).

A plain ``QObject`` with one signal, :attr:`GeneraPresenter.changed`, emitted
after every change; the page re-renders from it. No widget here. The read-only
views and the words (button, confirmation, notes) are in ``genera_views``.

* **Three sources**, each keeping its own text: template keys typed by hand,
  the Quadient list (only the ticked packages) or whole FDIs. A list loaded
  in "Elenco" also gives the typed keys their package folders (spec: "Se un
  elenco è caricato la cartella è il package dell'elenco").
* **Where**: the enabled generators; "Chiamate da" follows the generator's
  name until the user picks another environment (picking the generator's
  name again makes it follow again); the destination folder.
* **Headers**: the whole table that is sent, starting from
  ``batch_default_headers``; changes live here only, lost when the app
  closes ("Ripristina" goes back to Impostazioni).
* :meth:`problems` — in the order of the screen, top to bottom, so the line
  under the button names the first thing to fix.
* **Lazy.** Construction reads only the configuration and the remembered
  choices (``ui/prefs``): no disk, no Officina service — the window is being
  built, and a mapped drive that is gone must not stall it. The remembered
  folder is kept as text, unchecked (the run creates it, or says why it
  cannot). :meth:`activate`, when the tab is first shown, builds the
  service (the header table) and reads the remembered list; a list that is
  gone or unreadable is simply dropped, never an error.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from qtrequestory.ui import prefs, strings
from qtrequestory.ui.contracts import (
    BatchReport,
    BatchRequest,
    CoreServices,
    Elenco,
    ElencoError,
    Target,
    header_problems,
    parse_keys,
    targets_from_fdis,
    targets_from_keys,
    targets_from_packages,
)
from qtrequestory.ui.pages import genera_prefs
from qtrequestory.ui.pages.genera_retry import RETRY_STATUSES, retry_count, retry_targets
from qtrequestory.ui.pages.genera_views import GeneraViews

__all__ = ["CONFIRM_ABOVE", "MODES", "RETRY_STATUSES", "GeneraPresenter"]

log = logging.getLogger(__name__)

MODES = ("keys", "elenco", "fdi")
#: Above this many calls the run is confirmed first (spec "Esecuzione").
CONFIRM_ABOVE = 20


class GeneraPresenter(QObject, GeneraViews):
    """See the module docstring."""

    changed = Signal()

    def __init__(self, services: CoreServices, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._mode = "keys"
        self._keys_text = ""
        self._fdi_text = ""
        self._elenco: Elenco | None = None
        self._elenco_path: Path | None = None
        self._elenco_error = ""
        self._pending_elenco: Path | None = None  # remembered, read by activate()
        self._activated = False
        self._checked: set[str] = set()
        self._generators: list[str] = []
        self._generator = ""
        self._default_generator = ""
        self._envs: list[str] = []
        self._source_env = ""
        self._source_chosen = False
        self._destination: Path | None = None
        self._default_headers: list[tuple[str, str]] = []
        self._headers: list[tuple[str, str]] = []
        self._make_zip = False
        self._save_html = False
        self._read_config()
        self._restore()

    def activate(self) -> None:
        """The tab is shown for the first time: the header table (this builds
        the Officina service) and the remembered list. Once; never raises."""
        if self._activated:
            return
        self._activated = True
        self._default_headers = self._load_default_headers()
        self._headers = list(self._default_headers)
        pending, self._pending_elenco = self._pending_elenco, None
        if pending is not None and self._elenco is None:
            self.load_elenco(pending, quiet=True)  # emits changed
        else:
            self.changed.emit()

    # -- changes (the read-only views are in genera_views) ------------------------

    def set_mode(self, mode: str) -> None:
        if mode in MODES and mode != self._mode:
            self._mode = mode
            self._remember(prefs.GENERA_MODE_KEY, mode)
            self.changed.emit()

    def set_keys_text(self, text: str) -> None:
        if text != self._keys_text:
            self._keys_text = text
            self.changed.emit()

    def set_fdi_text(self, text: str) -> None:
        if text != self._fdi_text:
            self._fdi_text = text
            self.changed.emit()

    def load_elenco(self, path: Path, *, quiet: bool = False) -> bool:
        """Read the list at ``path`` (quick: the GUI thread). False when it
        cannot be read: the reason is :attr:`elenco_error` (``quiet``: none,
        for a remembered file that is gone). The ticks start empty. Never
        raises: an unexpected failure is logged and said in general terms."""
        path = Path(path)
        try:
            elenco = self._services.officina.batch_load_elenco(path)
        except Exception as exc:  # noqa: BLE001 - a list is never a reason to lose the tab
            if not isinstance(exc, (ElencoError, OSError)):
                log.warning("elenco di Genera non leggibile: %s", type(exc).__name__)
            known = isinstance(exc, ElencoError)
            self._elenco, self._elenco_path = None, (None if quiet else path)
            self._elenco_error = "" if quiet else (str(exc) if known else strings.GENERA_ELENCO_UNREADABLE)
            self._checked = set()
            self.changed.emit()
            return False
        self._elenco, self._elenco_path, self._elenco_error = elenco, path, ""
        self._pending_elenco = None
        self._checked = set()
        self._remember(prefs.GENERA_ELENCO_KEY, str(path))
        self.changed.emit()
        return True

    def set_package_checked(self, package: str, on: bool) -> None:
        self.set_packages_checked([package], on)

    def set_packages_checked(self, packages: Iterable[str], on: bool) -> None:
        known = {name for name, _n in self._elenco.packages()} if self._elenco else set()
        before = set(self._checked)
        for package in packages:
            if package not in known:
                continue
            if on:
                self._checked.add(package)
            else:
                self._checked.discard(package)
        if self._checked != before:
            self.changed.emit()

    def set_generator(self, name: str) -> None:
        if name not in self._generators or name == self._generator:
            return
        self._generator = name
        self._follow()
        self._remember(prefs.GENERA_GENERATOR_KEY, name)
        self.changed.emit()

    def set_source_env(self, name: str) -> None:
        if name not in self._envs:
            return
        self._source_chosen = name != self._generator
        changed = name != self._source_env
        self._source_env = name
        self._remember(prefs.GENERA_SOURCE_ENV_KEY, name if self._source_chosen else "")
        if changed:
            self.changed.emit()

    def set_destination(self, path: Path | None) -> None:
        path = Path(path) if path is not None else None
        if path != self._destination:
            self._destination = path
            self._remember(prefs.GENERA_DESTINATION_KEY, str(path) if path is not None else "")
            self.changed.emit()

    def set_header_rows(self, rows: Sequence[tuple[str, str]]) -> None:
        rows = [(str(name), str(value)) for name, value in rows]
        if rows != self._headers:
            self._headers = rows
            self.changed.emit()

    def reset_headers(self) -> None:
        """"Ripristina": the table of Impostazioni again (re-read now)."""
        self._default_headers = self._load_default_headers()
        self._headers = list(self._default_headers)
        self.changed.emit()

    def set_make_zip(self, on: bool) -> None:
        if bool(on) != self._make_zip:
            self._make_zip = bool(on)
            self._remember(prefs.GENERA_ZIP_KEY, self._make_zip)
            self.changed.emit()

    def set_save_html(self, on: bool) -> None:
        if bool(on) != self._save_html:
            self._save_html = bool(on)
            self._remember(prefs.GENERA_HTML_KEY, self._save_html)
            self.changed.emit()

    def reload_config(self) -> None:
        """Impostazioni saved: generators and environments again; the header
        table too, unless the user changed it (those changes win). Before
        :meth:`activate` the table is not read at all."""
        self._read_config()
        if self._activated:
            untouched = self._headers == self._default_headers
            self._default_headers = self._load_default_headers()
            if untouched:
                self._headers = list(self._default_headers)
        self.changed.emit()

    # -- what would be generated -------------------------------------------------

    def keys(self) -> list[str]:
        return parse_keys(self._keys_text)

    def fdis(self) -> list[str]:
        """The FDIs typed (any separator, lower case as the index has them)."""
        return [fdi.lower() for fdi in parse_keys(self._fdi_text)]

    def targets(self) -> tuple[Target, ...]:
        if self._mode == "keys":
            return targets_from_keys(self.keys(), self._elenco)
        if self._mode == "elenco":
            return targets_from_packages(self._elenco, self._checked) if self._elenco else ()
        return targets_from_fdis(self.fdis())

    def call_count(self) -> int:
        """What the button counts before any lookup: distinct keys, the
        ticked packages' distinct keys, or the number of FDIs."""
        if self._mode == "keys":
            return len(self.keys())
        if self._mode == "elenco":
            return len(self._elenco.keys_of(self._checked)) if self._elenco else 0
        return len(self.fdis())

    def problems(self) -> list[str]:
        """What stops the button, in screen order; empty = ready."""
        found: list[str] = []
        if self._mode == "keys" and not self.keys():
            found.append(strings.GENERA_NEED_KEYS)
        elif self._mode == "elenco" and self._elenco is None:
            found.append(strings.GENERA_NEED_ELENCO)
        elif self._mode == "elenco" and not self.call_count():
            found.append(strings.GENERA_NEED_PACKAGE)
        elif self._mode == "fdi" and not self.fdis():
            found.append(strings.GENERA_NEED_FDI)
        if not self._generators:  # disabled in Impostazioni while the results are on screen
            found.append(strings.GENERA_NEED_GENERATOR)
        if not self._source_env:
            found.append(strings.GENERA_NEED_SOURCE)
        if self._destination is None:
            found.append(strings.GENERA_NEED_DESTINATION)
        header = next((p for row in self.header_row_problems() for p in row), None)
        if header:
            found.append(strings.GENERA_HEADER_PROBLEM.format(problem=header))
        return found

    def header_row_problems(self) -> list[list[str]]:
        return header_problems(self._headers)

    def build_request(self, targets: Sequence[Target] | None = None) -> BatchRequest:
        return BatchRequest(
            generator=self._generator, source_env=self._source_env,
            targets=tuple(self.targets() if targets is None else targets),
            header_rows=tuple(self._headers), destination=self._destination or Path(),
            save_html=self._save_html, make_zip=self._make_zip)

    def retry_request(self, report: BatchReport) -> BatchRequest:
        """The rows of ``report`` that did not end well (``genera_retry``),
        with the choices of NOW."""
        return self.build_request(self.retry_targets(report))

    @staticmethod
    def retry_targets(report: BatchReport) -> tuple[Target, ...]:
        return retry_targets(report)

    @staticmethod
    def retry_count(report: BatchReport) -> int:
        return retry_count(report)

    @staticmethod
    def needs_count(request: BatchRequest) -> bool:
        """True when the number of calls is known only from the logs: an FDI
        is as many calls as its template keys (spec: confirm over 20 CALLS)."""
        return any(t.kind == "fdi" for t in request.targets)

    def needs_confirmation(self, count: int | None = None) -> bool:
        return (self.call_count() if count is None else count) > CONFIRM_ABOVE

    # -- internals -------------------------------------------------------------------

    def _read_config(self) -> None:
        cfg = self._services.config.load()
        self._generators = [g.name for g in cfg.officina.enabled_generators()]
        self._default_generator = cfg.officina.default_generator
        self._envs = [e.name for e in cfg.enabled_environments()]
        if self._generator not in self._generators:
            self._generator = (self._default_generator if self._default_generator in self._generators
                               else (self._generators[0] if self._generators else ""))
        if self._source_env not in self._envs:
            self._source_chosen = False
        self._follow()

    def _follow(self) -> None:
        """"Chiamate da" takes the generator's name unless the user chose."""
        if self._source_chosen and self._source_env in self._envs:
            return
        self._source_chosen = False
        if self._generator in self._envs:
            self._source_env = self._generator
        elif self._source_env not in self._envs:
            self._source_env = self._envs[0] if self._envs else ""

    def _load_default_headers(self) -> list[tuple[str, str]]:
        try:
            return [(str(n), str(v)) for n, v in self._services.officina.batch_default_headers()]
        except Exception:  # noqa: BLE001 - a broken profile (or no Officina) must not break the tab
            # a warning, not an error: the tab still opens, with an empty table to fill
            log.warning("header predefiniti di Genera non disponibili", exc_info=True)
            return []

    def _restore(self) -> None:
        """The remembered choices (no disk: see the module docstring)."""
        stored = genera_prefs.read()
        if stored is None:
            return
        if stored.mode in MODES:
            self._mode = stored.mode
        if stored.generator in self._generators:
            self._generator = stored.generator
        if stored.source_env in self._envs and stored.source_env != self._generator:
            self._source_env, self._source_chosen = stored.source_env, True
        self._follow()
        if stored.destination.strip():
            self._destination = Path(stored.destination)  # as text: not checked here
        if stored.elenco.strip():
            self._pending_elenco = Path(stored.elenco)
        self._make_zip, self._save_html = stored.make_zip, stored.save_html

    _remember = staticmethod(genera_prefs.remember)
