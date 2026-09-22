"""Entry point: parse the arguments, then dispatch to the core.

Everything this module does is argument handling and printing; the behaviour
lives in ``core/jobs.py`` (sync/index), ``core/index/search.py`` (find),
``core/extract.py`` + ``core/opener.py`` (the extracted file) and
``core/scheduler.py`` (the Windows task).

Two rules shape the file:

* **Headless modes must not import Qt.** ``--sync`` runs from the scheduled
  task every hour; paying ~200 ms to load PySide6 for nothing would be absurd,
  and a machine without the Qt runtime must still be able to sync. The only
  ``qtrequestory.ui`` import is inside :func:`_start_gui`.
* **Nothing is created behind the user's back.** ``load_config`` no longer
  writes a default ``config.json`` (see ``core/config.py``), so a ``--sync``
  run before the first launch — or a first-run wizard the user cancelled —
  leaves ``is_first_run()`` True and the wizard appears next time.
"""
from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import signal
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from qtrequestory import __version__
from qtrequestory.core import facade, opener, scheduler
from qtrequestory.core.config import Config, load_config
from qtrequestory.core.events import CancelToken, EventSink, LoggingSink
from qtrequestory.core.index.search import SearchHit, SearchQuery
from qtrequestory.core.jobs import EXIT_CANCELLED, EXIT_ERRORS, JobReport, run_index_job, run_sync_job
from qtrequestory.core.logsetup import configure_logging, sync_logger
from qtrequestory.core.paths import AppPaths, app_paths

log = logging.getLogger(__name__)

TASK_ACTIONS = ("install", "remove", "status", "run")
#: ``--find`` prints the same shape the legacy ``nginx/find-call.py`` printed,
#: because the people using it read those three lines without thinking.
NOTHING_FOUND = "nessuna chiamata trovata nella finestra indicata"


def _guard_std_streams() -> None:
    """A windowed PyInstaller exe has sys.stdout/stderr == None: any print would raise."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


# ------------------------------------------------------------------- parsing ---


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="qtRequestory",
        description="Mirror, indicizza e cerca i log delle chiamate al document generator.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--sync", action="store_true", help="scarica i log e aggiorna l'indice")
    mode.add_argument("--index", action="store_true", help="indicizza i log già presenti in locale")
    mode.add_argument("--find", action="store_true", help="estrai una chiamata dall'indice")
    mode.add_argument("--task", choices=TASK_ACTIONS, help="gestisci l'attività pianificata")
    mode.add_argument("--version", action="store_true", help="mostra la versione ed esci")

    p.add_argument("--config", metavar="PERCORSO", help="usa questo file di configurazione")
    p.add_argument("-e", "--env", action="append", metavar="NOME",
                   help="ambiente su cui operare (ripetibile; con --find uno solo)")

    p.add_argument("--force", action="store_true", help="--sync: riscarica anche se già aggiornato")
    p.add_argument("--dry-run", action="store_true", help="--sync: mostra cosa farebbe senza scaricare")
    p.add_argument("--rebuild", action="store_true", help="--index: ricostruisci l'indice da zero")

    p.add_argument("-f", "--fdi", metavar="FDI", help="--find: FDI, anche solo un prefisso")
    p.add_argument("-k", "--template-key", metavar="KEY", help="--find: template key esatta")
    p.add_argument("--days", type=int, metavar="N", help="--find: finestra a ritroso da oggi")
    p.add_argument("--from", dest="day_from", metavar="DATA", help="--find: data inizio (YYYY-MM-DD)")
    p.add_argument("--to", dest="day_to", metavar="DATA", help="--find: data fine (YYYY-MM-DD)")
    p.add_argument("--out", metavar="PERCORSO", help="--find: scrivi qui invece che nella cartella temporanea")
    p.add_argument("--no-open", action="store_true", help="--find: non aprire il file nell'editor")
    return p


def _parse_day(parser: argparse.ArgumentParser, raw: str) -> date:
    """``YYYY-MM-DD`` or ``YYYYMMDD``, like the legacy script accepted."""
    try:
        return datetime.strptime(raw.replace("-", ""), "%Y%m%d").date()
    except ValueError:
        parser.error(f"data non valida: {raw!r} (attesa YYYY-MM-DD)")


def _check_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    """Refuse options that belong to another mode instead of ignoring them.

    Silently dropping ``--rebuild`` from a ``--sync`` invocation would make the
    user believe the index was rebuilt.
    """
    find_only = {"--fdi": args.fdi, "--template-key": args.template_key, "--days": args.days,
                 "--from": args.day_from, "--to": args.day_to, "--out": args.out,
                 "--no-open": args.no_open}
    if not args.find:
        for name, value in find_only.items():
            if value:
                parser.error(f"{name} si usa solo con --find")
    if args.rebuild and not args.index:
        parser.error("--rebuild si usa solo con --index")
    if (args.force or args.dry_run) and not args.sync:
        parser.error("--force e --dry-run si usano solo con --sync")
    if args.env and not (args.sync or args.index or args.find):
        parser.error("--env si usa con --sync, --index o --find")
    if args.find:
        if not args.fdi and not args.template_key:
            parser.error("--find richiede almeno --fdi o --template-key")
        if len(args.env or []) != 1:
            parser.error("--find richiede esattamente un ambiente (-e)")


# ---------------------------------------------------------------------- main ---


def main(argv: list[str] | None = None) -> int:
    _guard_std_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(f"qtRequestory {__version__}")
        return 0
    _check_arguments(parser, args)

    paths = _resolve_paths(args.config)
    config = load_config(paths.config_file)
    gui = not (args.sync or args.index or args.find or args.task)
    configure_logging(paths, headless=not gui, level=config.log_level)

    if args.sync:
        return _run_job(lambda sink, cancel: run_sync_job(
            config, envs=args.env, force=args.force, dry_run=args.dry_run, sink=sink, cancel=cancel))
    if args.index:
        return _run_job(lambda sink, cancel: run_index_job(
            config, envs=args.env, full_rebuild=args.rebuild, sink=sink, cancel=cancel))
    if args.find:
        return _run_find(parser, args, config)
    if args.task:
        return _run_task(args.task)
    return _start_gui(paths)


def _resolve_paths(config_override: str | None) -> AppPaths:
    """The app directory, with ``--config`` pointing ``config_file`` elsewhere."""
    paths = app_paths()
    if config_override:
        paths = dataclasses.replace(paths, config_override=Path(config_override))
    return paths


# ------------------------------------------------------------ sync / index ---


def _run_job(job: Callable[[EventSink, CancelToken], JobReport]) -> int:
    """Run a core job with the headless sink, honouring Ctrl+C.

    The signal handler only sets the token: the job then unwinds through its own
    cancellation points, which is what releases the process lock and leaves the
    index consistent. Killing it mid-write would not.
    """
    cancel = CancelToken()
    sink = LoggingSink(sync_logger())
    with _sigint_cancels(cancel):
        try:
            return job(sink, cancel).exit_code
        except KeyboardInterrupt:  # no handler could be installed (not the main thread)
            cancel.cancel()
            return EXIT_CANCELLED


@contextmanager
def _sigint_cancels(cancel: CancelToken) -> Iterator[None]:
    def handler(_signum, _frame) -> None:
        log.info("interruzione richiesta: annullo…")
        cancel.cancel()

    try:
        previous = signal.signal(signal.SIGINT, handler)
    except (ValueError, OSError):  # not the main thread: leave the default behaviour
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


# ------------------------------------------------------------------- --find ---


def _run_find(parser: argparse.ArgumentParser, args: argparse.Namespace, config: Config) -> int:
    """The legacy ``find-call.py`` on top of the index.

    Same contract as the old script: ONE file holding the pure pretty-printed
    request body, named after day/FDI/template key, opened in the editor, plus
    the "altre N entry" hint when the same day holds more matches.
    """
    env = args.env[0]
    day_to = _parse_day(parser, args.day_to) if args.day_to else date.today()
    window = args.days if args.days is not None else config.default_window_days
    day_from = _parse_day(parser, args.day_from) if args.day_from else day_to - timedelta(days=window)

    fdi = args.fdi.lower() if args.fdi else None
    key = args.template_key.upper() if args.template_key else None
    print(f"cerco in {env} dal {day_from} al {day_to}: fdi={fdi or '*'} key={key or '*'}")

    index = facade.IndexService(lambda: config)
    hits = index.search(SearchQuery(env=env, fdi_prefix=fdi, template_key=key,
                                    day_from=day_from, day_to=day_to))
    if not hits:
        print(NOTHING_FOUND)
        return EXIT_ERRORS

    hit = hits[0]
    extract = facade.ExtractService(lambda: config)
    text = extract.pretty_json(index.read_body(hit))
    if args.out:
        out = Path(args.out)
        extract.save_as(out, text)
    else:
        out = extract.write_temp_file(hit, text)

    print(f"trovato in {hit.file_path.name}: {hit.name}.json "
          f"(requestDate {hit.request_date or '?'}, {_documents(hit)} documenti)")
    _print_others([h for h in hits[1:] if h.day == hit.day])
    print(f"scritto: {out}")
    if not args.no_open:
        print(f"aperto in {_EDITOR_LABEL[extract.open_in_editor([out])]}")
    return 0


#: ``ExtractApi.open_in_editor`` answers "editor"/"default"; the user reads Italian.
_EDITOR_LABEL = {"editor": "Notepad++", "default": "app predefinita"}


def _documents(hit: SearchHit) -> str:
    return "?" if hit.ndocs is None else str(hit.ndocs)


def _print_others(others: list[SearchHit]) -> None:
    if not others:
        return
    print(f"altre {len(others)} entry che soddisfano la ricerca nello stesso giorno "
          f"(usa -f/-k per isolarne una):")
    for other in others:
        print(f"  - {other.name}.json  ({_documents(other)} documenti, "
              f"requestDate {other.request_date or '?'})")


# ------------------------------------------------------------------- --task ---


def scheduler_service() -> facade.SchedulerService:
    """Built through a function so tests can substitute a fake ``schtasks``."""
    return facade.SchedulerService()


def _run_task(action: str) -> int:
    service = scheduler_service()
    if action == "status":
        return _print_task_status(service.status(), service.exe_path())
    try:
        if action == "install":
            reason = service.unstable_location_reason()
            if reason:
                print(f"Attenzione: {reason}")
            service.register()
            print(f"Attività '{scheduler.TASK_NAME}' registrata.")
        elif action == "remove":
            service.unregister()
            print(f"Attività '{scheduler.TASK_NAME}' rimossa.")
        elif action == "run":
            service.run_now()
            print(f"Attività '{scheduler.TASK_NAME}' avviata.")
    except scheduler.SchedulerError as e:
        print(f"Errore: {e}")
        return EXIT_ERRORS
    return 0


def _print_task_status(status: scheduler.TaskStatus, exe: Path | None) -> int:
    """Print the task snapshot; exit 1 when there is no task (a shell can test it)."""
    print(f"Attività pianificata: {scheduler.TASK_NAME}")
    print(f"Registrata: {_yes_no(status.registered)}")
    if not status.registered:
        return EXIT_ERRORS
    print(f"Comando: {_or_dash(status.command)}")
    print(f"Argomenti: {_or_dash(status.args)}")
    print(f"Corrisponde all'eseguibile corrente: {_yes_no(status.exe_matches)} ({_or_dash(exe)})")
    print(f"Stato: {_or_dash(status.state)}")
    print(f"Prossima esecuzione: {_or_dash(status.next_run)}")
    print(f"Ultima esecuzione: {_or_dash(status.last_run)}")
    print(f"Ultimo esito: {_or_dash(status.last_result)}")
    return 0


def _yes_no(value: bool) -> str:
    return "sì" if value else "no"


def _or_dash(value: object) -> str:
    return "—" if value is None else str(value)


# --------------------------------------------------------------------- GUI ---


def _start_gui(paths: AppPaths) -> int:
    """The only place Qt is imported; a separate function so tests can replace it."""
    from qtrequestory.ui.app import run_gui
    from qtrequestory.ui.contracts import CoreServices

    return run_gui(CoreServices.real(paths))
