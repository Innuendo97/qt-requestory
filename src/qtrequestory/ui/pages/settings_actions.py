"""What the Impostazioni page *does* besides editing the form.

The background jobs ([Ricostruisci indice], the reindex after a new mirror
folder, [Verifica]), the file and folder dialogs, the Explorer shortcuts and
the leave question. :class:`SettingsActions` is a mixin of
:class:`~qtrequestory.ui.pages.settings_page.SettingsPage`, kept apart only so
each file reads in one sitting; it uses the page's ``_services``, ``_runner``,
``_window``, ``_presenter`` and the widgets the sections created.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.pages.settings_presenter import check_reachable, normalised
from qtrequestory.ui.pages.settings_widgets import PathField

__all__ = ["CHECK_JOB", "INDEX_JOB", "SettingsActions", "ask_leave"]

#: Exclusive job name: an index run refuses a second one while it works.
INDEX_JOB = "index"
CHECK_JOB = "check-envs"


class SettingsActions:
    """Jobs, dialogs and folders of the Impostazioni page (a mixin).

    What it relies on from :class:`SettingsPage`:

    * services and state: ``_services`` (``CoreServices``), ``_runner``
      (``JobRunner``), ``_window`` (``MainWindow`` or a stub), ``_presenter``
      (``SettingsPresenter``, for ``loaded``);
    * behaviour: ``can_leave()``, ``reload()``;
    * widgets built by ``settings_sections``: ``env_table``, ``check_label``,
      ``mirror_path`` and ``editor_path`` (``PathField``).
    """

    def _offer_reindex(self) -> None:
        answer = QMessageBox.question(
            self, strings.SETTINGS_REINDEX_TITLE, strings.SETTINGS_REINDEX_QUESTION
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_index(full_rebuild=False)

    # -- jobs --------------------------------------------------------------

    def rebuild_index(self) -> None:
        if self._index_refused():
            return
        answer = QMessageBox.question(
            self, strings.SETTINGS_REBUILD_TITLE, strings.SETTINGS_REBUILD_QUESTION
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_index(full_rebuild=True)

    def _index_refused(self) -> bool:
        """An empty or relative log folder: the index would land in the CWD."""
        problems = self._services.config.mirror_root_errors(self._presenter.loaded)
        if problems:
            self._status(strings.SETTINGS_INDEX_REFUSED.format(problem=problems[0]))
        return bool(problems)

    def _start_index(self, *, full_rebuild: bool) -> None:
        if self._index_refused():
            return
        envs = [e.name for e in self._presenter.loaded.enabled_environments()]
        job = self._runner.submit(
            INDEX_JOB, self._services.index.update, envs, full_rebuild=full_rebuild
        )
        if job is None:  # already running, or the application is closing
            return
        job.signals.result.connect(self._on_index_done)
        job.signals.error.connect(self._on_index_failed)
        self._status(strings.SETTINGS_INDEX_STARTED)

    def _on_index_done(self, report: object) -> None:
        self._status(
            strings.SETTINGS_INDEX_DONE.format(n=getattr(report, "indexed_files", 0))
        )

    def _on_index_failed(self, _kind: str, message: str) -> None:
        self._status(strings.SETTINGS_INDEX_FAILED.format(message=message))

    def check_environments(self) -> None:
        # The rows as they are on screen, URLs included: a URL corrected but not
        # yet saved is exactly the one worth probing.
        envs = [e for e in self.env_table.environments() if e.name]
        self.check_label.show()
        if not envs:
            self.check_label.setText(strings.SETTINGS_CHECK_NONE)
            return
        job = self._runner.submit(CHECK_JOB, check_reachable, self._services.sync, tuple(envs))
        if job is None:  # the application is closing: no job, so no "in corso…"
            return
        self.check_label.setText(strings.SETTINGS_CHECK_RUNNING)
        job.signals.result.connect(self._on_checked)
        # Without this the label would sit on "Verifica in corso…" for ever if
        # a probe raised something `check_reachable` does not swallow.
        job.signals.error.connect(self._on_check_failed)

    def _on_checked(self, results: object) -> None:
        parts = [
            (strings.SETTINGS_CHECK_REACHABLE if ok else strings.SETTINGS_CHECK_UNREACHABLE)
            .format(name=name)
            for name, ok in results or ()
        ]
        self.check_label.setText(
            strings.SETTINGS_CHECK_SEPARATOR.join(parts) or strings.SETTINGS_CHECK_NONE
        )

    def _on_check_failed(self, _kind: str, message: str) -> None:
        self.check_label.setText(strings.SETTINGS_CHECK_FAILED.format(message=message))

    # -- dialogs and folders -----------------------------------------------

    def browse_folder(self, field: PathField, caption: str) -> None:
        chosen = QFileDialog.getExistingDirectory(self, caption, field.text())
        if chosen:  # empty means the user cancelled: leave the field alone
            field.setText(normalised(chosen))

    def browse_editor(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, strings.SETTINGS_EDITOR_CAPTION, self.editor_path.text(),
            strings.SETTINGS_EDITOR_FILTER,
        )
        if chosen:
            self.editor_path.setText(normalised(chosen))

    def detect_editor(self) -> None:
        found = self._services.config.detect_editor()
        if found is None:
            self._status(strings.SETTINGS_EDITOR_NOT_FOUND)
            return
        self.editor_path.setText(str(found))
        self._status(strings.SETTINGS_EDITOR_FOUND.format(path=found))

    def import_environments(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, strings.ENV_IMPORT_CAPTION, "", strings.ENV_IMPORT_FILTER
        )
        if not chosen:
            return
        try:
            self.env_table.import_from_file(
                Path(chosen), self._services.config.import_environments_file
            )
        except ValueError as exc:
            QMessageBox.warning(
                self, strings.ENV_IMPORT_ERROR_TITLE,
                strings.ENV_IMPORT_ERROR.format(error=exc),
            )

    def open_mirror(self) -> None:
        text = self.mirror_path.text().strip()
        if text:
            self._services.extract.open_folder(Path(text))

    def open_config_folder(self) -> None:
        self._services.extract.open_folder(self._services.config.config_path().parent)

    def rerun_wizard(self) -> None:
        """Settle the form, then run the wizard.

        The wizard writes ``config.json`` itself and may then start a sync,
        which switches page. A form still dirty at that point would ask
        "Salvare le modifiche?" *after* the wizard, and Salva would write the
        stale values over the configuration just saved. So the question comes
        first — Salva / Scarta, or Annulla, which does not open the wizard —
        and the new configuration reaches the form through the window's
        broadcast (:meth:`on_config_changed`) before any page switch.
        """
        hook = getattr(self._window, "rerun_wizard", None)
        if not callable(hook) or not self.can_leave():
            return
        hook()
        # A window without the broadcast: catch up here. A cancelled wizard
        # wrote nothing, and the form (already clean) stays as it is.
        if self._services.config.load() != self._presenter.loaded:
            self.reload()

    def on_config_changed(self, _cfg: object) -> None:
        """The configuration was written elsewhere (the wizard): show it.

        ``MainWindow`` never sends a page its own save, so this is only ever
        someone else's configuration, and the form becomes clean with it.
        """
        self.reload()

    def _status(self, text: str) -> None:
        setter = getattr(self._window, "set_status", None)
        if callable(setter):
            setter(text)

    def _notify(self, text: str) -> None:
        """A confirmation: the window's toast when it has one, else the status line."""
        toast = getattr(self._window, "show_toast", None)
        if callable(toast):
            toast(text, "ok")
        else:
            self._status(text)


def ask_leave(parent: QWidget) -> str:
    """"Salvare le modifiche?" → ``"save"``, ``"discard"`` or ``"cancel"``."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(strings.SETTINGS_LEAVE_TITLE)
    box.setText(strings.SETTINGS_LEAVE_QUESTION)
    box.setInformativeText(strings.SETTINGS_LEAVE_INFO)
    save = box.addButton(strings.SETTINGS_LEAVE_SAVE, QMessageBox.ButtonRole.AcceptRole)
    discard = box.addButton(strings.SETTINGS_LEAVE_DISCARD, QMessageBox.ButtonRole.DestructiveRole)
    cancel = box.addButton(strings.BTN_CANCEL, QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(save)
    box.setEscapeButton(cancel)
    try:
        box.exec()
        clicked = box.clickedButton()
        return "save" if clicked is save else "discard" if clicked is discard else "cancel"
    finally:
        box.deleteLater()
