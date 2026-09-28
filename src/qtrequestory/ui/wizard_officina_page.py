"""Page 4 of the first-run wizard: the Officina (release 1.3.2, decision U3).

The folder of the Officina and the document generator, with the form the
Officina tab's setup card uses (``pages/officina_setup.SetupForm``): the
generator is prefilled from the ``generators`` of environments.json when the
sidecar carries them, else one empty row waits to be filled.

Optional by design: the wizard's "Più tardi" button (``wizard.py``) finishes
without it, and so does leaving it empty — the Officina then stays exactly as
it was (unconfigured on a first run). Whatever *is* filled in must pass the
same rules as Impostazioni, and the folder must be writable. The check
leaves nothing on disk (Annulla may follow); [Fine] creates the folder.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Config, CoreServices, OfficinaSettings
from qtrequestory.ui.folder_check import is_writable
from qtrequestory.ui.pages.officina_setup import SetupForm
from qtrequestory.ui.wizard_step import WizardStepPage, muted

__all__ = ["OfficinaSetupPage"]

log = logging.getLogger(__name__)


class OfficinaSetupPage(WizardStepPage):
    """Folder + generator; ``base`` is the configuration of the pages before."""

    def __init__(self, services: CoreServices, base: Callable[[], Config], parent=None) -> None:
        super().__init__(4, strings.WIZARD_P4_TITLE, strings.WIZARD_P4_SUBTITLE, parent)
        self._services = services
        self._loaded = False
        self._skipped = False
        self.intro_note = muted(strings.WIZARD_P4_INTRO)
        self.form = SetupForm(base)
        self.body.addWidget(self.intro_note)
        self.body.addSpacing(theme.SPACE[2])
        self.body.addWidget(self.form)
        self.body.addStretch(1)

    def initializePage(self) -> None:
        """Filled once: [Indietro] and [Avanti] keep what the user typed."""
        self._skipped = False
        if not self._loaded:
            self.form.load(self._services.config.load().officina,
                           self._services.config.sidecar_generators())
            self._loaded = True

    def validatePage(self) -> bool:
        # QWizard.done() validates the current page again, "Più tardi" too:
        # a skipped step is neither checked nor created on disk.
        if self._skipped:
            return True
        if self.form.check(require_folder=False, require_generator=False):
            return False
        root = self.form.root()
        # Checked, not kept: Annulla must leave no folder behind; [Fine]
        # creates it (``create_folder``).
        if root is not None and not is_writable(root, keep=False):
            self.form.show_problem(strings.WIZARD_P1_ERROR_NOT_WRITABLE.format(path=root))
            return False
        return True

    # -- what the wizard asks ----------------------------------------------

    def skip(self, skipped: bool = True) -> None:
        """"Più tardi": the Officina is left as it was (``False``: it counts again)."""
        self._skipped = skipped

    def officina(self, base: OfficinaSettings) -> OfficinaSettings:
        """``base`` with this step's answers — or ``base`` itself when the step
        was skipped or never shown."""
        if self._skipped or not self._loaded:
            return base
        return self.form.officina(base)

    def create_folder(self) -> str:
        """[Fine]: create the folder the step checked; the reason when that
        fails, "" otherwise (and when the step was skipped or left empty)."""
        if self._skipped or not self._loaded:
            return ""
        root = self.form.root()
        if root is None:
            return ""
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return strings.OFFICINA_ROOT_FAILED.format(path=root, reason=exc)
        return ""

    def cancel_jobs(self) -> None:
        """Nothing runs in the background here (the wizard asks every page)."""
