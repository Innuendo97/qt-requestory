"""Strings of the Sincronizzazione page (auto-sync card, env cards, log).

Owned by: Task 11, redesigned by Task 17.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).

The wording of the *registro* is deliberately absent: those lines are produced
by the core's own ``LoggingSink`` so the panel reads exactly like ``sync.log``
(see ``ui/pages/sync_format.py``). Duplicating them here would let the two
drift apart. For the same reason sizes ("80,4 MB") are worded by the core's
``events.format_size``, which the page reuses.
"""

SYNC_TITLE = "Sincronizzazione"

# -- automatic synchronisation card (top of the page) ------------------------

#: The switch's accessible name, and the title while the status is unknown.
SYNC_AUTO_TITLE = "Sincronizzazione automatica"
SYNC_AUTO_TITLE_ON = "Sincronizzazione automatica attiva"
SYNC_AUTO_TITLE_OFF = "Sincronizzazione automatica non attiva"
#: Shown under the title until ``scheduler.status()`` answers (it runs schtasks).
SYNC_AUTO_CHECKING = "verifica in corso…"
#: Under the title when no task is registered.
SYNC_AUTO_OFF_HINT = "L'archivio locale si aggiorna solo quando sincronizzi a mano"
#: {next} = the localised next-run string schtasks prints.
SYNC_AUTO_NEXT = "prossimo avvio: {next}"
#: {last} = the localised last-run string, {result} = its exit code.
SYNC_AUTO_LAST = "ultima esecuzione: {last} (esito {result})"
SYNC_AUTO_LAST_NONE = "ultima esecuzione: mai"
SYNC_AUTO_SEP = " · "
SYNC_AUTO_EDIT = "Modifica orari"
SYNC_AUTO_EDIT_TOOLTIP = "Apre Impostazioni › Sincronizzazione automatica"
#: {path} = the executable the registered task points at.
SYNC_AUTO_EXE_MISMATCH = "L'attività pianificata avvia un eseguibile diverso ({path})."
SYNC_AUTO_EXE_UPDATE = "Aggiorna"
SYNC_AUTO_UNSTABLE_TITLE = "Posizione poco stabile"
#: {reason} = why this location is a bad place to schedule from.
SYNC_AUTO_UNSTABLE_TEXT = (
    "{reason}\n\nL'attività pianificata smetterà di funzionare se l'eseguibile viene "
    "spostato o cancellato. Vuoi registrarla lo stesso?"
)
SYNC_AUTO_UNSTABLE_OK = "Registra lo stesso"
#: {error} = the message of the SchedulerError.
SYNC_AUTO_FAILED = "Impossibile aggiornare l'attività pianificata: {error}"
#: {error} = why ``scheduler.status()`` failed.
SYNC_AUTO_STATUS_FAILED = "Impossibile leggere lo stato dell'attività pianificata: {error}"
#: A register/unregister refused because Impostazioni is updating the task.
SYNC_AUTO_REFUSED = (
    "L'attività pianificata è già in aggiornamento da Impostazioni: "
    "la modifica non è stata applicata."
)
SYNC_AUTO_RETRY = "Riprova"

# -- the sync button ---------------------------------------------------------

SYNC_BTN_NOW = "Sincronizza ora"
SYNC_BTN_NOW_TOOLTIP = "Scarica i file mancanti da tutti gli ambienti abilitati"
SYNC_MENU_ALL = "Tutti gli ambienti"
#: {env} = the name of one environment.
SYNC_MENU_ONLY = "Solo {env}"
SYNC_MENU_DRY_RUN = "Anteprima (senza scaricare)"

# -- coverage banners (days with calls that are not in the archive) ---------
#
# The server keeps its daily files until a manual purge: a day that is not
# local is either still there (pending) or was purged first (lost).

#: {env} = environment, {dates} = one dd/MM/yyyy.
SYNC_PENDING_ONE = "{env}: 1 giorno ({dates}) è ancora sul server ma non è stato scaricato."
#: {env} = environment, {n} = days (2 or more), {dates} = dd/MM/yyyy list.
SYNC_PENDING_MANY = (
    "{env}: {n} giorni ({dates}) sono ancora sul server ma non sono stati scaricati."
)
#: {env} = environment, {dates} = one dd/MM/yyyy.
SYNC_LOST_ONE = (
    "{env}: 1 giorno ({dates}) è stato ripulito dal server prima di essere scaricato: "
    "non recuperabile."
)
#: {env} = environment, {n} = days (2 or more), {dates} = dd/MM/yyyy list.
SYNC_LOST_MANY = (
    "{env}: {n} giorni ({dates}) sono stati ripuliti dal server prima di essere scaricati: "
    "non recuperabili."
)
#: {n} = dates not listed after the first few.
SYNC_MISSING_MORE = " e altri {n}"
SYNC_MISSING_DATES_SEP = ", "

# -- env cards ---------------------------------------------------------------

SYNC_BADGE_FRESH = "aggiornato"
SYNC_BADGE_STALE = "da aggiornare"
SYNC_BADGE_QUEUED = "in attesa"
SYNC_BADGE_RUNNING = "in corso"
#: {n} = days still on the server that are not local (1 or more).
SYNC_BADGE_PENDING = "{n} da scaricare"
SYNC_BADGE_LOST_ONE = "1 giorno perso"
#: {n} = days purged by the server before they were downloaded (2 or more).
SYNC_BADGE_LOST = "{n} giorni persi"
SYNC_BADGE_UNREACHABLE = "non raggiungibile"
SYNC_BADGE_ERRORS = "errori"
SYNC_BADGE_NEVER = "mai sincronizzato"

SYNC_CARD_LAST_LABEL = "Ultima sincronizzazione"
SYNC_CARD_ARCHIVE_LABEL = "Archivio locale"
SYNC_CARD_INDEX_LABEL = "Indice"
#: {when} = "oggi 11:23"; followed by SYNC_CARD_DOWNLOADED* when known.
SYNC_CARD_LAST = "{when}"
SYNC_CARD_DOWNLOADED_ONE = " · 1 file scaricato"
#: {n} = files the last sync downloaded (2 or more; none says nothing).
SYNC_CARD_DOWNLOADED = " · {n} file scaricati"
#: {days} = SYNC_DAYS*, {size} = "3,9 GB", {first} = dd/MM/yyyy of the oldest day.
SYNC_CARD_ARCHIVE = "{days} · {size} · dal {first}"
SYNC_CARD_ARCHIVE_EMPTY = "nessun file"
SYNC_DAYS_ONE = "1 giorno"
#: {n} = a number of days (0 or 2+).
SYNC_DAYS = "{n} giorni"
#: {n} = local files not indexed yet ("file" is invariable, so 1 reads fine).
SYNC_CARD_INDEX_PENDING = "{n} file da indicizzare"

# -- coverage calendar -------------------------------------------------------

#: {day} = dd/MM/yyyy, {what} = one of the SYNC_COVERAGE_* below.
SYNC_COVERAGE_TIP = "{day}: {what}"
SYNC_COVERAGE_PRESENT = "presente"
SYNC_COVERAGE_EMPTY = "nessuna chiamata"
SYNC_COVERAGE_PENDING = "sul server: da scaricare"
SYNC_COVERAGE_LOST = "ripulito dal server prima di essere scaricato"
SYNC_COVERAGE_UNKNOWN = "non verificabile"
SYNC_COVERAGE_WEEKEND = "weekend"
SYNC_COVERAGE_TODAY = "oggi (arriva domani)"
SYNC_COVERAGE_BEFORE = "prima dell'inizio dell'archivio"
SYNC_LEGEND_PRESENT = "log presente"
SYNC_LEGEND_EMPTY = "nessuna chiamata"
SYNC_LEGEND_PENDING = "da scaricare"
SYNC_LEGEND_LOST = "ripulito dal server"
SYNC_LEGEND_UNKNOWN = "non verificabile"
SYNC_LEGEND_WEEKEND = "weekend"
SYNC_LEGEND_TODAY = "oggi (arriva domani)"
SYNC_LEGEND_BEFORE = "prima dell'inizio dell'archivio"

# -- "when" wording, shared by the cards and the status bar summary ----------

#: {time} = HH:mm
SYNC_WHEN_TODAY = "oggi {time}"
SYNC_WHEN_YESTERDAY = "ieri {time}"
#: {date} = dd/MM/yyyy, {time} = HH:mm
SYNC_WHEN_OLDER = "{date} {time}"
SYNC_WHEN_NEVER = "mai"
SYNC_WHEN_UNREACHABLE = "non raggiungibile"

#: {env} = environment name, {when} = one of the four above.
SYNC_SUMMARY_ENTRY = "{env}: {when}"
SYNC_SUMMARY_SEP = " · "

# -- progress (inside the card of the environment being synced) --------------

SYNC_PROGRESS_STARTING = "Avvio…"
#: Status bar during the download; {env} = environment, {i}/{n} = file i of n.
SYNC_STATUS_PROGRESS = "Sincronizzazione {env} {i}/{n}…"
#: Status bar during the index phase of a sync; {i}/{n} = file i of n.
SYNC_STATUS_INDEXING = "Indicizzazione {i}/{n}…"
#: The app-bar chip for an environment being synced right now.
SYNC_CHIP_RUNNING = "in corso"
#: The app-bar chip for an environment waiting for its turn in this run.
SYNC_CHIP_QUEUED = "in attesa"
SYNC_PROGRESS_CANCELLING = "Annullamento…"
#: {name} = file name, {size} = "80,4 MB".
SYNC_PROGRESS_FILE = "{name} ({size})"
SYNC_PROGRESS_ENV = "lettura dell'elenco del server…"
#: {i} = file being transferred, {n} = files in the remote index,
#: {done}/{total} = bytes so far over the announced total.
SYNC_PROGRESS_TOTALS = "file {i} di {n} · {done}/{total}"
#: {i} of {n} files, used while indexing (no byte totals there).
SYNC_PROGRESS_COUNT = "file {i} di {n}"
SYNC_PROGRESS_INDEXING = "Indicizzazione…"
#: {name} = the file being scanned.
SYNC_PROGRESS_INDEXING_FILE = "Indicizzazione · {name}"
#: {rate} = "8,2 MB/s".
SYNC_PROGRESS_RATE = "{rate}"
#: {rate} = "8,2 MB/s", {eta} = "circa 2 min rimanenti".
SYNC_PROGRESS_RATE_ETA = "{rate} · {eta}"

# -- sizes, rates and ETAs ---------------------------------------------------

#: {n} = whole kilobytes with the Italian thousands separator (results table).
SYNC_UNIT_KB = "{n} KB"
#: {size} = "8,2 MB".
SYNC_UNIT_RATE = "{size}/s"

#: {n} = seconds, rounded to five.
SYNC_ETA_SECONDS = "circa {n} s rimanenti"
SYNC_ETA_MINUTES = "circa {n} min rimanenti"
SYNC_ETA_HOURS = "circa {n} h rimanenti"

# -- registro ----------------------------------------------------------------

SYNC_LOG_HEADER = "Registro dell'ultima esecuzione"
#: {part} = the time or the outcome, appended to SYNC_LOG_HEADER.
SYNC_LOG_HEADER_PART = " · {part}"
SYNC_LOG_RUNNING = "in corso"
SYNC_LOG_DONE = "completata"
SYNC_LOG_WARNINGS = "completata con avvisi"
SYNC_LOG_CANCELLED = "annullata"
SYNC_LOG_FAILED = "non riuscita"
#: The core found the lock held and ran nothing.
SYNC_LOG_SKIPPED = "non eseguita"

# -- run outcome (status bar, toast and the line under the cards) ------------

SYNC_DONE = "Sincronizzazione completata"
SYNC_DONE_DRY_RUN = "Anteprima completata: nessun file scaricato"
#: {details} = SYNC_DETAIL_* joined by SYNC_DETAIL_SEP.
SYNC_DONE_PARTIAL = "Completata · {details}"
SYNC_DETAIL_SEP = " · "
#: {env} = the environment that could not be reached.
SYNC_DETAIL_UNREACHABLE = "{env} non raggiungibile"
SYNC_DETAIL_ERROR_ONE = "{env} con 1 errore"
#: {env} = environment, {n} = failed files (2 or more).
SYNC_DETAIL_ERRORS = "{env} con {n} errori"
SYNC_DONE_UNREACHABLE = "Nessun ambiente raggiungibile: riprova quando sei in VPN"
SYNC_CANCELLED = "Sincronizzazione annullata"
#: {error} = the message of the exception the core raised.
SYNC_ERROR = "Sincronizzazione non riuscita: {error}"
#: {problem} = the core's sentence about the log folder (config.mirror_root), through ``lower_first``.
SYNC_REFUSED_MIRROR_ROOT = "Sincronizzazione non avviata: {problem}"

# -- lock held by the scheduled task -----------------------------------------

SYNC_LOCK_HELD = "Sincronizzazione in corso dall'attività pianificata…"
#: The lock is held by this window's own "Importa log" (it copies under the lock).
SYNC_LOCK_IMPORT = "Importazione in corso…"
#: A "Sincronizza ora" the core skipped because our own import held the lock.
SYNC_SKIPPED_IMPORT = "Importazione in corso: sincronizza al termine"

# -- the schedule in words ---------------------------------------------------
#
# Assembled by ``ui/pages/schedule_text.py`` and shown BOTH in the status line
# above and under the Impostazioni fields, so the schedule is described in one
# place only. The pieces are separate constants because the sentence changes
# shape: no repetition window, no logon trigger, or an end time that falls on
# the following day.

#: {time} = the configured start, HH:mm.
SYNC_SCHEDULE_DAILY = "Ogni giorno alle {time}"
#: {end} = when the retry window closes. Used when it repeats every hour.
SYNC_SCHEDULE_REPEAT_HOURLY = ", riprova ogni ora fino alle {end}"
#: {n} = hours between two attempts (2 or more), {end} = when the window closes.
SYNC_SCHEDULE_REPEAT_EVERY = ", riprova ogni {n} ore fino alle {end}"
#: {time} = HH:mm; wraps the end time when the window crosses midnight.
SYNC_SCHEDULE_END_NEXT_DAY = "{time} del giorno dopo"
SYNC_SCHEDULE_LOGON = ", e al login"
# No full stop here: the sentence ends without one because this page shows it
# between " · " separators. Impostazioni and the wizard close it with their own
# string (``SETTINGS_SCHEDULE_SUMMARY``, ``WIZARD_P3_AUTOSYNC_NOTE``).
