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

    def officina_verdicts(ini, case_id: str) -> None:
        """Phase 2 (U1): script the fake's ``compare_case`` for case B so that
        its TO-BE v2 holds every verdict and state — regressione, da fare, non
        risolta (marked in v1, unchanged in v2), in corso, da verificare
        (marked in v2), fatta, tollerata (by profile and by hand), rumore,
        variabile — on word boxes of page 1 of the synthetic PDFs."""
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

        da_fare = last_letter(20)
        stuck = one_more(34, "e")
        before = diff("cambiato", "testo", 48, generated="prima")
        now = one_more(48, "i", before)
        promised = diff("cambiato", "testo", 62, generated=rw[62].text.upper())
        done = diff("mancante", "testo", 76, 2, right=False)
        by_hand = diff("cambiato", "testo", 104, generated=rw[104].text + "!")
        link = fake_diff("cambiato", "link", "Scopri le condizioni", "Scopri le condizioni",
                         before="Per i dettagli", after="del servizio.",
                         detail="href: https://example.invalid/condizioni → "
                                "https://example.invalid/condizioni-2025")
        tobe = [
            diff("in_piu", "testo", 6, 2, left=False),               # regressione
            da_fare, stuck, now, promised,
            diff("cambiato", "stile", 90),                            # tollerata (profilo)
            by_hand,                                                  # tollerata a mano
            diff("cambiato", "rumore", 118),
            diff("cambiato", "variabile", 132, 2),
            link,                                                     # solo nell'elenco
        ]
        # U2: a v1-only difference, so that a mark made in v1 is "risolta" in v2
        extra = fake_diff("cambiato", "testo", "Titolo di esempio", "Titolo")
        api.set_canned(case_id, 0, [da_fare, stuck, before, promised, done, by_hand, link])
        api.set_canned(case_id, 1, [*tobe, extra])
        api.set_canned(case_id, 2, tobe)
        case = next(c for c in ini.cases if c.id == case_id)
        v1, v2 = case.tobe_versions()[:2]
        first = api.compare_case(ini, case, v1)
        api.mark_done(case, next(j for j in first.judged if j.diff.anchor == stuck.anchor), 1)
        second = api.compare_case(ini, case, v2)  # verifies the v1 mark: still there
        by_anchor = {j.diff.anchor: j for j in second.judged}
        api.mark_done(case, by_anchor[promised.anchor], 2)
        api.tolerate(case, by_anchor[by_hand.anchor], "scelta di esempio")
        officina_state.update(stuck=stuck, extra=extra, one_letter=da_fare, in_corso=now, link=link)

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

    def officina_case_verdicts() -> None:
        """Phase 2 (U1): case B's v2 judged by the scripted fake — every verdict
        and state drawn by verdict, the fatte shown, the regression focused."""
        officina_case()
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
        """Where the documents start (R28: well above 45% of the window height)."""
        from PySide6.QtCore import QPoint

        view = window.page("officina").case_view
        top = view.left.view.mapTo(window, QPoint(0, 0)).y()
        print(f"{what}: documents start at y={top} of {window.height()} "
              f"({100 * top / window.height():.1f}%)")

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

    def officina_case_profile():
        """Phase 2 (U2): the header's profile menu open on case B."""
        page, _case = officina_open_case_version(2)
        button = page.case_view.profile_button
        menu = button.menu()
        menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        corner = button.mapToGlobal(button.rect().bottomRight())
        corner.setX(corner.x() - menu.sizeHint().width())  # inside the window's right edge
        menu.popup(corner)
        pump(300)
        return _WithMenu(menu)

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
        """U6: "Regole di rumore…" of the HTML case: the presets all off, two
        rules of the case — one counted, one whose regex does not compile."""
        from qtrequestory.ui import strings as s
        from qtrequestory.ui.contracts import NoiseRule
        from qtrequestory.ui.pages.officina_format import case_title
        from qtrequestory.ui.pages.officina_noise import NoiseDialog

        state = officina_setup()
        page = window.page("officina")
        page.open_initiative(state["html_ini"])
        case = page._case(state["html_case"])
        rules = [NoiseRule("Codice pratica", r"PR-\d{6}"), NoiseRule("Saluti", r"(Cordiali saluti")]
        dialog = NoiseDialog(s.RUMORE_TITLE_CASE.format(name=case_title(case)),
                             services.officina.noise_presets(), set(), rules,
                             own_title=s.RUMORE_OWN_CASE, counter=page._counter(case),
                             counts_note=s.RUMORE_COUNTS_ON.format(case=case_title(case)), parent=window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        dialog.resize(820, 600)
        dialog.show()
        end = time.monotonic() + 10
        while dialog.is_counting() and time.monotonic() < end:
            pump(100)
        pump(300)
        print("noise counts:", [dialog.hits_shown(dialog.own, r) for r in range(dialog.own.rowCount())])
        return dialog

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

    scenes += [
        ("officina-consegna", officina_delivery_dialog),
        ("officina-consegna-riepilogo", officina_delivery_summary),
        ("officina-cartella", officina_chooser),
        ("officina-iniziative", officina_list),
        ("officina-bacheca", officina_board),
        ("officina-bacheca-pillole", officina_board_pills),
        ("officina-caso-minimappa", officina_case_minimap),
        ("officina-caso", officina_case),
        ("officina-caso-verdetti", officina_case_verdicts),
        ("officina-caso-verifica", officina_case_verification),
        ("officina-caso-due-vie", officina_case_two_way),
        ("officina-caso-senza-testo", officina_case_no_text),
        ("officina-caso-profilo", officina_case_profile),
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
        ("officina-rumore", officina_noise_dialog),
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
