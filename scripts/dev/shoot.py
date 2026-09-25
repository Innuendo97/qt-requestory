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
            from qtrequestory.officina.compare.textdiff import compare_text
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
                                 diffs=compare_text(lt, rt).differences)
        return officina_docs

    def officina_viewer(zoom="fit_width"):
        def prepare():
            from PySide6.QtWidgets import QHBoxLayout, QWidget

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
                pick = (lambda d: d.left) if side == "left" else (lambda d: d.right)
                view.set_highlights([(d.id, d.kind, pick(d)) for d in docs["diffs"]])
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
        return officina_state

    def officina_list() -> None:
        officina_setup()
        page = window.page("officina")
        window.show_page("officina")
        page.show_list()
        pump(300)

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

    def officina_chooser() -> None:
        cfg = services.config.config
        saved = cfg.officina
        services.config.config = dataclasses.replace(
            cfg, officina=dataclasses.replace(saved, root=None))
        page = window.page("officina")
        window.show_page("officina")
        page.refresh()
        pump(300)
        services.config.config = dataclasses.replace(services.config.config, officina=saved)

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

    scenes += [
        ("officina-consegna", officina_delivery_dialog),
        ("officina-consegna-riepilogo", officina_delivery_summary),
        ("officina-cartella", officina_chooser),
        ("officina-iniziative", officina_list),
        ("officina-bacheca", officina_board),
        ("officina-caso", officina_case),
        ("officina-bacheca-invio", officina_board_sending),
        ("officina-caso-invio", officina_case_sending),
        ("officina-payload-header", officina_editor),
        ("officina-aggiungi", officina_add_dialog),
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
