"""Starting the GUI: one instance, one QApplication, one window.

``cli.main`` parses the arguments first and only calls :func:`run_gui` when no
headless mode was asked for — importing Qt costs ~200 ms, and ``--sync`` run by
the scheduled task must never pay it (DESIGN-ui §Concurrency, "Startup order").

Single instance: the user clicking the icon again must raise the window that is
already open instead of starting a second process that would fight over the
sync lock and the index. The guard is a ``QLocalServer`` named after the user
(one instance *per user*, so a shared machine still works); the second process
connects to it, which makes the first one raise its window, and exits.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from qtrequestory.ui import icons, strings, theme
from qtrequestory.ui.contracts import CoreServices
from qtrequestory.ui.main_window import MainWindow
from qtrequestory.ui.workers import JobRunner

__all__ = ["APP_USER_MODEL_ID", "INSTANCE_KEY_ENV_VAR", "SingleInstance", "instance_key",
           "run_gui", "set_app_user_model_id", "show_first_run_wizard", "wizard_available"]

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_MS = 300

#: Overrides the local-server name. A named pipe is machine-global, so two test
#: runs on the same box (CI and a developer, or two agents) would steal it from
#: each other and each think it is the second instance. The test harness sets
#: this to something unique per process; the application never sets it.
INSTANCE_KEY_ENV_VAR = "QTREQUESTORY_INSTANCE_KEY"

#: The taskbar identity. Without an explicit one the process (under onefile, the
#: extracted child of the bootloader) is grouped under a generic identity and
#: the taskbar shows the default Windows icon instead of ours.
APP_USER_MODEL_ID = "qtRequestory.App"


def set_app_user_model_id() -> None:
    """Give the process its own taskbar identity (Windows only, best effort).

    Must run before the ``QApplication`` exists: the shell reads the ID when the
    first window is created.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError) as exc:
        log.warning("impossibile impostare l'AppUserModelID: %s", exc)


def instance_key() -> str:
    """Name of the local server: one running instance per user."""
    override = os.environ.get(INSTANCE_KEY_ENV_VAR)
    if override:
        return override
    user = os.environ.get("USERNAME") or os.environ.get("USER") or "utente"
    return f"qtrequestory-{re.sub(r'[^A-Za-z0-9_-]+', '-', user).lower()}"


class SingleInstance(QObject):
    """Local-server guard. ``activated`` fires when another process shows up."""

    activated = Signal()

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """True when we are the first instance; False after notifying the first.

        A server that cannot listen (an exotic security policy, a name clash we
        cannot clean up) is *not* a reason to refuse to start: the guard is a
        convenience, the sync lock in the core is the real protection.
        """
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if socket.waitForConnected(CONNECT_TIMEOUT_MS):
            socket.write(b"activate")
            socket.waitForBytesWritten(CONNECT_TIMEOUT_MS)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self._key)  # a pipe left behind by a crash
        server = QLocalServer(self)
        server.newConnection.connect(self._on_new_connection)
        if not server.listen(self._key):
            log.warning("impossibile attivare il controllo di istanza singola: %s",
                        server.errorString())
            return True
        self._server = server
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self._key)
            self._server = None

    def _on_new_connection(self) -> None:
        if self._server is not None:
            connection = self._server.nextPendingConnection()
            if connection is not None:
                connection.disconnectFromServer()
        self.activated.emit()


def wizard_available() -> bool:
    """Whether ``ui.wizard`` (Task 10) is part of this build."""
    return _wizard_entry_point() is not None


def show_first_run_wizard(services: CoreServices, runner: JobRunner, parent: Any = None) -> Any:
    """Run the first-run wizard; ``None`` when cancelled or not available.

    The import is lazy and its absence tolerated so the shell runs — and is
    tested — without the wizard module.
    """
    entry = _wizard_entry_point()
    if entry is None:
        log.warning("%s", strings.WIZARD_UNAVAILABLE)
        return None
    return entry(services, runner, parent)


def _wizard_entry_point() -> Callable[..., Any] | None:
    try:
        from qtrequestory.ui.wizard import run_first_run_wizard
    except ImportError:
        return None
    return run_first_run_wizard


def configure_application(app: QApplication, version: str = "") -> None:
    """Name, icon and theme — everything Qt derives from the application.

    The names are also what ``QSettings(ORG_NAME, APP_NAME)`` keys off, so they
    must match the constants the pages use. The theme goes last: its mode is
    read from ``QSettings``, which keys off those names.
    """
    app.setApplicationName(strings.APP_NAME)
    app.setApplicationDisplayName(strings.APP_NAME)
    app.setOrganizationName(strings.ORG_NAME)
    app.setApplicationVersion(version)
    app.setWindowIcon(icons.app_icon())
    theme.apply(app)


def run_gui(services: CoreServices, argv: list[str] | None = None, *,
            run_startup_tasks: bool = True) -> int:
    """Start the GUI and return the exit code for ``cli.main``.

    Once the window is visible — never before (DESIGN-ui "Startup order") —
    ``MainWindow.startup_tasks`` indexes what is pending and runs a non-forced
    sync, unless the first-run wizard asked for a sync of its own (which
    indexes too). ``run_startup_tasks=False`` is for callers that must not
    start background jobs.
    """
    set_app_user_model_id()
    app = QApplication.instance() or QApplication(list(argv) if argv is not None else sys.argv)
    configure_application(app, services.version())

    # Neither the guard nor the runner is parented to the application: they
    # must die with this function, or the window they capture would outlive it.
    guard = SingleInstance(instance_key())
    if not guard.try_acquire():
        log.info("qtRequestory è già in esecuzione: porto in primo piano quella finestra")
        return 0

    runner = JobRunner()
    try:
        start_sync = False
        import_sources: tuple = ()
        if services.config.is_first_run():
            if wizard_available():
                result = show_first_run_wizard(services, runner)
                if result is None:  # the user cancelled: nothing is configured
                    return 0
                start_sync = bool(getattr(result, "start_sync", False))
                import_sources = tuple(getattr(result, "import_sources", ()))
            else:
                log.warning("%s", strings.WIZARD_UNAVAILABLE)

        window = MainWindow(services, runner)
        guard.activated.connect(lambda: _raise(window))
        window.show()
        then = (window.start_sync if start_sync
                else window.startup_tasks if run_startup_tasks else None)
        if import_sources:
            # The wizard's "li importerò alla fine": first the import, then the
            # sync (which would otherwise hold the lock the copy needs).
            window.open_import(import_sources, on_closed=then)
        elif start_sync:
            window.start_sync()
        elif run_startup_tasks:
            # The window is the timer's context: a window already gone by the
            # time the loop turns cancels the call instead of crashing it.
            QTimer.singleShot(0, window, window.startup_tasks)
        return app.exec()
    finally:
        runner.shutdown()
        guard.close()


def _raise(window: MainWindow) -> None:
    """Bring the existing window back to the front (another launch happened)."""
    window.setWindowState(
        (window.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive
    )
    window.show()
    window.raise_()
    window.activateWindow()
