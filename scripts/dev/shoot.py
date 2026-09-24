"""Screenshots of the real MainWindow, for looking at UI changes (dev only).

    python scripts/dev/shoot.py [--modes light dark] [--out DIR] [--platform windows]

Not shipped: qtRequestory.spec builds from ``scripts/entrypoint.py`` only and
the wheel packages ``src/`` only.

Safe by construction:

* the core is ``tests/fakes/fake_core.py`` — no network, no SQLite, no
  scheduled tasks, nothing under the real mirror;
* ``QTREQUESTORY_HOME``, ``USERPROFILE``, ``LOCALAPPDATA`` and ``APPDATA`` point
  into a fresh temp directory *before* anything is imported, and ``QSettings``
  is redirected to INI files there, so the registry is never touched;
* the window is never shown on screen (``WA_DontShowOnScreen``) and has its own
  single-instance key, so a running qtRequestory is left alone.

Every requested mode is applied to the *same* window with ``theme.apply``,
which also exercises a live theme switch. PNGs are named
``<mode>-<nn>-<what>.png``. Later tasks add their own states to ``SCENES``.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _isolate(tmp: Path) -> None:
    for var in ("QTREQUESTORY_HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA"):
        target = tmp / var.lower()
        target.mkdir(parents=True, exist_ok=True)
        os.environ[var] = str(target)
    os.environ["QTREQUESTORY_INSTANCE_KEY"] = f"qtrequestory-shoot-{os.getpid()}"
    sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modes", nargs="+", default=["light", "dark"],
                        choices=["light", "dark", "system"])
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "qtr-shots")
    parser.add_argument("--size", default="1400x800",
                        help="window size WxH, e.g. 1366x768 or 1920x1080")
    parser.add_argument("--page", choices=["all", "search"], default="all",
                        help="only the Ricerca scenes with 'search'")
    parser.add_argument("--platform", default="windows",
                        help="Qt platform plugin; 'offscreen' has no real fonts")
    parser.add_argument("--only", nargs="+", default=None, metavar="SCENE",
                        help="shoot only the scenes whose name contains one of these")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="qtr-shoot-"))
    _isolate(tmp)
    os.environ["QT_QPA_PLATFORM"] = args.platform
    args.out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QEventLoop, QSettings, Qt
    from PySide6.QtWidgets import QApplication

    ini = QSettings.Format.IniFormat
    QSettings.setDefaultFormat(ini)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(ini, scope, str(tmp / "settings"))

    app = QApplication([])
    from qtrequestory.ui import theme
    from qtrequestory.ui.app import configure_application
    from qtrequestory.ui.main_window import MainWindow
    from qtrequestory.ui.workers import JobRunner
    from tests.fakes.fake_core import build_fake_core

    configure_application(app, "0.0-shoot")

    def pump(ms: int = 300) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.01)

    services = build_fake_core(tmp / "core")
    runner = JobRunner()
    window = MainWindow(services, runner)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    width, height = (int(part) for part in args.size.lower().split("x"))
    window.resize(width, height)
    window.show()
    pump(500)

    search = window.page("search")  # builds its own preview pane

    def search_results() -> None:
        window.show_page("search")
        search.set_grouped(True)
        search.form.set_fdi("aaaaaaaa")
        search.run_search()
        pump(900)

    def search_start() -> None:
        window.show_page("search")
        search.form.set_env("svil")
        search.form.set_env("coll")  # back to the start state, recents listed
        pump(300)

    def search_flat() -> None:
        window.show_page("search")
        search.set_grouped(False)
        search.form.set_fdi("")
        search.form.set_template_key("MOD_ALPHA_SUMMARY_OFFER_FIX_B")
        search.run_search()
        pump(900)

    def search_details() -> None:
        search_results()
        search.preview_widget().show_tab(1)
        pump(200)

    def search_no_results() -> None:
        window.show_page("search")
        search.preview_widget().show_tab(0)
        search.form.set_template_key("")
        search.form.set_fdi("ffff")
        search.run_search()
        pump(900)

    def search_period():
        """The custom-range popup, grabbed on its own."""
        window.show_page("search")
        search.form.period.open_popup()
        pump(300)
        return search.form.period.popup

    def context_menu():
        """The row menu, grabbed on its own (a popup is not in window.grab)."""
        search_results()
        menu = search.build_context_menu(search.selected_hit())
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        menu.popup(window.mapToGlobal(window.rect().center()))
        pump(300)
        return menu

    def sync_archive() -> None:
        """A realistic 60-day archive: quiet weekends as 0-byte days, coll
        complete, svil with a day still on the server and one the server purged
        before it was downloaded, the scheduled task registered (all fake: no
        real task is touched)."""
        from datetime import date, datetime, timedelta

        today = date.today()
        days = [today - timedelta(days=i) for i in range(1, 61)]
        weekdays = {d for d in days if d.weekday() < 5}
        weekends = {d for d in days if d.weekday() >= 5}
        newest = sorted(weekdays, reverse=True)
        pending, lost = newest[1], newest[7]  # two weekdays ago, and last week
        services.index.set_local_days("coll", weekdays, empty=weekends)
        services.index.set_local_days("svil", weekdays - {pending, lost}, empty=weekends)
        services.index.set_server_days("svil", listed={pending}, seen={lost})
        yesterday = datetime.combine(today - timedelta(days=1), datetime.min.time())
        services.sync.set_env_status("svil", n_local_files=len(weekdays) - 2,
                                     local_bytes=2_254_857_830,
                                     last_success=yesterday.replace(hour=18, minute=40))
        services.sync.set_env_status("coll", n_local_files=len(weekdays),
                                     local_bytes=4_187_593_113)
        services.scheduler.exe = Path(tmp / "qtRequestory.exe")
        services.scheduler.set_status(registered=True, exe_matches=True, state="Pronto",
                                      next_run=f"{today:%d/%m/%Y} 12:00")
        page = window.page("sync")
        page.auto_card.refresh_scheduler()
        page.on_data_changed()

    def sync_idle() -> None:
        sync_archive()
        window.show_page("sync")
        pump(600)

    def search_gap() -> None:
        """Ricerca on svil after sync_archive: one day to download, one lost."""
        window.show_page("search")
        search.form.set_env("svil")
        pump(300)

    def sync_log_open() -> None:
        window.show_page("sync")
        window.page("sync").log_panel.expand()
        pump(300)

    def sync_running() -> None:
        """Mid-run: chip "in corso", status bar "Sincronizzazione coll i/n…"."""
        window.page("sync").log_panel.expand(False)
        window.show_page("sync")
        services.sync.step_delay = 0.8
        window.page("sync").start_sync()
        pump(1500)

    def sync_run() -> None:
        window.show_page("sync")
        services.sync.step_delay = 0.0
        if runner.is_running("sync"):
            pump(12000)
        services.sync.set_unreachable("svil")
        window.page("sync").start_sync()
        pump(4000)

    def toast() -> None:
        window.show_page("search")
        window.show_toast("JSON copiato · 157 KB", tone="ok", ms=60_000)

    search_scenes: list[tuple[str, Callable[[], None]]] = [
        ("ricerca-avvio", search_start),
        ("ricerca", search_results),
        ("ricerca-elenco", search_flat),
        ("ricerca-dettagli", search_details),
        ("ricerca-nessun-risultato", search_no_results),
        ("ricerca-periodo", search_period),
    ]
    scenes: list[tuple[str, Callable[[], None]]] = [
        *search_scenes,
        ("toast", toast),
        ("menu", context_menu),
        ("sync-riposo", sync_idle),
        ("ricerca-giorni-mancanti", search_gap),
        ("sync-in-corso", sync_running),
        ("sync", sync_run),
        ("sync-registro", sync_log_open),
        ("impostazioni", lambda: window.show_page("settings")),
        ("info", lambda: window.show_page("about")),
    ]

    settings = window.page("settings")

    def settings_section(key: str, dirty: bool = False, banner: bool = False):
        def prepare() -> None:
            settings.reload()
            window.show_page("settings")
            settings.show_section(key)
            if dirty:
                settings.set_window_days(7)
            if banner:
                settings._on_schedule_failed("", "accesso negato")
        return prepare

    scenes += [
        (f"impostazioni-{key}", settings_section(key))
        for key in ("archive", "environments", "automation", "search", "editor", "advanced")
    ]
    scenes += [
        ("impostazioni-modifiche", settings_section("search", dirty=True)),
        ("impostazioni-banner", settings_section("automation", dirty=True, banner=True)),
    ]

    good_config = services.config.load()

    def mirror_root(root: Path | None) -> None:
        """``None`` = the fake's valid folder; ``Path("")`` = what the CLI refuses."""
        import dataclasses

        services.config.config = (good_config if root is None
                                  else dataclasses.replace(good_config, mirror_root=root))
        # Only the banners: a full on_config_changed() rebuilds the env cards,
        # and without an event loop the old ones are never deleted (deleteLater).
        for name in ("search", "sync"):
            window.page(name).mirror_banner.refresh()
        window.page("sync").run_label.hide()  # the refusal line of the last mode

    def search_no_folder() -> None:
        mirror_root(Path(""))
        search_start()

    def sync_no_folder() -> None:
        mirror_root(Path(""))
        window.show_page("sync")
        window.page("sync").start_sync()  # refused: the run line says why
        pump(300)

    scenes += [
        ("ricerca-cartella-non-valida", search_no_folder),
        ("sync-cartella-non-valida", sync_no_folder),
    ]

    # -- import (1.1.0): strays in the mirror, a colleague's folder, the dialog --
    import threading

    from qtrequestory.ui.import_dialog import STEP_COPY, STEP_REPORT, STEP_RESULT, ImportDialog
    from qtrequestory.ui.import_state import ArchiveWatch
    from tests.test_archive import LOG, LOG2, OTHER, put

    core_root = tmp / "core"
    colleague = core_root / "log di Mario"

    def import_tree() -> None:
        """Every verdict once, rebuilt for each mode (the import consumes it)."""
        import shutil

        shutil.rmtree(colleague, ignore_errors=True)
        m = services.config.load().mirror_root
        for env, days in (("coll", (2, 3, 11, 12)), ("svil", (3, 4))):
            for d in days:  # what the previous mode imported
                (m / env / "2026" / "09" / f"202609{d:02d}.txt").unlink(missing_ok=True)
        for rel in ("coll/2026/9/20260911.txt", "coll/2026/9/20260912.txt", "vari/20260908.txt"):
            put(m, rel, LOG)
        put(colleague, "coll/20260902.txt", LOG)
        put(colleague, "coll/2026-09-03.txt", LOG2)
        put(colleague, "svil/03092026.txt", LOG)
        put(colleague, "svil/2026_09_04.txt", LOG)
        put(colleague, "da smistare/20260905.txt", LOG)
        put(colleague, "da smistare/20260906.txt", LOG)
        put(colleague, "settembre.zip", b"PK")
        put(colleague, "note.txt", b"appunti")
        put(m, "coll/2026/09/20260901.txt", LOG)
        put(colleague, "coll/20260901.txt", LOG)                 # already in the archive
        put(m, "svil/2026/09/20260907.txt", OTHER)
        put(colleague, "svil/20260907.txt", LOG)                 # conflict
        watch = ArchiveWatch.existing(runner)
        if watch is not None:
            watch.refresh()
        pump(600)

    def stray_banner(page: str):
        def prepare() -> None:
            import_tree()
            window.show_page(page)
            pump(300)
        return prepare

    dialogs: dict[str, ImportDialog] = {}

    def dialog_report():
        import_tree()
        dialog = ImportDialog(services, runner, [colleague], window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.show()
        pump(900)
        assert dialog.step() == STEP_REPORT
        dialogs["d"] = dialog
        return dialog

    gate = threading.Event()

    def dialog_copy():
        dialog = dialog_report()
        real = services.archive.import_

        def slow(report, *, cancel=None, progress=None):
            def step(done, total, rel):
                progress(done, total, rel)
                if done == 2:
                    gate.wait(10)
            return real(report, cancel=cancel, progress=step)

        services.archive.import_ = slow
        gate.clear()
        dialog.primary_button.click()
        pump(900)
        assert dialog.step() == STEP_COPY
        return _Kept(dialog)

    def dialog_result():
        dialog = dialogs["d"]
        gate.set()
        pump(900)
        del services.archive.import_
        assert dialog.step() == STEP_RESULT
        return _Kept(dialog)

    def dialog_deleted():
        dialog = dialogs["d"]
        dialog.result_view.delete_button.click()
        pump(900)
        return dialog

    class _Kept:
        """A target the loop must not close: the next scene continues it."""

        def __init__(self, widget) -> None:
            self.widget = widget

        def grab(self):
            return self.widget.grab()

        def close(self) -> None:
            pass

        def deleteLater(self) -> None:
            pass

    def settings_import() -> None:
        import_tree()
        settings.reload()
        window.show_page("settings")
        settings.show_section("archive")
        pump(300)

    scenes += [
        ("ricerca-log-fuori-struttura", stray_banner("search")),
        ("sync-log-fuori-struttura", stray_banner("sync")),
        ("impostazioni-archivio-importa", settings_import),
        ("importa-1-elenco", dialog_report),
        ("importa-2-copia", dialog_copy),
        ("importa-3-risultato", dialog_result),
        ("importa-4-cestino", dialog_deleted),
    ]
    if args.page == "search":
        scenes = [*search_scenes, ("toast", toast), ("menu", context_menu)]
    if args.only:
        scenes = [scene for scene in scenes if any(o in scene[0] for o in args.only)]

    try:
        for mode in args.modes:
            theme.apply(app, theme.Mode(mode))
            theme.save_mode(theme.Mode(mode))  # what the Aspetto selector shows
            mirror_root(None)  # the previous mode's last scenes broke it on purpose
            pump(300)
            for number, (name, prepare) in enumerate(scenes, 1):
                target = prepare() or window  # a scene may name its own widget
                pump(300)
                path = args.out / f"{mode}-{number:02d}-{name}.png"
                target.grab().save(str(path))
                if target is search.form.period.popup:
                    target.hide()
                elif target is not window:
                    target.close()
                    target.deleteLater()
                window.toast.hide()  # one scene only
                if settings.is_dirty():
                    # Discard what a "-modifiche" scene typed: left dirty, the
                    # next show_page() asks Salva / Scarta / Annulla in a modal
                    # nobody answers, and the run hangs (can_leave()).
                    settings.reload()
                # The title bar is not in window.grab(): print it next to the shot.
                print("saved", path, "|", window.windowTitle())
    finally:
        runner.shutdown(3000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
