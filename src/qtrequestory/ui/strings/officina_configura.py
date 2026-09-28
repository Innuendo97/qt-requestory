"""Strings of the Officina setup: the tab's inline card and the wizard's step.

Owned by: release 1.3.2 (task S1). The same form appears in the first-run
wizard (step "Officina", whose own title and buttons are in ``wizard.py``)
and in the Officina tab, where the folder or the generator is missing.
"""

# -- the card in the Officina tab ------------------------------------------------------

#: The card's title; the generation refusal of the core names it too
#: (``officina.service.NO_GENERATOR``): keep the two in step.
OFFICINA_SETUP_TITLE = "Configura l'Officina"
OFFICINA_SETUP_TEXT = (
    "L'Officina genera i documenti sul generatore di documenti e li confronta con il target. "
    "Servono due cose: una cartella locale per iniziative, payload e documenti, e l'indirizzo "
    "del generatore."
)
#: The card over the initiatives: the folder is there, the generator is not.
OFFICINA_SETUP_TEXT_GENERATOR = (
    "Manca il generatore di documenti: senza, i casi non si possono generare. "
    "Le iniziative restano consultabili qui sotto."
)
OFFICINA_SETUP_MORE = "Altre impostazioni…"
OFFICINA_SETUP_SAVED = "Officina configurata."

# -- the form (card and wizard) --------------------------------------------------------

OFFICINA_SETUP_FOLDER_LABEL = "Cartella dell'Officina:"
OFFICINA_SETUP_FOLDER_PLACEHOLDER = "es. C:\\Lavoro\\Officina"
OFFICINA_SETUP_FOLDER_ADVICE = (
    "Una cartella sul tuo PC, fuori da ogni repository e non sincronizzata nel cloud."
)
OFFICINA_SETUP_GENERATORS_LABEL = "Generatore:"
OFFICINA_SETUP_DEFAULT_LABEL = "Predefinito:"
#: The generators come from the environments.json next to the executable.
OFFICINA_SETUP_FROM_SIDECAR = (
    "Generatore proposto dal file environments.json: controllalo e conferma."
)
OFFICINA_SETUP_CONFIGURED = "Generatori già configurati: modificali o aggiungine altri."
#: The shape of a document generator's address: the placeholder of an empty
#: URL cell (wizard, card and Impostazioni). ``<host>`` is the user's to fill.
OFFICINA_SETUP_URL_PLACEHOLDER = "https://<host>/rest/api/submit-job/documentGenerator"
OFFICINA_SETUP_EMPTY_HINT = (
    "Scrivi un nome (es. svil) e l'indirizzo: "
    "https://<host>/rest/api/submit-job/documentGenerator"
)
OFFICINA_SETUP_NEED_FOLDER = "Indica la cartella dell'Officina."
OFFICINA_SETUP_NEED_GENERATOR = "Aggiungi almeno un generatore attivo."
