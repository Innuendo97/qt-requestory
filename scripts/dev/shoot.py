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
import dataclasses
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

    def splash_scene():
        """The startup splash (D2), grabbed on its own at its second phase."""
        from PySide6.QtGui import QGuiApplication

        from qtrequestory.ui import strings
        from qtrequestory.ui.splash import Splash

        shown = Splash("0.0-shoot", QGuiApplication.primaryScreen())
        shown.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        shown.showMessage(strings.SPLASH_PAGES)
        return shown

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

    def header_sync(pending: bool = False, lost: bool = False, panel: bool = False,
                    running: bool = False):
        """D3: the sync chip in the header — all fine, amber (a day still on
        the server), red (a day purged) — optionally with its panel open."""
        from datetime import date, datetime, timedelta

        page = window.page("sync")
        for _ in range(100):  # the previous mode's running scene: let it end
            if not runner.is_running("sync"):
                break
            pump(200)
        today = date.today()
        days = [today - timedelta(days=i) for i in range(1, 61)]
        weekdays = {d for d in days if d.weekday() < 5}
        weekends = {d for d in days if d.weekday() >= 5}
        newest = sorted(weekdays, reverse=True)
        missing_p, missing_l = newest[1], newest[7]
        at_nine = datetime.combine(today, datetime.min.time()).replace(hour=9)
        for env in ("coll", "svil"):
            services.sync.set_ok(env)
            services.sync.set_env_status(env, fresh=True, last_success=at_nine,
                                         n_local_files=len(weekdays), local_bytes=2_254_857_830)
            services.index.set_local_days(env, weekdays, empty=weekends)
            services.index.set_server_days(env)
        page.presenter.reachable.clear()
        page.presenter.outcomes.clear()
        page.presenter.failures.clear()
        if pending or lost:
            services.index.set_local_days(
                "coll", weekdays - ({missing_p} if pending else set()) - ({missing_l} if lost else set()),
                empty=weekends)
            services.index.set_server_days("coll", listed={missing_p} if pending else (),
                                           seen={missing_l} if lost else ())
        window.show_page("search")
        for key in window.pages():  # the Ricerca gap banner reads the same days
            refresh = getattr(window.page(key), "on_data_changed", None)
            if callable(refresh):
                refresh()
        page.presenter.emit_summary()
        if running:
            services.sync.step_delay = 0.8
            page.start_sync()
            pump(1200)
        pump(300)
        if not panel:
            return window
        if window.sync_panel is None:
            window.toggle_sync_panel()
            window.sync_panel.close()
        window.sync_panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        window.toggle_sync_panel()
        pump(300)
        return _WithMenu(window.sync_panel)

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
        ("splash", splash_scene),
        *search_scenes,
        ("toast", toast),
        ("menu", context_menu),
        ("sync-riposo", sync_idle),
        ("ricerca-giorni-mancanti", search_gap),
        ("testata-sync-tutto-ok", lambda: header_sync()),
        ("testata-sync-ambra", lambda: header_sync(pending=True)),
        ("testata-sync-rosso", lambda: header_sync(lost=True)),
        ("testata-sync-pannello", lambda: header_sync(pending=True, lost=True, panel=True)),
        ("testata-sync-pannello-ok", lambda: header_sync(panel=True)),
        ("testata-sync-in-corso", lambda: header_sync(panel=True, running=True)),
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
        for key in ("archive", "environments", "automation", "search", "officina", "editor",
                    "advanced")
    ]
    scenes += [
        ("impostazioni-modifiche", settings_section("search", dirty=True)),
        ("impostazioni-banner", settings_section("automation", dirty=True, banner=True)),
    ]

    def settings_officina_problems(scroll_to: str):
        """Impostazioni → Officina with what the section reports inline: a
        OneDrive folder (a warning), a PROD generator, the default disabled,
        a Host header. ``scroll_to`` names the widget brought into view."""
        def prepare() -> None:
            settings.reload()
            window.show_page("settings")
            settings.show_section("officina")
            s = settings.officina_section
            onedrive = tmp / "userprofile" / "OneDrive - Esempio"
            os.environ["OneDrive"] = str(onedrive)
            s.folder.setText(str(onedrive / "Officina"))
            table = s.generators
            row = table.add_row()
            table.item(row, table.COL_NAME).setText("PROD")
            table.item(row, table.COL_URL).setText(
                "https://inspire-prod.example.invalid/rest/api/submit-job/documentGenerator")
            row = table.add_row()
            table.item(row, table.COL_NAME).setText("coll")
            table.item(row, table.COL_URL).setText(
                "https://example.invalid/coll/rest/api/submit-job/documentGenerator?sv=1&sig=abc")
            table.item(0, table.COL_ENABLED).setCheckState(Qt.CheckState.Unchecked)
            heads = s.headers
            row = heads.add_row()
            heads.item(row, heads.COL_NAME).setText("Host")
            heads.item(row, heads.COL_VALUE).setText("example.invalid")
            pump(100)
            settings.scroll.ensureWidgetVisible(getattr(s, scroll_to), 0, 0)
        return prepare

    def settings_save_blocked() -> None:
        """A PROD row in Officina, then an edit in Ricerca: the bar says why
        Salva is off and offers [Mostra]."""
        settings.reload()
        window.show_page("settings")
        table = settings.officina_section.generators
        row = table.add_row()
        table.item(row, table.COL_NAME).setText("PROD")
        table.item(row, table.COL_URL).setText("https://example.invalid/g")
        settings.show_section("search")
        settings.set_window_days(7)

    scenes += [
        ("impostazioni-salva-bloccato", settings_save_blocked),
        ("impostazioni-officina-avvisi", settings_officina_problems("folder")),
        ("impostazioni-officina-generatori", settings_officina_problems("default_combo")),
        ("impostazioni-officina-intestazioni", settings_officina_problems("remove_header_button")),
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
        # The core now answers "nothing there" without a folder: re-read the
        # Ricerca coverage line so the next scene does not keep the last one.
        search.on_data_changed()
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
        # Path("") is the CWD: the synthetic logs would land in the worktree.
        assert m.is_absolute(), f"import_tree needs the scene mirror, not {m!r}"
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
    # -- Officina viewer (Task 6): two DocViews in sync, synthetic PDFs only ----
    officina_docs: dict[str, object] = {}

    def officina_pdfs():
        """TARGET / TO-BE PDFs (synthetic words) and their differences, made once."""
        if not officina_docs:
            from qtrequestory.officina.compare.extract_pdf import extract
            from qtrequestory.officina.compare.pipeline import compare_docs
            from tests.officina import pdfgen

            pdfgen.load_font()
            folder = tmp / "officina-viewer"
            folder.mkdir(exist_ok=True)

            def pages(changed: bool) -> str:
                out = []
                for n in range(12):
                    words = pdfgen.lorem(240, seed=n).split()
                    if changed and n == 0:
                        words[14] = "MOD_TEST_NUOVO"
                        words.insert(40, "parola aggiunta qui")
                        del words[80:84]
                    brk = "always" if n else "auto"
                    out.append(f"<h2 style='page-break-before: {brk}'>Sezione {n + 1}</h2>"
                               f"<p>{' '.join(words)}</p>")
                return "".join(out)

            left = pdfgen.html_pdf(folder / "target.pdf", pages(False))
            right = pdfgen.html_pdf(folder / "tobe.pdf", pages(True))
            lt, rt = extract(left), extract(right)
            officina_docs.update(left=(left, lt), right=(right, rt),
                                 diffs=compare_docs(lt, rt).diffs)
        return officina_docs

    def officina_viewer(zoom="fit_width"):
        def prepare():
            from PySide6.QtWidgets import QHBoxLayout, QWidget

            from qtrequestory.ui.pages.officina_judged import unjudged
            from qtrequestory.ui.pages.officina_viewer import DocView, SyncController

            docs = officina_pdfs()
            holder = QWidget()
            holder.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            row = QHBoxLayout(holder)
            views = []
            for side in ("left", "right"):
                view = DocView()
                path, text = docs[side]
                view.load(side, path, text.page_sizes)
                view.set_highlights([(unjudged(d), side) for d in docs["diffs"]])
                row.addWidget(view)
                views.append(view)
            holder._sync = SyncController(*views)
            holder.resize(width, height)
            holder.show()
            pump(200)
            views[0].set_zoom(zoom)
            if docs["diffs"]:
                holder._sync.focus_difference(docs["diffs"][0].id)
            pump(900)
            return holder
        return prepare

    scenes += [
        ("officina-visore", officina_viewer()),
        ("officina-visore-pagina", officina_viewer("fit_page")),
    ]

    # -- Officina tab (Task 7): list, board, case — synthetic keys and PDFs ------
    officina_state: dict[str, object] = {}

    sending_key = "MOD_TEST_RICHIESTA_B"

    def officina_settle() -> None:
        """A "-invio" scene leaves a slow generation running: let it end, and
        forget it (it is answered 502 on purpose, so no version is written and
        every mode shows the same documents)."""
        page = window.page("officina")
        end = time.monotonic() + 10
        while page.queue.is_busy() and time.monotonic() < end:
            pump(100)
        services.officina.delay_s = 0.0
        services.officina.set_response_for(sending_key, None)
        if officina_state:
            page.failures.pop((officina_state["ini"], officina_state["case"]), None)

    def officina_send_slowly(case_id: str) -> None:
        page = window.page("officina")
        services.officina.delay_s = 3.0
        services.officina.set_response_for(sending_key, b"<html>gateway</html>", 502)
        page.regenerate_tobe([case_id])

    def officina_setup():
        """Two initiatives; the first holds five cases in every state (a TO-BE
        with differences, one equal and reopened by a newer version after its
        acceptance, one accepted, one failed, one empty)."""
        officina_settle()
        if officina_state:
            return officina_state
        from tests.fakes.fake_core import canned_pdf

        docs = officina_pdfs()
        api = services.officina
        payloads = tmp / "officina-payloads"
        payloads.mkdir(exist_ok=True)
        ini = api.create_initiative("Iniziativa di esempio")
        api.create_initiative("Rinnovo moduli")
        keys = [("MOD_TEST_MANDATO_A", ""), ("MOD_TEST_RICHIESTA_B", "abilitato"),
                ("MOD_TEST_CARTA_C", ""), ("MOD_TEST_CARTA_D", ""), ("MOD_TEST_RICHIESTA_E", "")]
        for key, variant in keys:
            path = payloads / f"{key}.json"
            path.write_text('{"documents": [{"template": {"templateKey": "%s"}}]}' % key,
                            encoding="utf-8")
            api.case_from_file(ini, path, key, variant)
        ini = api.load(ini.id)
        cases = {c.key: c for c in ini.cases}
        left, right = docs["left"][0], docs["right"][0]
        for key in ("MOD_TEST_MANDATO_A", "MOD_TEST_RICHIESTA_B", "MOD_TEST_CARTA_C",
                    "MOD_TEST_CARTA_D"):
            api.set_target(cases[key], left)
        api.set_response(left.read_bytes())
        for key in ("MOD_TEST_MANDATO_A", "MOD_TEST_RICHIESTA_B", "MOD_TEST_CARTA_C",
                    "MOD_TEST_CARTA_D"):
            api.generate(ini, cases[key], "asis")
        api.generate(ini, cases["MOD_TEST_MANDATO_A"], "tobe")
        cases["MOD_TEST_MANDATO_A"].mark_accepted()
        api.save_case(cases["MOD_TEST_MANDATO_A"])
        api.generate(ini, cases["MOD_TEST_MANDATO_A"], "tobe")  # reopens it: da ricontrollare
        api.set_response(right.read_bytes())
        api.generate(ini, cases["MOD_TEST_RICHIESTA_B"], "tobe")
        api.generate(ini, cases["MOD_TEST_RICHIESTA_B"], "tobe")
        api.set_response(left.read_bytes())
        api.generate(ini, cases["MOD_TEST_CARTA_C"], "tobe")
        cases["MOD_TEST_CARTA_C"].mark_accepted()
        api.save_case(cases["MOD_TEST_CARTA_C"])
        api.set_response(canned_pdf("x"))
        api.set_response_for("MOD_TEST_CARTA_D", b"<html><body>gateway</body></html>", 502)
        officina_state.update(ini=ini.id, case=cases["MOD_TEST_RICHIESTA_B"].id,
                              failing=cases["MOD_TEST_CARTA_D"])
        officina_verdicts(api.load(ini.id), cases["MOD_TEST_RICHIESTA_B"].id)
        officina_html_case()  # U6: in the second initiative, the same in every mode
        return officina_state

    def officina_zone_boxes(docs):
        """U3: the zone boxes of page 1-2 of the synthetic PDFs, as the zone
        stage would give them (header, title, left shoulder, footer, page
        number), for the margin rails and the zones summary."""
        from qtrequestory.ui.contracts import ZoneBox

        out = []
        for page, (w, h) in enumerate(docs["left"][1].page_sizes[:2]):
            out += [ZoneBox(page, "header", 40, 20, w - 40, 60), ZoneBox(page, "titolo", 40, 64, w - 40, 84),
                    ZoneBox(page, "spalla_sx", 8, 120, 30, h - 160), ZoneBox(page, "footer", 40, h - 70, w - 40, h - 36),
                    ZoneBox(page, "numero_pagina", w - 90, h - 30, w - 40, h - 18)]
        return tuple(out)

    def officina_verdicts(ini, case_id: str) -> None:
        """Phase 2 (U1): script the fake's ``compare_case`` for case B so that
        its TO-BE v2 holds every verdict and state — regressione, da fare, non
        risolta (marked in v1, unchanged in v2), in corso, da verificare
        (marked in v2), fatta, tollerata (by profile and by hand), rumore,
        variabile, arredo (D1) — on word boxes of page 1 of the synthetic PDFs."""
        from tests.fakes.fake_core import fake_diff

        api = services.officina
        docs = officina_pdfs()
        lw = [w for w in docs["left"][1].words if w.page == 0]
        rw = [w for w in docs["right"][1].words if w.page == 0]

        def diff(op, klass, i, n=1, *, left=True, right=True, generated=None, part=False):
            lwords = tuple(lw[i:i + n]) if left else ()
            rwords = tuple(rw[i:i + n]) if right else ()
            target = " ".join(w.text for w in lwords)
            made = generated if generated is not None else " ".join(w.text for w in rwords)
            # R33: the target words around the change, as the engine gives them (<= 5 a side)
            fields = dict(left=lwords, right=rwords,
                          context_before=" ".join(w.text for w in lw[max(0, i - 5):i]),
                          context_after=" ".join(w.text for w in lw[i + n:i + n + 5]))
            if part:  # a few characters inside the word, not all of it
                fields.update(left_spans=((1, 3),), right_spans=((1, 3),))
            return dataclasses.replace(fake_diff(op, klass, target, made), **fields)

        def last_letter(i):  # U3: ONE letter changed, the list's hardest case
            word = lw[i].text
            made = word[:-1] + ("o" if word[-1] != "o" else "a")
            n = len(word)
            return dataclasses.replace(diff("cambiato", "testo", i, generated=made),
                                       left_spans=((n - 1, n),), right_spans=((n - 1, n),))

        def one_more(i, tail, base=None):  # one character added at the end of the word
            n = len(lw[i].text)
            return dataclasses.replace(base or diff("cambiato", "testo", i),
                                       right_text=lw[i].text + tail, left_spans=((n, n),),
                                       right_spans=((n, n + len(tail)),))

        def typed(d, tipo, zone="corpo", klass=None):  # U3: every type and zone, scripted
            return dataclasses.replace(d, tipo=tipo, zone=zone, **({"klass": klass} if klass else {}))

        da_fare = typed(last_letter(20), "parola")
        stuck = typed(one_more(34, "e"), "parola")
        before = diff("cambiato", "testo", 48, generated="prima")
        now = typed(one_more(48, "i", before), "parola")
        promised = typed(diff("cambiato", "testo", 62, generated=rw[62].text.upper()), "maiuscole")
        done = typed(diff("mancante", "testo", 76, 2, right=False), "frase")
        by_hand = typed(diff("cambiato", "testo", 104, generated=rw[104].text + "!"), "punteggiatura")
        link = fake_diff("cambiato", "link", "Scopri le condizioni", "Scopri le condizioni",
                         before="Per i dettagli", after="del servizio.", tipo="link",
                         detail="href: https://example.invalid/condizioni → "
                                "https://example.invalid/condizioni-2025")
        # U3: the zones (as the engine's zone stage names them) and the other types
        header = typed(diff("cambiato", "zona", 0, 2, generated="Sezione iniziale"), "zona", "header")
        shoulder = typed(diff("cambiato", "zona", 146, generated="Ed. 01/2026"), "zona", "spalla_sx")
        footer = typed(diff("cambiato", "zona", 180, 2, generated="Acme-Servizi S.p.A."), "zona", "footer")
        number = typed(diff("cambiato", "testo", 160, generated="11,50"), "numeri")
        spaces = typed(diff("cambiato", "testo", 166, generated=f"{rw[166].text}  {rw[167].text}"), "spazi")
        moved = typed(diff("spostato", "testo", 172), "spostamento")
        section = typed(diff("sezione_in_piu", "testo", 196, 6, left=False), "sezione")
        page_no = typed(diff("cambiato", "arredo", 210, generated="2 di 12"), "numeri", "numero_pagina")
        tobe = [
            typed(diff("in_piu", "testo", 6, 2, left=False), "frase"),  # regressione
            da_fare, stuck, now, promised,
            typed(diff("cambiato", "stile", 90), "altro"),               # tollerata (profilo)
            by_hand,                                                  # tollerata a mano
            typed(diff("cambiato", "rumore", 118), "numeri"),
            typed(diff("cambiato", "variabile", 132, 2), "numeri"),
            link,                                                     # solo nell'elenco
            header, shoulder, footer, number, spaces, moved, section, page_no,
        ]
        # U2: a v1-only difference, so that a mark made in v1 is "risolta" in v2
        extra = fake_diff("cambiato", "testo", "Titolo di esempio", "Titolo", tipo="parola")
        zones = officina_zone_boxes(docs)
        api.set_canned(case_id, 0, [da_fare, stuck, before, promised, done, by_hand, link, header, shoulder,
                                    footer, number, spaces, moved, section], left_zones=zones, right_zones=zones)
        api.set_canned(case_id, 1, [*tobe, extra], left_zones=zones, right_zones=zones)
        api.set_canned(case_id, 2, tobe, left_zones=zones, right_zones=zones)
        officina_state.update(stuck=stuck, extra=extra, one_letter=da_fare, in_corso=now, link=link,
                              filters=dict(footer=footer, header=header, shoulder=shoulder, page_no=page_no,
                                           caps=promised, punct=by_hand, variable=tobe[8], noise=tobe[7]))

    def officina_list() -> None:
        officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.show_list()
        pump(300)

    def officina_deletions(count: int, expanded: bool = False):
        """D6: 1, 2 or 3 initiatives deleted a moment apart, the bar counting
        down on a frozen clock (the loop undoes them after the shot: a scene
        never deletes anything)."""
        def prepare() -> None:
            officina_setup()
            api = services.officina
            names = ["Banco prove", "Campagna estate", "Moduli 2025"][:count]
            for name in names:
                try:
                    api.load(name)
                except FileNotFoundError:
                    api.create_initiative(name)
            page = window.page("officina")
            window.show_page("officina")
            page.ini = None
            page.show_list()
            now = [time.monotonic() * 1000]
            window.deletions.clock = lambda: now[0]
            for name in names:
                page.delete_initiative(name)
                now[0] += 800
            now[0] += 900
            window.deletions.tick()
            window.deletion_bar.set_expanded(expanded)
            pump(200)
        return prepare

    def officina_board() -> None:
        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        page.regenerate_tobe([state["failing"].id])  # fails: 502, shown on its row
        pump(1500)
        page.board.select_cases([state["case"]])
        pump(300)

    def officina_case() -> None:
        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        page.open_case(state["case"])
        pump(2500)
        view = page.case_view
        if view.diffs.list.count():
            view.diffs.list.setCurrentRow(0)
        pump(900)

    def officina_case_verdicts() -> None:
        """Phase 2 (U1): case B's v2 judged by the scripted fake — every verdict
        and state drawn by verdict, the fatte shown, the regression focused."""
        officina_case()
        officina_measure("case")
        view = window.page("officina").case_view
        for side in (view.left, view.right):
            side.view.set_show_done(True)
        pump(600)

    class _Restoring(_Kept):
        """The window, then ``undo`` once it has been grabbed."""

        def __init__(self, widget, undo) -> None:
            super().__init__(widget)
            self._undo = undo

        def close(self) -> None:
            self._undo()

    def officina_measure(what: str) -> None:
        """Where the documents start (U2: <= 80 px under the case view's top)."""
        from PySide6.QtCore import QPoint

        view = window.page("officina").case_view
        top = view.left.view.mapTo(window, QPoint(0, 0)).y()
        inside = view.left.view.mapTo(view, QPoint(0, 0)).y()
        print(f"{what}: documents start at y={top} of {window.height()} "
              f"({100 * top / window.height():.1f}%), {inside} px under the case view's top")

    def officina_open_case_version(number: int):
        from qtrequestory.ui.pages.officina_docside import version_key

        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        case = page._case(state["case"])
        page.open_case(case.id, version_key(case.tobe_versions()[number - 1]))
        pump(2500)
        return page, case

    def officina_case_verification():
        """Phase 2 (U2): two marks made in v1, v2 opened: one resolved (gone),
        one "non risolta" (still identical) — the outcome banner; the v2 mark
        still waits (the blue "da verificare" banner)."""
        from qtrequestory.ui.contracts import Judged

        state = officina_setup()
        page = window.page("officina")
        page.open_initiative(state["ini"])
        case = page._case(state["case"])
        api = services.officina
        api.mark_done(case, Judged(state["stuck"], "da_fare"), 1)
        api.mark_done(case, Judged(state["extra"], "regressione"), 1)
        officina_open_case_version(2)
        officina_measure("bar + marks strip + outcome strip")
        return None

    def officina_case_two_way():
        """Phase 2 (U2): case B judged without an AS-IS comparison (its canned
        entry 0 put aside for this picture): the two-way warning."""
        state = officina_setup()
        canned = services.officina.canned[state["case"]]
        asis = canned.pop(0)
        officina_open_case_version(2)
        officina_measure("two-way (bar + marks strip)")

        def undo() -> None:
            canned[0] = asis

        return _Restoring(window, undo)

    def officina_case_no_text():
        """R49 (final review): case B's v2 came back without text (the canned
        comparison says so; the viewer still draws the fake's PDF) — no
        verdict, no progress bar, the note instead of the list."""
        from tests.fakes.fake_core import fake_comparison

        state = officina_setup()
        canned = services.officina.canned[state["case"]]
        v2 = canned[2]
        canned[2] = fake_comparison([], right_has_text=False, note="il TO-BE non ha testo estraibile")
        officina_open_case_version(2)

        def undo() -> None:
            canned[2] = v2

        return _Restoring(window, undo)

    class _WithMenu:
        """The window with a popup menu painted where it opened (a popup is a
        window of its own: ``window.grab()`` would miss it)."""

        def __init__(self, menu) -> None:
            self.menu = menu

        def grab(self):
            from PySide6.QtGui import QPainter

            shot = window.grab()
            painter = QPainter(shot)
            painter.drawPixmap(self.menu.pos() - window.mapToGlobal(window.rect().topLeft()),
                               self.menu.grab())
            painter.end()
            return shot

        def close(self) -> None:
            self.menu.hide()

        def deleteLater(self) -> None:
            pass

    pill_state: dict[str, object] = {}

    def officina_pills_setup():
        """U5: an initiative whose cases show one board pill each — every worst
        state, a summary of an older TO-BE ("da riconfrontare"), nothing that
        counts, and no TO-BE — from summaries saved in ``riepilogo`` (the board
        compares nothing)."""
        if pill_state:
            return pill_state
        from datetime import datetime

        from qtrequestory.ui.contracts import CaseSummary

        officina_setup()
        api = services.officina
        docs = officina_pdfs()
        payloads = tmp / "officina-pill-payloads"
        payloads.mkdir(exist_ok=True)
        ini = api.create_initiative("Pillole della bacheca")
        rows = [  # key, TO-BE versions, summary counts (version, avanzamento last)
            ("MOD_TEST_PILL_REGRESSIONE", 1, dict(regressioni=1, non_risolte=1, da_fare=3,
                                                  in_corso=2, da_verificare=1, fatte=2,
                                                  tollerate=2, variabili=3, rumore=1), 1, 0.25),
            ("MOD_TEST_PILL_NON_RISOLTA", 1, dict(da_fare=3, non_risolte=1, fatte=2), 1, 0.4),
            ("MOD_TEST_PILL_DA_FARE", 1, dict(da_fare=2, fatte=4, variabili=8), 1, 0.67),
            ("MOD_TEST_PILL_IN_CORSO", 1, dict(in_corso=2, fatte=5), 1, 0.71),
            ("MOD_TEST_PILL_DA_VERIFICARE", 1, dict(da_fare=2, da_verificare=2, fatte=4), 1, 0.67),
            ("MOD_TEST_PILL_FATTA", 1, dict(fatte=6, tollerate=2), 1, 1.0),
            ("MOD_TEST_PILL_VECCHIO", 2, dict(regressioni=1, da_fare=1, fatte=2), 1, 0.5),
            ("MOD_TEST_PILL_NIENTE", 1, dict(tollerate=2, rumore=1), 1, 1.0),
            ("MOD_TEST_PILL_SENZA_TOBE", 0, None, 0, 0.0),
        ]
        for key, *_rest in rows:
            path = payloads / f"{key}.json"
            path.write_text('{"documents": [{"template": {"templateKey": "%s"}}]}' % key,
                            encoding="utf-8")
            api.case_from_file(ini, path, key)
        ini = api.load(ini.id)
        cases = {c.key: c for c in ini.cases}
        api.set_response(docs["right"][0].read_bytes())
        zero = dict(fatte=0, da_fare=0, in_corso=0, regressioni=0, da_verificare=0,
                    non_risolte=0, tollerate=0, variabili=0, rumore=0)
        for key, versions, counts, version, progress in rows:
            case = cases[key]
            api.set_target(case, docs["left"][0])
            for _ in range(versions):
                api.generate(ini, case, "tobe")
            if counts is not None:
                # now and two-way (no AS-IS here): else the board says "da riconfrontare" (I1)
                summary = CaseSummary(version=version, **{**zero, **counts}, avanzamento=progress,
                                      two_way=True, when=datetime.now().isoformat(timespec="seconds"))
                api._commit_review(None, case, dataclasses.replace(case.review, summary=summary))
        pill_state.update(ini=ini.id, tip=cases["MOD_TEST_PILL_REGRESSIONE"].id)
        return pill_state

    class _WithTip(_WithMenu):
        """The window with the tooltip painted where it shows (its own window)."""

        def close(self) -> None:
            from PySide6.QtWidgets import QToolTip

            QToolTip.hideText()

    def officina_board_pills():
        """U5: the board of "Pillole della bacheca", the tooltip of the first
        pill (the full breakdown) showing."""
        from PySide6.QtWidgets import QApplication, QLabel, QToolTip

        from qtrequestory.ui.pages.officina_board import COL_PILL

        state = officina_pills_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        pump(600)
        board = page.board
        row = next(r for r, c in enumerate(board._cases()) if c.id == state["tip"])
        label = board.table.cellWidget(row, COL_PILL).findChild(QLabel)
        at = label.mapToGlobal(label.rect().topRight())  # beside it: the rows below stay visible
        at.setX(at.x() + 24)
        QToolTip.showText(at, label.toolTip(), label)
        pump(400)
        tip = next((w for w in QApplication.topLevelWidgets()
                    if w.metaObject().className() == "QTipLabel" and w.isVisible()), None)
        return _WithTip(tip) if tip is not None else None

    minimap_state: dict[str, object] = {}

    def officina_minimap_setup():
        """U5: a case of its own ("Minimappa") whose v1 has differences on
        pages 1 to 12 of the synthetic 12-page PDFs, one of every verdict, so
        the minimaps spread over the whole document height."""
        if minimap_state:
            return minimap_state
        from tests.fakes.fake_core import fake_diff

        officina_setup()
        api = services.officina
        docs = officina_pdfs()
        lw, rw = docs["left"][1].words, docs["right"][1].words
        path = tmp / "officina-minimap.json"
        path.write_text('{"documents": [{"template": {"templateKey": "MOD_TEST_MINIMAPPA"}}]}',
                        encoding="utf-8")
        ini = api.create_initiative("Minimappa")
        api.case_from_file(ini, path, "MOD_TEST_MINIMAPPA")
        ini = api.load(ini.id)
        case = ini.cases[0]
        api.set_target(case, docs["left"][0])
        api.set_response(docs["right"][0].read_bytes())
        api.generate(ini, case, "asis")
        api.generate(ini, case, "tobe")

        def on(page, i, klass="testo", generated=None):
            lwords = tuple(w for w in lw if w.page == page)[i:i + 2]
            rwords = tuple(w for w in rw if w.page == page)[i:i + 2]
            target = " ".join(w.text for w in lwords)
            return dataclasses.replace(
                fake_diff("cambiato", klass, target, generated or target.upper(),
                          context=f"p{page}"), left=lwords, right=rwords)

        regression, todo, moving, marked = on(1, 60), on(3, 120), on(5, 30), on(8, 90)
        done, tolerated, late = on(10, 150), on(6, 200, "stile"), on(11, 40)
        asis = [todo, dataclasses.replace(moving, right_text="prima"), marked, done, late]
        api.set_canned(case.id, 0, asis)
        api.set_canned(case.id, 1, [regression, todo, moving, marked, tolerated, late])
        first = api.compare_case(ini, case, case.tobe_versions()[0])
        api.mark_done(case, next(j for j in first.judged if j.diff.anchor == marked.anchor), 1)
        minimap_state.update(ini=ini.id, case=case.id)
        return minimap_state

    def officina_case_minimap():
        """U5: the "Minimappa" case, v1: the minimap beside each document's
        scroll bar, the fatte shown (their segment appears on the target side)."""
        state = officina_minimap_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        page.open_case(state["case"], "v1")
        pump(2500)
        view = page.case_view
        for side in (view.left, view.right):
            side.view.set_show_done(True)
        pump(900)

    viewer_state: dict[str, object] = {}

    def officina_viewer_u1_setup():
        """Phase 2.5 (U1): a case of its own ("Visore") on the synthetic
        12-page PDFs: a difference over three separate lines of page 2 (one
        ring per box), a «mancante» on page 3 (no words on the TO-BE side) and
        a plain one on page 1."""
        if viewer_state:
            return viewer_state
        from tests.fakes.fake_core import fake_diff

        officina_setup()
        api = services.officina
        docs = officina_pdfs()
        lw, rw = docs["left"][1].words, docs["right"][1].words
        path = tmp / "officina-visore.json"
        path.write_text('{"documents": [{"template": {"templateKey": "MOD_TEST_VISORE"}}]}',
                        encoding="utf-8")
        ini = api.create_initiative("Visore")
        api.case_from_file(ini, path, "MOD_TEST_VISORE")
        ini = api.load(ini.id)
        case = ini.cases[0]
        api.set_target(case, docs["left"][0])
        api.set_response(docs["right"][0].read_bytes())
        api.generate(ini, case, "tobe")

        def pick(words, page, *indexes):
            on = [w for w in words if w.page == page]
            return tuple(on[i] for i in indexes)

        spread = pick(lw, 1, 30, 31, 32, 95, 96, 170)
        section = dataclasses.replace(
            fake_diff("cambiato", "testo", " ".join(w.text for w in spread), "altro testo",
                      context="sezione"), left=spread, right=pick(rw, 1, 30, 31))
        gone = pick(lw, 2, 150, 151, 152)
        missing = dataclasses.replace(
            fake_diff("mancante", "testo", " ".join(w.text for w in gone), "", context="mancante"),
            left=gone, right=())
        plain = pick(lw, 0, 20, 21)
        simple = dataclasses.replace(
            fake_diff("cambiato", "testo", " ".join(w.text for w in plain), "MOD_TEST",
                      context="semplice"), left=plain, right=pick(rw, 0, 20, 21))
        api.set_canned(case.id, 1, [simple, section, missing])
        viewer_state.update(ini=ini.id, case=case.id, section=section, missing=missing)
        return viewer_state

    def officina_viewer_u1(key: str, zoom: float | None = None, shift: float = 0.0):
        def prepare():
            state = officina_viewer_u1_setup()
            page = window.page("officina")
            window.show_page("officina")
            page.open_initiative(state["ini"])
            page.open_case(state["case"], "v1")
            pump(2500)
            view = page.case_view
            if zoom is not None:
                view.left.view.set_zoom(zoom)
                pump(300)
            anchor = state[key].anchor
            target = next(j for j in view.docs.judged.judged if j.diff.anchor == anchor)
            for other in view.docs.judged.judged:  # several selections first: one ring stays
                view.diffs.select(other.diff.id)
                view.sync.focus_difference(other.diff.id)
                pump(150)
            view.diffs.select(target.diff.id)
            view.sync.focus_difference(target.diff.id)
            pump(300)
            if shift:
                bar = view.left.view.horizontalScrollBar()
                bar.setValue(round(bar.maximum() * shift))
            pump(900)
            doc_l, doc_r = view.left.view, view.right.view
            print(f"u1 {key}: left v{doc_l.verticalScrollBar().value()} h{doc_l.horizontalScrollBar().value()}"
                  f" | right v{doc_r.verticalScrollBar().value()} h{doc_r.horizontalScrollBar().value()}"
                  f" | rings {[i for i in doc_l.scene().items() if i.zValue() == 3].__len__()}")
        return prepare

    def officina_case_menu():
        """Phase 2.5 (U2): the case bar's "⋯" menu open on case B (every
        command that left the bar: AS-IS, target, payload, call, profile,
        noise, tolerances, marks, acceptance)."""
        page, _case = officina_open_case_version(2)
        button = page.case_view.more_button
        menu = button.menu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        corner = button.mapToGlobal(button.rect().bottomRight())
        corner.setX(corner.x() - menu.sizeHint().width())  # inside the window's right edge
        menu.popup(corner)
        pump(300)
        return _WithMenu(menu)

    def officina_case_same_as_asis():
        """Phase 2.5 (U2): case B's v1 given the AS-IS's differences (the
        canned v1 put aside for this picture): the "= AS-IS" chip."""
        state = officina_setup()
        canned = services.officina.canned[state["case"]]
        v1 = canned[1]
        canned[1] = canned[0]
        officina_open_case_version(1)
        officina_measure("= AS-IS")

        def undo() -> None:
            canned[1] = v1

        return _Restoring(window, undo)

    def officina_case_asis():
        """Phase 2.5 (U2): case B's AS-IS, drawn in the same visual language
        (its differences from the target as "da fare": the whole work)."""
        state = officina_setup()
        api = services.officina
        api.scripted_comparison = api.canned[state["case"]][0]  # the fake PDFs of B read alike
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        page.open_case(state["case"], "asis")
        pump(2500)
        officina_measure("AS-IS")

        def undo() -> None:
            api.scripted_comparison = None

        return _Restoring(window, undo)

    def officina_panel(tab: str = "guardare", *, types=(), fold=(), collapsed: bool = False,
                       legend: bool = False):
        """Phase 2.5 (U3): case B's v2 with the side panel on ``tab``, the type
        chips ``types`` on, the groups ``fold`` folded, collapsed to the rail,
        or with the legend open (the zone rails on every page margin)."""
        def prepare():
            officina_open_case_version(2)
            view = window.page("officina").case_view
            diffs = view.diffs
            diffs.set_collapsed(collapsed)
            diffs.set_tab(tab)
            diffs.set_types(set(types))
            for key in fold:
                diffs.toggle_group(key)
            if diffs.row_ids():
                diffs.select(diffs.row_ids()[0])
                view.sync.focus_difference(diffs.row_ids()[0])
            pump(900)

            def undo() -> None:
                diffs.set_types(set())
                diffs._folded.clear()
                diffs.set_collapsed(False)

            if legend:
                diffs.footer.legend_button.click()
                pump(300)
                shot = _WithMenu(diffs.popover)
                shot.close = lambda: (diffs.popover.hide(), undo())
                return shot
            return _Restoring(window, undo)
        return prepare

    def officina_list_select(tab: str, key: str | None = None, *, verification: bool = False):
        """Phase 2 (U3): case B's v2, the list on ``tab`` with the row of the
        scripted diff ``officina_state[key]`` selected (by anchor)."""
        def prepare():
            if verification:
                officina_case_verification()
            else:
                officina_open_case_version(2)
            view = window.page("officina").case_view
            view.diffs.set_tab(tab)
            if key is not None:
                anchor = officina_state[key].anchor
                target = next(j for j in view.docs.judged.judged if j.diff.anchor == anchor)
                view.diffs.select(target.diff.id)
                view.sync.focus_difference(target.diff.id)
            elif view.diffs.row_ids():
                view.diffs.select(view.diffs.row_ids()[0])
            view.diffs.list.setFocus()
            pump(900)
            return None
        return prepare

    def _open_diff_near_right_edge():
        """U4: case B's v2 zoomed in, the counting difference whose box ends
        furthest right scrolled against the right edge of the TO-BE viewport,
        then clicked (a real click): selected, with its mini-bar."""
        from PySide6.QtTest import QTest

        from qtrequestory.ui.pages.officina_rows import OPEN_STATES
        from qtrequestory.ui.pages.officina_verdict_style import state_of

        page, _case = officina_open_case_version(2)
        view = page.case_view
        doc = view.right.view
        shown = [j for j in view.docs.judged.judged if doc.highlight_items(j.diff.id)]
        candidates = ([j for j in shown if state_of(j) == "da_fare"]
                      or [j for j in shown if state_of(j) in OPEN_STATES])
        j = max(candidates, key=lambda x: doc.difference_rect(x.diff.id).right())
        doc.set_zoom(2.0)
        pump(300)
        rect = doc.difference_rect(j.diff.id)
        doc.centerOn(rect.center())
        pump(100)
        hbar = doc.horizontalScrollBar()
        right = doc.mapFromScene(rect.topRight()).x()
        hbar.setValue(hbar.value() + right - (doc.viewport().width() - 10))
        pump(300)
        item = doc.highlight_items(j.diff.id)[0]
        QTest.mouseClick(doc.viewport(), Qt.MouseButton.LeftButton,
                         pos=doc.mapFromScene(item.rect().center()))
        pump(600)
        bar = view.bars["right"]
        print(f"mini-bar: diff {j.diff.id} ({state_of(j)}) highlight "
              f"{doc.mapFromScene(rect).boundingRect()} bar {bar.geometry()} "
              f"viewport {doc.viewport().geometry()} "
              f"inside={doc.viewport().geometry().contains(bar.geometry())} visible={bar.isVisible()}")
        return page, j

    def officina_action_bar():
        _open_diff_near_right_edge()
        return None

    def officina_action_menu():
        """U4: the right-click menu of a "da fare" difference (grabbed where it opened)."""
        page, j = _open_diff_near_right_edge()
        view = page.case_view
        doc = view.right.view
        view.hide_bars()
        at = doc.viewport().mapToGlobal(doc.mapFromScene(doc.difference_rect(j.diff.id).center()))
        view.open_review_menu(j.diff.id, at)
        menu = view.menu
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        if menu.pos().x() + menu.width() > window.mapToGlobal(window.rect().topRight()).x():
            menu.move(at.x() - menu.width(), at.y())  # a real screen flips it the same way
        pump(300)
        return _WithMenu(menu)

    def officina_action_toast():
        """U4: the toast after "✓ Fatta" in the mini-bar; the mark is undone
        after the grab (Ctrl+Z path), so the next scenes see case B unchanged."""
        page, _j = _open_diff_near_right_edge()
        bar = page.case_view.bars["right"]
        bar.done_button.click()
        end = time.monotonic() + 10
        while (page.case_view.acting or not window.toast.isVisible()) and time.monotonic() < end:
            pump(100)
        pump(300)

        def undo() -> None:
            page.undo_review()
            end = time.monotonic() + 10
            while page.case_view.acting and time.monotonic() < end:
                pump(100)
            window.toast.hide()

        return _Restoring(window, undo)

    def officina_action_note():
        """U4: "Tollera…": the small note dialog, grabbed on its own."""
        from qtrequestory.ui.pages.officina_actions_bar import TolerateDialog

        officina_setup()
        dialog = TolerateDialog(officina_state["one_letter"].left_text, window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.edit.setText("Il cliente accetta la nuova dicitura")
        dialog.show()
        pump(300)
        return dialog

    def officina_board_sending() -> None:
        """The board while a case is on its way: "Generazione su svil…"."""
        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        officina_send_slowly(state["case"])
        pump(600)

    def officina_case_sending() -> None:
        """The workbench while its case is on its way: the busy label names
        the generator (the header always does)."""
        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        page.open_case(state["case"])
        pump(2500)
        officina_send_slowly(state["case"])
        pump(400)

    #: A synthetic generator the sidecar "carries" in the 1.3.2 setup scenes.
    from qtrequestory.ui.contracts import GeneratorEndpoint as _Gen
    sidecar_gen = _Gen("svil", "https://example.invalid/svil/rest/api/submit-job/documentGenerator")

    def officina_setup_card(*, keep_root: bool, sidecar: bool = True):
        """1.3.2: "Configura l'Officina" — instead of the initiatives (no
        folder) or over them (a folder, no generator), prefilled from the
        sidecar's generators; ``sidecar=False``: the normal case since U4, an
        empty row whose URL cell shows the shape of an address."""
        def prepare() -> None:
            cfg = services.config.config
            saved = cfg.officina
            officina = (dataclasses.replace(saved, generators=[]) if keep_root
                        else dataclasses.replace(saved, root=None, generators=[]))
            services.config.config = dataclasses.replace(cfg, officina=officina)
            services.config.sidecar_gens = [sidecar_gen] if sidecar else []
            page = window.page("officina")
            window.show_page("officina")
            page.ini, page.case_id = None, None
            page.refresh()
            pump(300)
            services.config.config = dataclasses.replace(services.config.config, officina=saved)
            services.config.sidecar_gens = []
        return prepare

    def wizard_officina(sidecar: bool = True):
        """1.3.2: the wizard's fourth step, prefilled from the sidecar (or, the
        normal case since U4, without one: an empty row), grabbed on its own."""
        from PySide6.QtWidgets import QWizard

        from qtrequestory.ui.wizard import FirstRunWizard

        from qtrequestory.ui.contracts import OfficinaSettings

        saved = services.config.config
        services.config.config = dataclasses.replace(saved, officina=OfficinaSettings())
        services.config.sidecar_gens = [sidecar_gen] if sidecar else []
        wizard = FirstRunWizard(services, runner, window)
        wizard.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        wizard.resize(760, 600)
        wizard.show()
        wizard.folder_page.set_path(services.config.config.mirror_root)
        for _ in range(3):
            wizard.next()
            pump(200)
        if sidecar:
            wizard.officina_page.form.folder_edit.setText(str(tmp / "Officina"))
        services.config.config = saved
        services.config.sidecar_gens = []
        assert wizard.button(QWizard.WizardButton.CustomButton1).isVisible()
        pump(300)
        return wizard

    def officina_editor():
        """"Payload e header…" of the case, on its second tab, grabbed on its own."""
        from qtrequestory.ui.pages.officina_editor import PayloadHeaderDialog

        state = officina_setup()
        page = window.page("officina")
        page.open_initiative(state["ini"])
        case = page._case(state["case"])
        case.headers = {"X-Flag": "active", "current_timestamp": "1767225600000"}
        dialog = PayloadHeaderDialog(services, case, window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.tabs.setCurrentIndex(1)
        dialog.show()
        pump(300)
        return dialog

    def officina_add_dialog():
        from qtrequestory.ui.pages.officina_add import AddCaseDialog

        officina_setup()
        dialog = AddCaseDialog([("Iniziativa di esempio", "Iniziativa di esempio"),
                                ("Rinnovo moduli", "Rinnovo moduli")],
                               current="Iniziativa di esempio", key="MOD_TEST_RICHIESTA_B",
                               parent=window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.variant.setText("abilitato")
        dialog.show()
        pump(300)
        return dialog

    def officina_editor_payload():
        """A1: "Payload e header…" on its payload tab: the "Cambia chiamata…" link."""
        dialog = officina_editor()
        dialog.tabs.setCurrentIndex(0)
        pump(300)
        return dialog

    def officina_pick_dialog():
        """A1: "Aggiungi chiamata…" with the calls of one FDI, two chosen."""
        from qtrequestory.ui.pages.officina_pick_call import PickCallDialog

        state = officina_setup()
        dialog = PickCallDialog(services, runner, services.officina.initiatives(), current=state["ini"],
                                parent=window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.query.setText(services.index.hits[0].fdi[:8])
        dialog.variant.setText("abilitato")
        dialog.show()
        dialog.search_now()
        pump(900)
        dialog.table.selectRow(0)
        dialog.table.selectionModel().select(
            dialog.table.model().index(2, 0),
            dialog.table.selectionModel().SelectionFlag.Select | dialog.table.selectionModel().SelectionFlag.Rows)
        pump(300)
        return dialog

    def officina_pick_question():
        """A1: the replace-or-new question, opened from the case (replace is the default)."""
        from qtrequestory.ui.pages.officina_pick_question import ReplaceOrNewDialog

        state = officina_setup()
        ini = services.officina.load(state["ini"])
        case = next(c for c in ini.cases if c.id == state["case"])
        hit = dataclasses.replace(services.index.hits[0], template_key=case.key)
        dialog = ReplaceOrNewDialog(hit, [case], initiative=ini.name, default_replace=case.id,
                                    parent=window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.show()
        pump(300)
        return dialog

    def officina_call_strip():
        """A1: case C after "Cambia chiamata…": its AS-IS predates the call (the
        strip); caso.json and the payload are put back once grabbed."""
        from datetime import datetime

        from qtrequestory.officina.model_call import replace_payload

        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        case = next(c for c in page.ini.cases if c.key == "MOD_TEST_CARTA_C")
        kept = {name: (case.folder / name).read_bytes() for name in ("caso.json", "payload.json")}
        before = set(case.folder.iterdir())
        replace_payload(case, {"documents": [{"template": {"templateKey": case.key}}]},
                        services.index.hits[0].fdi, datetime.now())
        page.refresh()
        page.open_case(case.id)
        pump(2500)

        def undo() -> None:
            for path in set(case.folder.iterdir()) - before:
                if path.is_file() and path.name.startswith("payload."):  # the backups it made
                    path.unlink()
            for name, data in kept.items():
                (case.folder / name).write_bytes(data)
            case.source_fdi = None

        return _Restoring(window, undo)

    delivery_dest = tmp / "OneDrive - Esempio" / "Consegne tester"

    def officina_delivery_dialog():
        """"Consegna…": the accepted case, plus a non-accepted one (the warning)
        and one without TO-BE (a missing slot in the preview), zip on."""
        from qtrequestory.ui.pages.officina_delivery import DeliveryDialog

        state = officina_setup()
        ini = services.officina.load(state["ini"])
        dialog = DeliveryDialog(services, runner, ini, window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        for case in ini.cases:
            if case.key in ("MOD_TEST_RICHIESTA_B", "MOD_TEST_CARTA_D"):
                dialog.set_checked(case.id, True)
        dialog.set_destination(delivery_dest)
        dialog.zip_box.setChecked(True)
        dialog.show()
        pump(300)
        return dialog

    def officina_delivery_summary():
        """The summary after a delivery that found one file already there
        (answered "Salta" for all) and skipped the missing TO-BE."""
        from qtrequestory.ui.pages import officina_dialogs

        import shutil

        shutil.rmtree(delivery_dest, ignore_errors=True)  # the same picture in every mode
        dialog = officina_delivery_dialog()
        existing = delivery_dest / "Iniziativa di esempio" / "MOD_TEST_CARTA_C"
        existing.mkdir(parents=True, exist_ok=True)
        (existing / "MOD_TEST_CARTA_C_ASIS.pdf").write_bytes(b"%PDF-1.4 vecchio")
        saved = officina_dialogs.ask_conflict
        officina_dialogs.ask_conflict = lambda *_a: ("skip", True)
        try:
            dialog.start()
            end = time.monotonic() + 10
            while not dialog.showing_summary() and time.monotonic() < end:
                pump(100)
        finally:
            officina_dialogs.ask_conflict = saved
        pump(300)
        return dialog

    # -- U6: the noise rules dialog and the DOM tab --------------------------------

    email_pretty = "\n".join([
        "<!DOCTYPE html>", "<html>", "  <head>", "    <title>", "      Comunicazione Acme-Servizi",
        "    </title>", "  </head>", "  <body>", "    <table>", "      <tr>", "        <td>",
        "          <img src=\"https://example.invalid/img/logo.png\" alt=\"Acme-Servizi\">",
        "        </td>", "      </tr>", "      <tr>", "        <td>", "          Gentile cliente,",
        "        </td>", "      </tr>", "    </table>", "    <p>",
        "      la sua richiesta n. PR-204518 del 12/03/2026 è stata presa in carico.", "    </p>",
        "    <p>", "      Per i dettagli",
        "      <a href=\"https://example.invalid/condizioni?utm_source=mail&amp;utm_campaign=x\">",
        "        Scopri le", "        <b>", "          condizioni", "        </b>", "      </a>",
        "      del servizio.", "    </p>", "    <ul>", "      <li>", "        Attivazione entro 5 giorni",
        "      </li>", "      <li>", "        Assistenza dedicata", "      </li>", "    </ul>", "    <p>",
        "      Cordiali saluti,", "      <br>", "      Acme-Servizi", "    </p>", "  </body>", "</html>"])
    email_generated = (email_pretty
                       .replace("condizioni?utm_source=mail&amp;utm_campaign=x", "condizioni-2026")
                       .replace("Attivazione entro 5 giorni", "Attivazione entro 7 giorni")
                       .replace("PR-204518 del 12/03/2026", "PR-377120 del 25/09/2026"))

    def officina_html_case() -> None:
        """U6: an HTML case (target and TO-BE e-mails) in the second
        initiative, the DOM sources scripted as the engine prints them."""
        api = services.officina
        ini = api.load("Rinnovo moduli")
        payload = tmp / "officina-payloads" / "MOD_TEST_EMAIL_F.json"
        payload.write_text('{"documents": [{"template": {"templateKey": "MOD_TEST_EMAIL_F"}}]}',
                           encoding="utf-8")
        api.case_from_file(ini, payload, "MOD_TEST_EMAIL_F", "")
        ini = api.load(ini.id)
        case = ini.cases[0]
        target = tmp / "officina-payloads" / "Email del cliente.html"
        body = "".join(f"<p>{line.strip()}</p>" for line in email_pretty.splitlines()
                       if line.strip() and not line.strip().startswith("<"))
        body += "<p>Messaggio generato automaticamente, non rispondere.</p>" * 8  # not "too short"
        target.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
        api.set_target(case, target)
        api.set_response(f"<html><body>{body}</body></html>".encode())
        api.generate(ini, case, "tobe")
        from tests.fakes.fake_core import canned_pdf, fake_diff

        api.set_response(canned_pdf("x"))

        link = fake_diff("cambiato", "link", "https://example.invalid/condizioni",
                         "https://example.invalid/condizioni-2026", before="Per i dettagli",
                         after="del servizio.",
                         detail="href: https://example.invalid/condizioni → "
                                "https://example.invalid/condizioni-2026")
        text = fake_diff("cambiato", "testo", "5", "7", before="Attivazione entro", after="giorni")
        noise = fake_diff("cambiato", "rumore", "PR-204518", "PR-377120", before="richiesta n.",
                          after="del")
        api.set_canned(case.id, 1, [noise, link, text])
        api.set_dom_view(case.id, (email_pretty, email_generated))
        api.set_noise_text(case.id, email_pretty + "\n" + email_generated)
        officina_state.update(html_ini=ini.id, html_case=case.id, html_link=link)

    def officina_noise_dialog():
        """U6: "Regole di rumore…" of the board (the initiative's own rules,
        counted on the HTML case): two rules — one counted, one whose regex
        does not compile. No presets, no switches (F14: the Filtri's)."""
        from qtrequestory.ui import strings as s
        from qtrequestory.ui.contracts import NoiseRule
        from qtrequestory.ui.pages.officina_format import case_title
        from qtrequestory.ui.pages.officina_noise import NoiseDialog

        state = officina_setup()
        page = window.page("officina")
        page.open_initiative(state["html_ini"])
        case = page._case(state["html_case"])
        rules = [NoiseRule("Codice pratica", r"PR-\d{6}"), NoiseRule("Saluti", r"(Cordiali saluti")]
        dialog = NoiseDialog(s.RUMORE_TITLE_INITIATIVE.format(name=page.ini.name), rules,
                             own_title=s.RUMORE_OWN_INITIATIVE, presets=services.officina.noise_presets(),
                             counter=page._counter(case),
                             counts_note=s.RUMORE_COUNTS_ON.format(case=case_title(case)), parent=window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.resize(820, 600)
        dialog.show()
        end = time.monotonic() + 10
        while dialog.is_counting() and time.monotonic() < end:
            pump(100)
        pump(300)
        print("noise counts:", [dialog.hits_shown(r) for r in range(dialog.own.rowCount())])
        return dialog

    class _WithDialog(_WithMenu):
        """The window with a modeless dialog painted where it stands."""

    def officina_filters(*, expand=(), advanced: bool = False, control: str | None = None,
                         unavailable: bool = False, dirty: bool = False):
        """Phase 2.5 (U4): "Filtri del confronto" of case B's v2, over the case
        view: zones, variables and "da decidere" with scripted counts and
        occurrences (anchors of the scripted differences), the rows ``expand``
        expanded, "Regole avanzate" open, the control generation ``control``."""
        def prepare():
            from PySide6.QtCore import QPoint

            from qtrequestory.ui.contracts import ControlState, NoiseRule
            from qtrequestory.ui.pages.officina_filters import FiltersDialog
            from tests.fakes.fake_filters import fake_group, fake_occurrence

            state = officina_setup()
            api = services.officina
            d = state["filters"]

            def occ(diff, page=0, pages=None, detail=""):
                return fake_occurrence(diff.left_text or diff.right_text, pagine=pages or (page,),
                                       anchors=(diff.anchor,), zona=diff.zone, dettaglio=detail)

            api.set_filter_groups(state["case"], [
                fake_group("zona.header", n=1, occorrenze=[occ(d["header"], pages=(0, 1))]),
                fake_group("zona.titolo"),
                fake_group("zona.footer", n=1, occorrenze=[occ(d["footer"], pages=(0, 1))]),
                fake_group("zona.spalla_sx", n=1, occorrenze=[occ(d["shoulder"], pages=(0, 1))]),
                fake_group("zona.spalla_dx"),
                fake_group("zona.numero_pagina", n=2, occorrenze=[occ(d["page_no"]), occ(d["page_no"], 1)]),
                fake_group("zona.filigrana"),
                fake_group("zona.invisibile", n=3, occorrenze=[
                    fake_occurrence("MOD_TEST_CODICE_0001", pagine=(0,)),
                    fake_occurrence("MOD_TEST_CODICE_0001", pagine=(1,)),
                    fake_occurrence("Acme-Servizi", pagine=(1,))]),
                fake_group("variabile.segnaposto"),
                fake_group("variabile.buco", n=1, occorrenze=[occ(d["variable"], detail="importoMensile")]),
                fake_group("variabile.cella"),
                fake_group("variabile.sezione"),
                fake_group("variabile.esecuzione"),
                fake_group("variabile.listino"),
                fake_group("decidere.maiuscole", n=1, occorrenze=[occ(d["caps"])]),
                fake_group("decidere.punteggiatura", n=1, occorrenze=[occ(d["punct"])]),
                fake_group("avanzate.Numero di pagina"),
                fake_group("avanzate.Data", n=1, occorrenze=[occ(d["noise"])]),
                fake_group("avanzate.IBAN"),
                fake_group("avanzate.Codice fiscale"),
                fake_group("avanzate.Codice pratica", n=0),
            ])
            api.set_control_state(state["case"], ControlState(control, (
                "riconoscimento esteso non disponibile per questo caso" if control == "non_disponibile" else ""))
                if control else ControlState("pronta"))
            page, case = officina_open_case_version(2)
            ini = page.ini
            if not case.review.noise_rules:
                api.set_noise_rules(ini, case, [NoiseRule("Codice pratica", r"PR-\d{6}")])
                page._reload_initiative()

            class _Offscreen(FiltersDialog):
                def __init__(self, *a, **k) -> None:
                    super().__init__(*a, **k)
                    self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            page.filters_dialog_class = _Offscreen
            if unavailable:  # the real service before A5
                def not_yet(*_a):
                    raise NotImplementedError

                api.filters = not_yet
            try:
                page.open_filters()
            finally:
                api.__dict__.pop("filters", None)
            dialog = page.filters_dialog
            dialog.resize(700, 660)
            dialog.move(window.mapToGlobal(QPoint(window.width() - 700 - 330, 70)))
            for fid in expand:
                dialog.row(fid).set_expanded(True)
            dialog.set_advanced(advanced or unavailable)
            if dirty:
                dialog.editor.add_rule("Rotta", "(a+")
            pump(600)
            shot = _WithDialog(dialog)

            def close() -> None:
                dialog.ask_unsaved = lambda **_k: "discard"
                dialog.close()
                page.filters_dialog_class = FiltersDialog
                api.set_control_state(state["case"], None)
                api.set_filter_groups(state["case"], None)

            shot.close = close
            return shot
        return prepare

    def officina_case_dom():
        """U6: the DOM tab of the HTML case, the link difference selected in the list."""
        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["html_ini"])
        page.open_case(state["html_case"])
        pump(2500)
        view = page.case_view
        view.set_dom_mode(True)
        end = time.monotonic() + 10
        while view.dom.stack.currentWidget() is not view.dom.splitter and time.monotonic() < end:
            pump(100)
        anchor = state["html_link"].anchor
        target = next(j for j in view.docs.judged.judged if j.diff.anchor == anchor)
        view.diffs.list.setCurrentRow(view.diffs.row_ids().index(target.diff.id))
        pump(600)
        print("dom: link on lines", view.dom.line_of(target.diff.id))
        return None

    engine_state: dict[str, object] = {}
    engine_lines = ["Contratto di prova per Acme-Servizi, modulo di adesione.",
                    "Il prezzo resta fisso per dodici mesi dalla data di attivazione.",
                    "La carta sarà abilitata agli acquisti online e nei negozi.",
                    "Pagamento con addebito mensile anticipato sul conto indicato.",
                    "Il servizio clienti risponde entro tre giorni lavorativi.",
                    "Località ..........",
                    "Firma del cliente in calce al modulo, con la data."]

    def officina_engine_setup():
        """I1: a case of the third initiative ("Motore reale") whose
        comparisons come from the REAL engine (``compare_docs`` on synthetic
        PDFs, canned into the fake: its verdicts equal the service's, the
        fidelity test says so). AS-IS, v1, v2: one fatta, one in corso, marks
        made in v1 (one resolved, a stuck da fare, a stuck regressione), a
        tolerance whose difference is gone in v2 (inactive), a new v2
        regression, a variable slot. A second case, compared two-way, then
        given an AS-IS: its board pill says "da riconfrontare"."""
        if engine_state:
            return engine_state
        from qtrequestory.officina.compare.extract_pdf import extract
        from qtrequestory.officina.compare.pipeline import compare_docs
        from tests.fakes.fake_core import canned_pdf
        from tests.officina import pdfgen

        officina_setup()
        api = services.officina
        folder = tmp / "officina-motore"
        folder.mkdir(exist_ok=True)
        filler = [pdfgen.lorem(70, seed=40 + n) for n in range(6)]

        def pdf(name: str, *changes: tuple[str, str], extra: str = "", font_pt: float = 11) -> Path:
            lines = []
            for line in engine_lines:
                for old, new in changes:
                    line = line.replace(old, new)
                lines.append(line)
            body = [*lines[:3], *filler[:3], *lines[3:], *filler[3:]] + ([extra] if extra else [])
            return pdfgen.paragraphs_pdf(folder / f"{name}.pdf", body, font_pt=font_pt)

        target = pdf("target")
        bodies = {
            "asis": pdf("asis", ("dodici", "ventiquattro"), ("abilitata", "abilitato"),
                        ("mensile", "trimestrale"), ("tre giorni", "cinque giorni"),
                        ("..........", "Springfield"), font_pt=12),  # + a style change (Stretto only)
            1: pdf("v1", ("dodici", "ventiquattro"), ("abilitata", "abilitato"), ("tre giorni", "cinque giorni"),
                   ("Firma del", "Firme del"), ("calce", "calse"), ("..........", "Springfield")),
            2: pdf("v2", ("abilitata", "abilitato"), ("tre giorni", "quattro giorni"), ("Firma del", "Firme del"),
                   ("..........", "Shelbyville"), extra="Paragrafo aggiunto soltanto nella seconda versione."),
        }
        payloads = tmp / "officina-payloads"
        ini = api.create_initiative("Motore reale")
        for key in ("MOD_TEST_MOTORE_G", "MOD_TEST_MOTORE_H"):
            path = payloads / f"{key}.json"
            path.write_text('{"documents": [{"template": {"templateKey": "%s"}}]}' % key, encoding="utf-8")
            api.case_from_file(ini, path, key, "")
        ini = api.load(ini.id)
        case, other = sorted(ini.cases, key=lambda c: c.key)
        target_doc = extract(target)
        for c in (case, other):
            api.set_target(c, target)
        api.set_response(bodies["asis"].read_bytes())
        api.generate(ini, case, "asis")
        api.set_canned(case.id, 0, compare_docs(target_doc, extract(bodies["asis"]), right_label="AS-IS"))
        for number in (1, 2):
            api.set_response(bodies[number].read_bytes())
            api.generate(ini, case, "tobe")
            api.set_canned(case.id, number, compare_docs(target_doc, extract(bodies[number])))
        ini = api.load(ini.id)
        case = next(c for c in ini.cases if c.id == case.id)
        v1, v2 = case.tobe_versions()[:2]
        first = api.compare_case(ini, case, v1)
        marked = [next(j for j in first.judged if text in j.diff.left_text) for text in ("dodici", "abilitata", "Firma")]
        api.tolerate(case, next(j for j in first.judged if "calce" in j.diff.left_text), "refuso segnalato")
        api.compare_case(ini, case, v2)  # the tolerated difference is gone in v2: inactive
        # the second case: compared two-way, then an AS-IS arrives (the board: da riconfrontare)
        api.set_response(bodies[1].read_bytes())
        api.generate(ini, other, "tobe")
        api.set_canned(other.id, 1, compare_docs(target_doc, extract(bodies[1])))
        other = next(c for c in api.load(ini.id).cases if c.id == other.id)
        api.compare_case(ini, other, other.tobe_versions()[0])
        time.sleep(1.1)  # the summary's time has seconds only
        api.set_response(bodies["asis"].read_bytes())
        api.generate(ini, other, "asis")
        api.set_response(canned_pdf("x"))
        engine_state.update(ini=ini.id, case=case.id, marked=marked)
        return engine_state

    def officina_engine_case(tab: str = "guardare", select: str | None = None, version: str = "v2",
                             *, verify: bool = False):
        def prepare():
            state = officina_engine_setup()
            page = window.page("officina")
            if verify:  # three marks made in v1: opening v2 verifies them (every mode)
                case = next(c for c in services.officina.load(state["ini"]).cases if c.id == state["case"])
                for j in state["marked"]:
                    services.officina.mark_done(case, j, 1)
            window.show_page("officina")
            page.open_initiative(state["ini"])
            page.open_case(state["case"], version)
            pump(2500)
            view = page.case_view
            if view.docs is not None and view.docs.judged is not None:
                view.diffs.set_tab(tab)
                ids = view.diffs.row_ids()
                chosen = next((j.diff.id for j in view.docs.judged.judged
                               if select and select in j.diff.left_text and j.diff.id in ids), None)
                if chosen is None and ids:
                    chosen = ids[0]
                if chosen is not None:
                    view.diffs.select(chosen)
                cc = view.docs.judged
                print("engine case:", ascii([(j.diff.op, j.diff.klass, j.verdict, j.unresolved, j.marked,
                                              j.diff.left_text[:24]) for j in cc.judged]),
                      "inactive", cc.inactive, "|", ascii(view.banners.outcome_text()), "|",
                      ascii(view.diffs.tab_texts()))
            elif view.diffs.list.count():
                view.diffs.list.setCurrentRow(0)
            pump(900)
        return prepare

    def officina_engine_asis_strict():
        """I1 fix: the AS-IS view under the Stretto profile (style rows named as such)."""
        state = officina_engine_setup()
        api = services.officina
        ini = api.load(state["ini"])
        case = next(c for c in ini.cases if c.id == state["case"])
        api.set_profile(ini, case, "stretto")
        officina_engine_case(version="asis")()

        def undo() -> None:
            api.set_profile(api.load(state["ini"]), case, None)

        return _Restoring(window, undo)

    def officina_engine_done():
        """R45: "✓ Mostra fatte" on: the fatte underlined in green on the target
        side and in its minimap."""
        officina_engine_case()()
        view = window.page("officina").case_view
        view.done_button.setChecked(True)
        pump(600)

    def officina_engine_more_menu():
        """R45: the case header's "⋯" menu with "Azzera tolleranze…"."""
        officina_engine_case()()
        view = window.page("officina").case_view
        menu = view.more_button.menu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        at = view.more_button.mapToGlobal(view.more_button.rect().bottomRight())
        menu.popup(at)
        menu.move(at.x() - menu.sizeHint().width(), at.y())
        pump(300)
        return _WithMenu(menu)

    def officina_html_without_edge():
        """R45 (spec §6): an HTML case whose print fails (Edge missing): the
        DOM comparison, the viewers' notice, the DOM tab as the main view."""
        state = officina_setup()
        api = services.officina
        if "noedge_case" not in state:
            ini = api.load(state["html_ini"])
            payload = tmp / "officina-payloads" / "MOD_TEST_EMAIL_SENZA_EDGE.json"
            payload.write_text('{"documents": [{"template": {"templateKey": "MOD_TEST_EMAIL_SENZA_EDGE"}}]}',
                               encoding="utf-8")
            api.case_from_file(ini, payload, "MOD_TEST_EMAIL_SENZA_EDGE", "")
            ini = api.load(ini.id)
            case = next(c for c in ini.cases if c.key == "MOD_TEST_EMAIL_SENZA_EDGE")
            body = "".join(f"<p>{line.strip()}</p>" for line in email_pretty.splitlines()
                           if line.strip() and not line.strip().startswith("<"))
            body += "<p>Senza stampa: confronto sul DOM.</p>" * 8
            target = tmp / "officina-payloads" / "Email senza Edge.html"
            target.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
            api.set_target(case, target)
            api.set_response(f"<html><body>{body}</body></html>".encode())
            api.generate(ini, case, "tobe")
            from tests.fakes.fake_core import canned_pdf

            api.set_response(canned_pdf("x"))
            api.set_canned(case.id, 1, list(api.canned[state["html_case"]][1].diffs))
            api.set_dom_view(case.id, (email_pretty, email_generated))
            state["noedge_case"] = case.id
        api.set_print_error("Microsoft Edge non trovato")
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["html_ini"])
        page.open_case(state["noedge_case"])
        pump(2500)
        view = page.case_view
        end = time.monotonic() + 10
        while view.dom.stack.currentWidget() is not view.dom.splitter and time.monotonic() < end:
            pump(100)
        print("no print: dom mode", view.dom_mode(), "|", ascii(view.left.message_text()[:60]))

        def undo() -> None:
            api.set_print_error(None)

        return _Restoring(window, undo)

    def officina_html_without_edge_documents():
        """The same case, "Documenti" chosen: the viewers' notice in place of the print."""
        restoring = officina_html_without_edge()
        view = window.page("officina").case_view
        view.set_dom_mode(False)
        pump(400)
        return restoring

    def officina_filters_email():
        """Final review M3: "Filtri del confronto" of the HTML case: the control
        line says an email has no control generation."""
        from PySide6.QtCore import QPoint

        from qtrequestory.ui.pages.officina_filters import FiltersDialog

        state = officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["html_ini"])
        page.open_case(state["html_case"])
        pump(1500)

        class _Offscreen(FiltersDialog):
            def __init__(self, *a, **k) -> None:
                super().__init__(*a, **k)
                self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

        page.filters_dialog_class = _Offscreen
        page.open_filters()
        dialog = page.filters_dialog
        dialog.resize(700, 560)
        dialog.move(window.mapToGlobal(QPoint(window.width() - 700 - 330, 70)))
        pump(600)
        print("email control line:", ascii(dialog.control.text()))
        shot = _WithDialog(dialog)

        def close() -> None:
            dialog.close()
            page.filters_dialog_class = FiltersDialog

        shot.close = close
        return shot

    def officina_engine_board():
        state = officina_engine_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.open_initiative(state["ini"])
        pump(1200)

    def officina_engine_confirm(which: str):
        """I1: the "Target…" (R29) and "Segna accettato" (spec §5.4) questions,
        as ``officina_dialogs.confirm`` asks them, on the engine case."""
        def prepare():
            from PySide6.QtWidgets import QMessageBox

            from qtrequestory.ui import strings as s

            officina_engine_case()()
            page = window.page("officina")
            case = page._case(page.case_id)
            if which == "target":
                title, text = s.OFFICINA_TARGET_REPLACE_TITLE, s.OFFICINA_TARGET_REPLACE
            else:
                title, text = s.OFFICINA_MARK_ACCEPTED, page.case_view.acceptance_warning()
            box = QMessageBox(QMessageBox.Icon.Question, title, text,
                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, window)
            box.setDefaultButton(QMessageBox.StandardButton.No)
            box.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            box.show()
            pump(300)
            print("confirm:", ascii(text))
            return box
        return prepare

    real_state: dict[str, object] = {}
    real_body = ["Condizioni del servizio di prova per il cliente, modulo di adesione.",
                 "La carta sarà abilitata agli acquisti online e nei negozi convenzionati.",
                 "Il prezzo resta fisso per dodici mesi dalla data di attivazione.",
                 "Importo mensile: 12,50 euro",
                 "Il pagamento avviene con addebito sul conto indicato, ogni mese.",
                 "Lorem ipsum resta il testo di riempimento del modulo di prova.",
                 "Le comunicazioni arrivano all'indirizzo indicato nella richiesta.",
                 "Il recesso è gratuito entro quattordici giorni dalla firma.",
                 "Questa riga manca nel documento generato dal generatore.",
                 "Data di sottoscrizione: 01/02/2026",
                 "Il servizio clienti risponde entro tre giorni lavorativi."]

    def officina_real_setup():
        """I1b: a fourth initiative ("Motore 2.5") whose case comparison,
        "Filtri del confronto" panel, switches and control state come from the
        REAL ``OfficinaService`` (the fake's own ``_service``), on a synthetic
        two-page pair with a header, a footer, page numbers and body changes
        of every kind; the AS-IS view (``compare``) is the real one anyway."""
        if real_state:
            return real_state
        from qtrequestory.ui.contracts import NoiseRule
        from tests.officina import pdfgen

        officina_setup()
        api = services.officina
        real = api._service
        folder = tmp / "officina-reale"
        folder.mkdir(exist_ok=True)

        def doc(name: str, head: str, edition: str, changes=(), drop: str = "", add: str = "") -> Path:
            lines = [line for line in real_body if line != drop]
            for old, new in changes:
                lines = [line.replace(old, new) for line in lines]
            if add:
                lines.insert(6, add)

            def paint(painter, page: int) -> None:
                pdfgen.draw_text(painter, 56, 40, head)
                pdfgen.draw_text(painter, 56, 800, f"Documento di prova · edizione {edition}")
                pdfgen.draw_text(painter, 480, 800, f"Pagina {page + 1} di 2")
                body = lines if page == 0 else [line + " (seconda pagina)" for line in lines[:5]]
                for k, line in enumerate(body):
                    pdfgen.draw_text(painter, 56, 110 + 26 * k, line)
            return pdfgen.painted_pdf(folder / f"{name}.pdf", paint, pages=2, font_pt=10.5)

        target = doc("atteso", "Acme-Servizi S.p.A. · Modulo di adesione", "04/2026")
        tobe = doc("generato", "Acme S.p.A. · Modulo di adesione", "05/2026",
                   (("abilitata", "abilitato"), ("dodici", "ventiquattro"), ("12,50", "18,40"),
                    ("Lorem ipsum", "LOREM IPSUM"), ("ogni mese.", "ogni mese"), ("01/02/2026", "03/04/2026")),
                   drop="Questa riga manca nel documento generato dal generatore.",
                   add="Una riga aggiunta soltanto nel documento generato.")
        asis = doc("asis", "Acme-Servizi S.p.A. · Modulo di adesione", "04/2026",
                   (("dodici", "diciotto"), ("01/02/2026", "05/06/2026")))
        payloads = tmp / "officina-payloads"
        key = "MOD_TEST_MOTORE_25"
        path = payloads / f"{key}.json"
        path.write_text('{"documents": [{"template": {"templateKey": "%s"}}], '
                        '"offerta": {"importoMensile": "18,40"}}' % key, encoding="utf-8")
        ini = api.create_initiative("Motore 2.5")
        api.case_from_file(ini, path, key, "")
        ini = api.load(ini.id)
        case = ini.cases[0]
        api.set_target(case, target)
        api.set_response(asis.read_bytes())
        api.generate(ini, case, "asis")
        api.set_response(tobe.read_bytes())
        api.generate(ini, case, "tobe")
        from tests.fakes.fake_core import canned_pdf

        api.set_response(canned_pdf("x"))
        ini = api.load(ini.id)
        case = ini.cases[0]
        real.set_noise_rules(ini, case, [NoiseRule("Date del modulo", r"\d{2}/\d{2}/2026")])
        mine = ini.id

        def ours(ini_or_case) -> bool:
            folder_ = getattr(ini_or_case, "folder", None)
            return getattr(ini_or_case, "id", None) == mine or (
                folder_ is not None and folder_.parent.parent.name == mine)

        def install() -> None:
            """The real service for this initiative, the fake's own methods for
            the others; again at every scene (the fake Filtri scenes drop the
            fake's instance attributes)."""
            def route(name: str, *args):
                if ours(args[0]):
                    return getattr(real, name)(*args)
                return getattr(type(api), name)(api, *args)

            for name in ("compare_case", "filters", "set_filters", "control_state"):
                setattr(api, name, lambda *args, _n=name: route(_n, *args))

        real_state.update(ini=ini.id, case=case.id, install=install)
        install()
        return real_state

    def officina_real(version: str = "tobe", *, tab: str = "tutte", select: str | None = None,
                      filters: bool = False, expand=(), side_types=(), zoom: float | None = None):
        """I1b: the "Motore 2.5" case driven by the real engine: ``version``
        ("tobe" or "asis"), the side panel on ``tab`` with ``select`` (text of
        the target side, or "+" for the first one-sided difference) selected,
        or the real "Filtri del confronto" panel with rows ``expand`` open."""
        def prepare():
            from PySide6.QtCore import QPoint

            from qtrequestory.ui.pages.officina_docside import version_key
            from qtrequestory.ui.pages.officina_filters import FiltersDialog

            state = officina_real_setup()
            state["install"]()
            page = window.page("officina")
            window.show_page("officina")
            page.open_initiative(state["ini"])
            case = page._case(state["case"])
            page.open_case(case.id, "asis" if version == "asis" else version_key(case.tobe_versions()[0]))
            pump(4000)
            view = page.case_view
            view.diffs.set_tab(tab)
            view.diffs.set_types(set(side_types))
            ids = view.diffs.row_ids()
            rows = (view.docs.judged.judged if view.docs.judged is not None
                    else [type("J", (), {"diff": d})() for d in view.docs.comparison.diffs])
            chosen = None
            for j in rows:
                d = j.diff
                if d.id not in ids:
                    continue
                if (select == "+" and bool(d.left) != bool(d.right)) or (select and select in d.left_text):
                    chosen = d.id
                    break
            chosen = chosen if chosen is not None else (ids[0] if ids else None)
            if zoom is not None:  # zoomed in: the empty side has to scroll to its place
                view.left.view.set_zoom(zoom)
                pump(600)
            if chosen is not None:
                view.diffs.select(chosen)
                view.sync.focus_difference(chosen, reveal=True)
            print("real engine:", version, ascii([(d.op, d.klass, d.zone, d.tipo, d.prova, d.left_text[:20],
                                                   d.right_text[:20], d.empty_at is not None)
                                                  for d in (j.diff for j in rows)]))
            print("  tabs:", ascii(view.diffs.tab_texts()), "chosen", chosen)
            pump(900)

            def undo() -> None:
                view.diffs.set_types(set())
                if zoom is not None:
                    view.left.view.set_zoom("fit_width")

            if not filters:
                return _Restoring(window, undo)

            class _Offscreen(FiltersDialog):
                def __init__(self, *a, **k) -> None:
                    super().__init__(*a, **k)
                    self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)

            page.filters_dialog_class = _Offscreen
            page.open_filters()
            dialog = page.filters_dialog
            dialog.resize(700, 660)
            dialog.move(window.mapToGlobal(QPoint(window.width() - 700 - 330, 70)))
            for fid in expand:
                dialog.row(fid).set_expanded(True)
            print("  panel:", ascii([(g.id, g.n, g.attivo) for g in
                                     services.officina.filters(page.ini, page._case(state["case"])).groups if g.n]))
            pump(600)
            shot = _WithDialog(dialog)

            def close() -> None:
                dialog.ask_unsaved = lambda **_k: "discard"
                dialog.close()
                page.filters_dialog_class = FiltersDialog
                undo()

            shot.close = close
            return shot
        return prepare

    scenes += [
        ("officina-consegna", officina_delivery_dialog),
        ("officina-consegna-riepilogo", officina_delivery_summary),
        ("officina-configura", officina_setup_card(keep_root=False)),
        ("officina-configura-generatore", officina_setup_card(keep_root=True)),
        ("wizard-officina", wizard_officina),
        ("officina-configura-vuota", officina_setup_card(keep_root=False, sidecar=False)),
        ("wizard-officina-vuota", lambda: wizard_officina(sidecar=False)),
        ("officina-iniziative", officina_list),
        ("officina-bacheca", officina_board),
        ("officina-bacheca-pillole", officina_board_pills),
        ("officina-caso-minimappa", officina_case_minimap),
        ("officina-visore-anelli", officina_viewer_u1("section", 1.0)),
        ("officina-visore-mancante", officina_viewer_u1("missing", 1.0)),
        ("officina-visore-zoom-orizzontale", officina_viewer_u1("section", 2.2, 0.8)),
        ("officina-caso", officina_case),
        ("officina-caso-verdetti", officina_case_verdicts),
        ("officina-caso-verifica", officina_case_verification),
        ("officina-caso-due-vie", officina_case_two_way),
        ("officina-caso-senza-testo", officina_case_no_text),
        ("officina-caso-menu", officina_case_menu),
        ("officina-caso-uguale-asis", officina_case_same_as_asis),
        ("officina-caso-asis", officina_case_asis),
        ("officina-pannello-tipi", officina_panel()),
        ("officina-pannello-filtro-tipo", officina_panel(types=("parola", "zona"))),
        ("officina-pannello-tutte", officina_panel("tutte", fold=("parola", "zona", "numeri", "maiuscole"))),
        ("officina-pannello-chiuso", officina_panel(collapsed=True)),
        ("officina-pannello-legenda", officina_panel(legend=True)),
        ("officina-elenco-una-lettera", officina_list_select("guardare", "one_letter")),
        ("officina-elenco-da-verificare", officina_list_select("verificare")),
        ("officina-elenco-non-risolta", officina_list_select("guardare", "stuck", verification=True)),
        ("officina-elenco-in-corso", officina_list_select("guardare", "in_corso")),
        ("officina-elenco-link", officina_list_select("guardare", "link")),
        ("officina-azioni-mini-barra", officina_action_bar),
        ("officina-azioni-menu", officina_action_menu),
        ("officina-azioni-toast", officina_action_toast),
        ("officina-azioni-tollera-nota", officina_action_note),
        ("officina-bacheca-invio", officina_board_sending),
        ("officina-caso-invio", officina_case_sending),
        ("officina-payload-header", officina_editor),
        ("officina-aggiungi", officina_add_dialog),
        ("officina-aggiungi-chiamata", officina_pick_dialog),
        ("officina-payload-cambia-chiamata", officina_editor_payload),
        ("officina-aggiungi-chiamata-domanda", officina_pick_question),
        ("officina-caso-chiamata-cambiata", officina_call_strip),
        ("officina-rumore", officina_noise_dialog),
        ("officina-filtri", officina_filters()),
        ("officina-filtri-occorrenze", officina_filters(expand=("zona.footer", "zona.invisibile",
                                                                "variabile.buco"))),
        ("officina-filtri-avanzate", officina_filters(advanced=True)),
        ("officina-filtri-controllo-in-corso", officina_filters(control="in_corso")),
        ("officina-filtri-controllo-non-disponibile", officina_filters(control="non_disponibile")),
        ("officina-filtri-controllo-assente", officina_filters(control="assente")),
        ("officina-filtri-non-disponibile", officina_filters(unavailable=True)),
        ("officina-filtri-email", officina_filters_email),
        ("officina-filtri-regole-non-salvate", officina_filters(advanced=True, dirty=True)),
        ("officina-caso-dom", officina_case_dom),
        # I1: the real engine's comparisons behind the case view
        ("officina-motore-caso", officina_engine_case(verify=True)),
        ("officina-motore-regressione-non-risolta", officina_engine_case(select="Firma")),
        ("officina-motore-in-corso", officina_engine_case(select="tre giorni")),
        ("officina-motore-tutte-inattive", officina_engine_case("tutte")),
        ("officina-motore-asis", officina_engine_case(version="asis")),
        ("officina-motore-asis-stretto", officina_engine_asis_strict),
        ("officina-motore-bacheca", officina_engine_board),
        ("officina-motore-conferma-target", officina_engine_confirm("target")),
        ("officina-motore-conferma-accetta", officina_engine_confirm("accept")),
        ("officina-motore-mostra-fatte", officina_engine_done),
        ("officina-motore-menu-azzera", officina_engine_more_menu),
        ("officina-html-senza-edge", officina_html_without_edge),
        ("officina-html-senza-edge-documenti", officina_html_without_edge_documents),
        # I1b: the real engine drives the case view, the side panel and the Filtri panel
        ("officina-reale-caso", officina_real(tab="guardare")),
        ("officina-reale-pannello-tipi", officina_real(tab="tutte", select="abilitata")),
        ("officina-reale-pannello-zone", officina_real(tab="tutte", select="Acme-Servizi")),
        ("officina-reale-mancante", officina_real(tab="tutte", select="+", zoom=2.4)),
        ("officina-reale-filtri", officina_real(filters=True, expand=("zona.header", "zona.footer"))),
        ("officina-reale-filtri-avanzate", officina_real(filters=True, expand=("avanzate.Date del modulo",
                                                                               "variabile.buco"))),
        ("officina-reale-asis", officina_real("asis", tab="tutte")),
        # D6: undoable deletion (last: its initiatives appear in no other scene)
        ("officina-eliminazione-una", officina_deletions(1)),
        ("officina-eliminazione-gruppo", officina_deletions(3)),
        ("officina-eliminazione-elenco", officina_deletions(3, expanded=True)),
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
                # Every scene starts from the scene mirror: the "-cartella-non-
                # valida" ones empty it on purpose, and a later scene writing
                # under Path("") would write into the CWD (final review I2).
                if services.config.config.mirror_root != good_config.mirror_root:
                    mirror_root(None)
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
                window.deletions.undo_all()  # a scene never deletes anything (D6)
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
