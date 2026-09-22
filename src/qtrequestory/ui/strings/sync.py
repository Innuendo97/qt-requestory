"""Strings of the Sincronizzazione page (cards, progress strip, log, auto-sync).

Owned by: Task 11.
Only ``UPPER_CASE`` string constants; the package re-exports every public
name defined here, so keep names unique across the strings package (prefix them
with the page, e.g. ``SEARCH_``, ``SYNC_``).

The wording of the *registro* is deliberately absent: those lines are produced
by the core's own ``LoggingSink`` so the panel reads exactly like ``sync.log``
(see ``ui/pages/sync_format.py``). Duplicating them here would let the two
drift apart.
"""

# -- header ------------------------------------------------------------------

SYNC_TITLE = "Sincronizzazione"
SYNC_BTN_NOW = "Sincronizza ora"
SYNC_BTN_NOW_TOOLTIP = "Scarica i file mancanti da tutti gli ambienti abilitati"
SYNC_MENU_ALL = "Tutti gli ambienti"
#: {env} = the name of one environment.
SYNC_MENU_ONLY = "Solo {env}"
SYNC_MENU_DRY_RUN = "Anteprima (senza scaricare)"

# -- cards -------------------------------------------------------------------

SYNC_PILL_FRESH = "● Aggiornato"
SYNC_PILL_STALE = "● Da aggiornare"
SYNC_PILL_UNREACHABLE = "○ Non raggiungibile"
SYNC_PILL_RUNNING = "◐ In corso"
SYNC_PILL_NEVER = "○ Mai sincronizzato"
#: {n} = how many files failed (always 2 or more; one failure has its own line).
SYNC_PILL_ERRORS = "▲ Completato con {n} errori"
SYNC_PILL_ERROR_ONE = "▲ Completato con 1 errore"

#: {when} = "oggi 11:23" / "ieri 15:48" / "21/09/2026 15:48" / "mai".
SYNC_CARD_LAST = "Ultimo sync: {when}"
#: {days} = daily files in the mirror, {size} = "41 MB".
SYNC_CARD_LOCAL = "Log locali: {days} giorni · {size}"
#: {day} = dd/MM/yyyy of the most recent daily file.
SYNC_CARD_LATEST = "Ultimo giorno: {day}"
SYNC_CARD_LATEST_NONE = "Ultimo giorno: —"
SYNC_CARD_INDEX_OK = "Indice: aggiornato"
#: {n} = local files not indexed yet ("file" is invariable, so 1 reads fine).
SYNC_CARD_INDEX_PENDING = "Indice: {n} file da indicizzare"

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

# -- progress strip ----------------------------------------------------------

SYNC_PROGRESS_STARTING = "Avvio…"
SYNC_PROGRESS_CANCELLING = "Annullamento…"
#: {env} = environment, {name} = file name, {size} = "80,4 MB".
SYNC_PROGRESS_FILE = "{env} · {name} ({size})"
#: {env} = the environment whose remote index is being read.
SYNC_PROGRESS_ENV = "{env} · lettura index…"
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

#: {n} = a whole number of bytes.
SYNC_UNIT_B = "{n} B"
#: {n} = a number with an Italian decimal comma ("2,5", "41").
SYNC_UNIT_KB = "{n} KB"
SYNC_UNIT_MB = "{n} MB"
SYNC_UNIT_GB = "{n} GB"
#: {size} = one of the four above.
SYNC_UNIT_RATE = "{size}/s"

#: {n} = seconds, rounded to five.
SYNC_ETA_SECONDS = "circa {n} s rimanenti"
SYNC_ETA_MINUTES = "circa {n} min rimanenti"
SYNC_ETA_HOURS = "circa {n} h rimanenti"

# -- registro ----------------------------------------------------------------

SYNC_LOG_TITLE = "Registro"

# -- run outcome (status bar + the line under the strip) ---------------------

SYNC_DONE = "Sincronizzazione completata."
SYNC_DONE_ERRORS = "Sincronizzazione completata con errori."
SYNC_DONE_UNREACHABLE = "Nessun ambiente raggiungibile: riprova quando sei in VPN."
SYNC_CANCELLED = "Sincronizzazione annullata."
#: {error} = the message of the exception the core raised.
SYNC_ERROR = "Sincronizzazione non riuscita: {error}"

# -- lock held by the scheduled task -----------------------------------------

SYNC_LOCK_HELD = "Sincronizzazione in corso dal task pianificato…"

# -- automatic synchronisation -----------------------------------------------

SYNC_AUTO_TITLE = "Sincronizzazione automatica"
SYNC_AUTO_ON = "Attiva"
SYNC_AUTO_OFF = "Non attiva"
#: {next} = the localised next-run string schtasks prints.
SYNC_AUTO_NEXT = "Prossimo avvio: {next}"
#: {last} = the localised last-run string, {result} = its exit code.
SYNC_AUTO_LAST = "Ultima esecuzione: {last} (esito {result})"
SYNC_AUTO_LAST_NONE = "Ultima esecuzione: mai"
SYNC_AUTO_SEP = " · "
#: {path} = the executable the registered task points at.
SYNC_AUTO_EXE_MISMATCH = "Il task punta a un eseguibile diverso ({path})."
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
