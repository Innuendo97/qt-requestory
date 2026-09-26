"""Officina phase 2: the words and glyphs of the three-way verdict (spec §5.1, §7.1).

Owned by the verdict styling (``ui/pages/officina_verdict_style.py``); the
progress bar, the list and the board read the same constants, so a verdict
is called the same everywhere. Verdict words are fixed by the spec: fatta,
da fare, in corso, regressione, tollerata; the state "da verificare" and the
flag "non risolta"; the classes variabile and rumore have no verdict.
"""

VERDETTO_REGRESSIONE = "regressione"
VERDETTO_NON_RISOLTA = "non risolta"
#: A regressione that is also "non risolta" (R31/R44: the flag on its verdict).
VERDETTO_FLAGGED = "{state} · non risolta"
VERDETTO_DA_FARE = "da fare"
VERDETTO_IN_CORSO = "in corso"
VERDETTO_DA_VERIFICARE = "da verificare"
VERDETTO_FATTA = "fatta"
VERDETTO_TOLLERATA = "tollerata"
VERDETTO_RUMORE = "rumore"
VERDETTO_VARIABILE = "variabile"
#: A difference without a verdict (the AS-IS view: no three-way comparison).
VERDETTO_NESSUNO = "differenza"

# Glyphs shown next to the word (always colour + glyph + word, spec §7.1).
VERDETTO_ICON_REGRESSIONE = "▲"
VERDETTO_ICON_NON_RISOLTA = "○!"
VERDETTO_ICON_DA_FARE = "○"
VERDETTO_ICON_IN_CORSO = "◐"
VERDETTO_ICON_DA_VERIFICARE = "✓?"
VERDETTO_ICON_FATTA = "✓"
VERDETTO_ICON_TOLLERATA = "⊘"
VERDETTO_ICON_RUMORE = "~"
VERDETTO_ICON_VARIABILE = "{x}"
VERDETTO_ICON_NESSUNO = "·"
