"""Entry point: parse the arguments, then dispatch to the core.

Everything this module does is argument handling and printing; the behaviour
lives in ``core/jobs.py`` (sync/index), ``core/index/search.py`` (find),
``core/extract.py`` (the extracted file, through ``facade.ExtractService``),
``core/scheduler.py`` (the Windows task) and ``cli_archive.py`` (``--archivio``
and ``--import``, the archive importer).

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
import ctypes
import dataclasses
import logging
import os
import signal
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from qtrequestory import __version__, cli_archive
from qtrequestory.core import daily, facade, scheduler
from qtrequestory.core.config import Config, UnknownEnvironment, load_config, mirror_root_errors
from qtrequestory.core.events import CancelToken, EventSink, FileSkipped, LoggingSink, format_size
from qtrequestory.core.index.search import SearchHit, SearchQuery, pick_best
from qtrequestory.core.jobs import EXIT_CANCELLED, EXIT_ERRORS, JobReport, run_index_job, run_sync_job
from qtrequestory.core.logsetup import configure_logging, sync_logger
from qtrequestory.core.paths import AppPaths, app_paths

log = logging.getLogger(__name__)

TASK_ACTIONS = ("install", "remove", "status", "run")
#: ``--find`` prints the same shape the legacy ``nginx/find-call.py`` printed,
#: because the people using it read those three lines without thinking.
NOTHING_FOUND = "nessuna chiamata trovata nella finestra indicata"
NOT_INDEXED = ("l'indice non contiene ancora nulla per '{env}': "
               "esegui --sync (o --index se i log sono già in locale)")
#: A config problem discovered before any job started, or an environment name
#: nothing knows about: distinct from EXIT_ERRORS (1, a job ran and failed)
#: and from the sync engine's own "nothing reachable" (also 2, but only after
#: it tried the network) — here nothing was attempted at all.
EXIT_CONFIG_ERROR = 2

#: Modes that read/print — the ones a windowed build's headless invocation
#: from an interactive terminal must not go silent for (Important #14).
_HEADLESS_FLAGS = ("--sync", "--index", "--find", "--task", "--version", "--archivio", "--import",
                   "--selftest-noise-guard")
_ATTACH_PARENT_PROCESS = -1


def _open_conout():
    """Isolated so tests can stub it instead of opening a real console handle."""
    return open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115


def _attach_parent_console(argv: list[str] | None) -> None:
    """A windowed PyInstaller exe (``console=False``) has no console of its
    own: ``sys.stdout``/``sys.stderr`` are ``None`` (see ``_guard_std_streams``
    right after this), so a headless mode run from an interactive terminal
    prints nothing anyone ever sees (Important #14).

    ``AttachConsole(ATTACH_PARENT_PROCESS)`` reattaches to the launching
    terminal's console; without one (the scheduled task, a double-click) it is
    a no-op and ``_guard_std_streams`` redirects to ``os.devnull``. Whether this run is headless is decided on the raw argv, before
    the parser exists, because this must run before ``_guard_std_streams``,
    which itself protects argparse's own error path. Any failure (not
    Windows, no ``ctypes.windll``, the API call itself) is swallowed: worst
    case the output stays invisible, same as before this existed.

    Both handles are opened first and reassigned only once BOTH succeeded:
    never a half-reattached stdout/stderr pair (fix round 1, Minor).
    """
    if sys.platform != "win32":
        return
    raw = list(argv) if argv is not None else sys.argv[1:]
    if not any(flag in raw for flag in _HEADLESS_FLAGS):
        return
    try:
        if ctypes.windll.kernel32.AttachConsole(_ATTACH_PARENT_PROCESS):
            new_out, new_err = _open_conout(), _open_conout()
            sys.stdout, sys.stderr = new_out, new_err
    except (AttributeError, OSError):
        pass


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
    mode.add_argument("--selftest-noise-guard", action="store_true", help=argparse.SUPPRESS)  # dev, R22
    mode.add_argument("--archivio", nargs="?", const="", metavar="PERCORSO",
                      help="elenca i log fuori dalla struttura dell'archivio (predefinito: la cartella "
                           "dei log) e cosa farebbe l'importazione; non modifica nulla")
    mode.add_argument("--import", dest="import_path", metavar="PERCORSO",
                      help="copia nell'archivio, verificandoli, i log trovati in PERCORSO, poi indicizza")

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
    p.add_argument("--env-for", action="append", metavar="CARTELLA=AMBIENTE",
                   help="--import: ambiente dei log di CARTELLA (relativa a PERCORSO, o assoluta); "
                        "'ignora' la salta. Ripetibile, vale solo per questa esecuzione")
    p.add_argument("--delete-originals", action="store_true",
                   help="--import: sposta nel Cestino gli originali copiati e verificati")
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
    # ``is not None``, not truthiness: ``--days 0`` is given, and this check
    # exists precisely so a given option is never silently ignored.
    find_only = {"--fdi": args.fdi, "--template-key": args.template_key, "--days": args.days,
                 "--from": args.day_from, "--to": args.day_to, "--out": args.out}
    if not args.find:
        for name, value in find_only.items():
            if value is not None:
                parser.error(f"{name} si usa solo con --find")
        if args.no_open:  # a flag: "not given" really is False
            parser.error("--no-open si usa solo con --find")
    if args.import_path is None:
        if args.env_for:
            parser.error("--env-for si usa solo con --import")
        if args.delete_originals:
            parser.error("--delete-originals si usa solo con --import")
    for raw in args.env_for or []:
        if cli_archive.parse_env_for(raw) is None:
            parser.error(f"--env-for {raw!r}: atteso CARTELLA=AMBIENTE")
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
    _attach_parent_console(argv)
    _guard_std_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    _check_arguments(parser, args)
    if args.version:
        print(f"qtRequestory {__version__}")
        return 0
    if args.selftest_noise_guard:  # before any config, path or log (noise_guard.selftest)
        from qtrequestory.officina.compare.noise_guard import selftest
        return selftest()

    paths = _resolve_paths(args.config)
    config = load_config(paths.config_file)
    archive_mode = args.archivio is not None or args.import_path is not None
    gui = not (args.sync or args.index or args.find or args.task or archive_mode)
    configure_logging(paths, headless=not gui, level=config.log_level)

    if args.sync or args.index or args.find or archive_mode:
        # ONLY mirror_root, not the full validate(): an emptied/relative
        # mirror_root (Minor M3) must stop things here — letting --sync run
        # against it once wrote into the live index instead of the mirror the
        # user actually meant — but a bad log_level or a malformed schedule
        # fall back silently already (see validate's own comments) and must
        # keep doing that: none of --sync/--index/--find depend on either,
        # and gating on them turned an unrelated typo into a hard refusal of
        # the scheduled --sync (fix round 1). --find reaches this too: its
        # index lives under mirror_root (Config.index_path) even though it
        # never touches the network.
        problems = mirror_root_errors(config)
        if problems:
            for problem in problems:
                print(f"Errore di configurazione: {problem}")
            return EXIT_CONFIG_ERROR

    if args.sync:
        base_sink = LoggingSink(sync_logger())
        job_sink = _dry_run_sink(base_sink, config) if args.dry_run else base_sink
        return _run_job(
            lambda sink, cancel: run_sync_job(
                config, envs=args.env, force=args.force, dry_run=args.dry_run, sink=sink, cancel=cancel),
            sink=job_sink,
        )
    if args.index:
        return _run_job(lambda sink, cancel: run_index_job(
            config, envs=args.env, full_rebuild=args.rebuild, sink=sink, cancel=cancel))
    if args.find:
        return _run_find(parser, args, config)
    if args.task:
        return _run_task(args.task, config)
    if args.archivio is not None:
        return cli_archive.run_archivio(config, args.archivio)
    if args.import_path is not None:
        return _run_import(args, config)
    return _start_gui(paths)


def _run_import(args: argparse.Namespace, config: Config) -> int:
    pairs = [cli_archive.parse_env_for(raw) for raw in args.env_for or []]
    cancel = CancelToken()
    with _sigint_cancels(cancel):
        return cli_archive.run_import(
            config, args.import_path, [p for p in pairs if p is not None],
            delete_originals=args.delete_originals, cancel=cancel,
            run_job=lambda job: _run_job(job),
        )


def _resolve_paths(config_override: str | None) -> AppPaths:
    """The app directory, with ``--config`` pointing ``config_file`` elsewhere."""
    paths = app_paths()
    if config_override:
        paths = dataclasses.replace(paths, config_override=Path(config_override))
    return paths


# ------------------------------------------------------------ sync / index ---


def _dry_run_sink(base: EventSink, config: Config) -> EventSink:
    """Wrap ``base`` so ``--sync --dry-run`` also lists what it would fetch.

    The log sink writes nothing for ``FileSkipped`` (too chatty for
    ``sync.log``, see ``LoggingSink``): a dry run leaves only the listing line,
    one "anteprima" line per env and the "anteprima della sincronizzazione"
    summary there — not which files it would fetch (Minor P1). The file list
    is printed here, on the CLI side, like the old script did; ``base`` still
    gets every event so ``sync.log`` reads the same as before.
    """
    def sink(ev: object) -> None:
        if isinstance(ev, FileSkipped) and ev.reason == "dry-run":
            day = daily.day_from_name(ev.name)
            dest = daily.local_path(config.mirror_root, ev.env, day) if day is not None else "?"
            print(f"[dry-run] scaricherei {ev.name} ({format_size(ev.size)}) -> {dest}")
        base(ev)
    return sink


def _run_job(job: Callable[[EventSink, CancelToken], JobReport], *, sink: EventSink | None = None) -> int:
    """Run a core job with the headless sink, honouring Ctrl+C.

    The signal handler only sets the token: the job then unwinds through its own
    cancellation points, which is what releases the process lock and leaves the
    index consistent. Killing it mid-write would not.

    An unknown environment (``UnknownEnvironment``) is a config problem, not a
    job failure: printed and exit 2, same as the ``validate`` gate in
    ``main``, distinct from a job that ran and failed.

    Any OTHER exception is logged to ``sync.log`` with its traceback and
    turned into exit code 1, never re-raised: this runs from an hourly
    scheduled task as a windowed (``console=False``) exe, where an unhandled
    exception would surface as a PyInstaller crash dialog nobody is there to
    dismiss, leaving the process stuck and the next trigger silently dropped.
    """
    cancel = CancelToken()
    sink = sink if sink is not None else LoggingSink(sync_logger())
    with _sigint_cancels(cancel):
        try:
            return job(sink, cancel).exit_code
        except KeyboardInterrupt:  # no handler could be installed (not the main thread)
            cancel.cancel()
            return EXIT_CANCELLED
        except UnknownEnvironment as e:
            print(f"Errore: {e}")
            return EXIT_CONFIG_ERROR
        except Exception:
            sync_logger().exception("eccezione non gestita durante l'esecuzione del job")
            return EXIT_ERRORS


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
    try:
        config.require_env(env)
    except UnknownEnvironment as e:
        print(f"Errore: {e}")
        return EXIT_CONFIG_ERROR
    day_to = _parse_day(parser, args.day_to) if args.day_to else date.today()
    window = args.days if args.days is not None else config.default_window_days
    day_from = _parse_day(parser, args.day_from) if args.day_from else day_to - timedelta(days=window)

    fdi = args.fdi.lower() if args.fdi else None
    key = args.template_key.upper() if args.template_key else None
    print(f"cerco in {env} dal {day_from} al {day_to}: fdi={fdi or '*'} key={key or '*'}")

    index = facade.IndexService(lambda: config)
    hits = index.search(SearchQuery(env=env, fdi_prefix=fdi, template_key=key,
                                    day_from=day_from, day_to=day_to))
    # Searching by FDI alone: the entry with the most documents is the one
    # holding the whole pratica (see ``pick_best``). With an explicit key the
    # user has already said which entry they want, so the query order stands.
    hit, others = pick_best(hits, prefer_most_documents=bool(fdi and not key))
    if hit is None:
        print(NOTHING_FOUND)
        # Unlike the legacy script, --find reads an index rather than the files
        # themselves: "nothing found" on an environment that was never indexed
        # would be a lie, so say which of the two it is.
        if index.coverage(env) is None:
            print(NOT_INDEXED.format(env=env))
        return EXIT_ERRORS

    extract = facade.ExtractService(lambda: config)
    text = extract.pretty_json(index.read_body(hit))
    if args.out:
        out = Path(args.out)
        extract.save_as(out, text)
    else:
        out = extract.write_temp_file(hit, text)

    # Two spaces before the parenthesis, exactly as the legacy script printed it.
    # A non-UTF-8 header comes back with surrogates: print() would choke on them.
    name = hit.name.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    print(f"trovato in {hit.file_path.name}: {name}.json  "
          f"(requestDate {hit.request_date or '?'}, {_documents(hit)} documenti)")
    _print_others(others)
    print(f"scritto: {out}")
    if not args.no_open:
        print(f"aperto {_EDITOR_LABEL[extract.open_in_editor([out])]}")
    return 0


#: ``ExtractApi.open_in_editor`` answers "editor"/"default"; the user reads
#: Italian. Not "Notepad++" like the legacy script said: the editor is
#: configurable, and naming the wrong program is worse than naming none.
_EDITOR_LABEL = {"editor": "nell'editor", "default": "con l'app predefinita"}


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


def scheduler_service(config: Config) -> facade.SchedulerService:
    """Built through a function so tests can substitute a fake ``schtasks``.

    ``config`` is the one ``main`` already loaded (``--config`` included), so
    ``--task install`` registers the schedule the user saved in Impostazioni
    instead of a second, hard-coded one.
    """
    return facade.SchedulerService(config_source=lambda: config)


def _run_task(action: str, config: Config) -> int:
    service = scheduler_service(config)
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
