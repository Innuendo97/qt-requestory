"""The Officina's text questions (a name, a note) have Italian buttons: Qt's
static ``QInputDialog.getText`` shows "OK" / "Cancel" because the app loads no
Qt translation."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QInputDialog, QPlainTextEdit, QPushButton

from qtrequestory.ui import strings
from qtrequestory.ui.pages import officina_dialogs


@pytest.mark.parametrize("multiline", [False, True])
def test_the_text_question_has_italian_buttons(qtbot, multiline):
    box = officina_dialogs.input_box(None, "Nuova iniziativa", "Nome:", "bozza", multiline=multiline)
    qtbot.addWidget(box)
    box.show()
    labels = {b.text().replace("&", "") for b in box.findChildren(QPushButton)}
    assert labels == {strings.BTN_OK, strings.BTN_CANCEL}
    assert box.textValue() == "bozza"
    assert bool(box.findChildren(QPlainTextEdit)) is multiline


def test_the_answer_is_stripped_and_empty_means_none(monkeypatch):
    answers = iter([("  Iniziativa di prova  ", 1), ("   ", 1), ("scartata", 0)])

    def fake_exec(self):
        text, code = next(answers)
        self.setTextValue(text)
        return code

    monkeypatch.setattr(QInputDialog, "exec", fake_exec)
    assert officina_dialogs.ask_text(None, "t", "l") == "Iniziativa di prova"
    assert officina_dialogs.ask_note(None, "t", "l") is None
    assert officina_dialogs.ask_text(None, "t", "l", "x") is None
