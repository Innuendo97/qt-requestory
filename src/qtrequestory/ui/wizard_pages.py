"""The three pages of the first-run wizard, one module each.

They live apart from :mod:`qtrequestory.ui.wizard` for the usual reason a form
splits from its dialog: the wizard owns the *flow* (order, buttons, what Fine
does) and each page owns one question and its validation. A page never saves
anything and never talks to the scheduler beyond asking — it only answers what
the user chose, through small accessors, which is what keeps the finish step in
``wizard.py`` short enough to read in one screen.

Every page holds the ``CoreServices`` bundle rather than a core module, and
asks its questions in ``initializePage`` rather than in ``__init__``: the
services are queried when the page is *shown*, so a test (and the [Indietro]
button) can change the answer and see the page follow.

======================================  =========================================
``wizard_step``                         header (icon, title, "Passo i di 3")
``wizard_folder_page.LogFolderPage``    1. log folder + Notepad++
``wizard_env_page.EnvironmentsPage``    2. environments table
``wizard_automation_page.AutomationPage``  3. scheduled task, old task
======================================  =========================================
"""
from __future__ import annotations

from qtrequestory.ui.wizard_automation_page import TASK_STATUS_JOB, AutomationPage
from qtrequestory.ui.wizard_env_page import REACHABILITY_JOB, EnvironmentsPage, _probe_reachability
from qtrequestory.ui.wizard_folder_page import COUNT_JOB, LogFolderPage

__all__ = [
    "COUNT_JOB", "REACHABILITY_JOB", "TASK_STATUS_JOB", "AutomationPage", "EnvironmentsPage",
    "LogFolderPage", "_probe_reachability",
]
