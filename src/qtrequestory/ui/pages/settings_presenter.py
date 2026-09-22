"""The rules behind the Impostazioni page, with no widget in sight.

:class:`SettingsPresenter` owns what the form *means* — what it is as a
``Config``, whether it differs from what is on disk, whether it validates — and
is the only caller of ``config.save`` in the application. ``settings_page.py``
owns the widgets, the dialogs and the background jobs, and decides nothing.

Keeping the two apart is what makes the rules testable without a single click,
and it keeps each file down to something that can be read in one sitting.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import (
    Config,
    CoreServices,
    Environment,
    ScheduleSettings,
    parse_hhmm,
)

__all__ = [
    "FormValues", "SettingsPresenter", "canonical_schedule", "check_reachable", "form_of",
    "normalised",
]

#: How ``ScheduleSettings.start_time`` is spelled once it has been through a widget.
TIME_FORMAT = "%H:%M"


@dataclass(frozen=True)
class FormValues:
    """What the widgets currently say, as plain data.

    Dirty tracking compares two of these rather than two ``Config`` objects:
    the form holds *text*, and ``Path("")`` and ``Path(".")`` are the same
    configuration but a very different thing to show the user.
    """

    mirror_root: str
    environments: list[Environment] = field(default_factory=list)
    editor_path: str = ""
    window_days: int = 30
    output_dir: str = ""
    #: The four automatic-synchronisation fields, already in the core's own
    #: shape: a frozen dataclass of scalars, so comparing two forms (dirty
    #: tracking) and handing it to ``config.validate`` both work unchanged.
    schedule: ScheduleSettings = field(default_factory=ScheduleSettings)


def normalised(text: str) -> str:
    """A path field's text in the platform's own spelling, or ``""``.

    Qt's file dialogs return forward slashes even on Windows, so picking the
    very same folder the configuration already holds would otherwise read as an
    edit: [Salva] would light up and a save would broadcast a ``config_changed``
    that changed nothing.
    """
    text = text.strip()
    return str(Path(text)) if text else ""


def canonical_schedule(schedule: ScheduleSettings) -> ScheduleSettings:
    """The schedule in the spelling the widgets produce.

    Same idea as :func:`normalised` for paths: ``config.validate`` accepts
    ``"7:30"`` and the task registers 07:30, but a ``QTimeEdit`` can only hand
    back ``"07:30"``. Comparing the raw strings would call that an edit —
    [Salva] lit on a form nobody touched. An unparsable value is left alone, so
    it reads as the edit it will be (the field shows the default, and saving
    repairs the file).
    """
    parsed = parse_hhmm(schedule.start_time)
    if parsed is None:
        return schedule
    return dataclasses.replace(schedule, start_time=parsed.strftime(TIME_FORMAT))


def form_of(cfg: Config) -> FormValues:
    """The form a configuration loads into."""
    return FormValues(
        mirror_root=str(cfg.mirror_root),
        environments=list(cfg.environments),
        editor_path=str(cfg.editor_path) if cfg.editor_path is not None else "",
        window_days=cfg.default_window_days,
        output_dir=str(cfg.output_dir) if cfg.output_dir is not None else "",
        schedule=canonical_schedule(cfg.schedule),
    )


def _optional_path(text: str) -> Path | None:
    """An empty field means "use the default", not ``Path("")``."""
    text = text.strip()
    return Path(text) if text else None


def check_reachable(sync, envs: Sequence[str], cancel) -> list[tuple[str, bool]]:
    """One blocking probe per environment; runs in a worker, stops on cancel."""
    results: list[tuple[str, bool]] = []
    for name in envs:
        if cancel.is_set():
            break
        results.append((name, sync.check_reachable(name)))
    return results


class SettingsPresenter(QObject):
    """Form in, configuration out — and the only ``config.save`` call."""

    config_changed = Signal(object)

    def __init__(self, services: CoreServices, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.loaded: Config = services.config.load()

    def load(self) -> Config:
        self.loaded = self._services.config.load()
        return self.loaded

    def to_config(self, form: FormValues) -> Config:
        """The loaded configuration with the edited fields replaced.

        A copy, never a mutation: the fields this page does not show
        (``compaction_time``, ``sync``, ``index``, ``log_level``) must survive
        a save untouched.
        """
        return dataclasses.replace(
            self.loaded,
            mirror_root=Path(form.mirror_root.strip()),
            environments=list(form.environments),
            editor_path=_optional_path(form.editor_path),
            default_window_days=form.window_days,
            output_dir=_optional_path(form.output_dir),
            schedule=form.schedule,
        )

    def is_dirty(self, form: FormValues) -> bool:
        return form != form_of(self.loaded)

    def mirror_moved(self, form: FormValues) -> bool:
        """Asked *before* saving: afterwards the old root is gone."""
        return Path(form.mirror_root.strip()) != self.loaded.mirror_root

    def errors(self, form: FormValues) -> list[str]:
        """Italian messages from ``config.validate``, plus the one rule the core
        cannot check: a configuration without a mirror root is meaningless to a
        user even though ``Path("")`` validates."""
        found = list(self._services.config.validate(self.to_config(form)))
        if not form.mirror_root.strip():
            found.insert(0, strings.SETTINGS_ERROR_NO_MIRROR)
        return found

    def save(self, form: FormValues) -> list[str]:
        """Persist ``form``; the returned errors mean nothing was written."""
        found = self.errors(form)
        if found:
            return found
        cfg = self.to_config(form)
        self._services.config.save(cfg)
        self.loaded = cfg
        self.config_changed.emit(cfg)
        return []
