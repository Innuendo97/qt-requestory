"""The Ricerca omnibox: one field for FDI, template key and pasted entry names.

What the user types or pastes turns into *chips* — one for the FDI, one for the
template key — so the two filters are visible at a glance and removable one by
one. These tests drive the widget alone, with real key events where the
behaviour depends on them (Backspace, Enter, Space, Ctrl+V).
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from qtrequestory.ui import strings
from qtrequestory.ui.pages.search_omnibox import SearchOmnibox
from qtrequestory.ui.pages.search_paste import classify_token, parse_pasted_entry
from qtrequestory.ui.pages.search_recents import Recent

FDI = "aaaaaaaa-1111-4222-8333-444444444444"
KEY = "MOD_TEST_A"
CALL = "1a2b3c0200000031"


@pytest.fixture
def box(qtbot) -> SearchOmnibox:
    widget = SearchOmnibox()
    qtbot.addWidget(widget)
    widget.show()
    return widget


# ------------------------------------------------------------ classifying ---

@pytest.mark.parametrize(
    "token, expected",
    [
        (FDI, ("fdi", FDI)),
        (FDI.upper(), ("fdi", FDI)),
        ("aaaaaaaa", ("fdi", "aaaaaaaa")),
        ("1a2b3c4d", ("fdi", "1a2b3c4d")),
        ("7c1e", ("fdi", "7c1e")),
        ("aaaa-", ("fdi", "aaaa-")),
        ("386", ("key", "386")),
        ("CAFE", ("key", "CAFE")),
        ("cafe", ("key", "CAFE")),
        (KEY, ("key", KEY)),
        ("mod_test_a", ("key", KEY)),
        ("transfer", ("key", "TRANSFER")),
        ("2_KEY_ALPHA", ("key", "2_KEY_ALPHA")),
        ("", None),
        ("due parole", None),
        ("a/b", None),
    ],
)
def test_classify_token_tells_an_fdi_from_a_key(token, expected):
    assert classify_token(token) == expected


def test_after_ctrl_k_a_hex_looking_token_is_a_key():
    assert classify_token("1a2b3c4d", prefer_key=True) == ("key", "1A2B3C4D")
    assert classify_token(FDI, prefer_key=True) is None, "a dash is never in a key"


def test_an_uppercase_fdi_in_a_pasted_name_is_lowercased():
    assert parse_pasted_entry(f"{FDI.upper()}_{KEY}_{CALL}.json") == (FDI, KEY)


def test_a_nameless_entry_is_a_key_and_nothing_else():
    """``2_KEY_ALPHA_<call id>`` split on the first underscore gave FDI "2"."""
    assert parse_pasted_entry(f"2_KEY_ALPHA_{CALL}.json") == (None, "2_KEY_ALPHA")
    assert parse_pasted_entry(f"KEY_ALPHA_{CALL}") == (None, "KEY_ALPHA")


# ------------------------------------------------------------------ chips ---

def test_typing_an_fdi_then_space_makes_an_fdi_chip(qtbot, box):
    qtbot.keyClicks(box.edit, "aaaaaaaa")
    qtbot.keyClick(box.edit, Qt.Key.Key_Space)
    assert box.fdi() == "aaaaaaaa"
    assert box.fdi_chip.isVisibleTo(box)
    assert box.edit.text() == ""


def test_typing_a_key_then_enter_makes_a_key_chip_and_submits(qtbot, box):
    qtbot.keyClicks(box.edit, "mod_test_a")
    with qtbot.waitSignal(box.submitted, timeout=1000):
        qtbot.keyClick(box.edit, Qt.Key.Key_Return)
    assert box.template_key() == KEY
    assert box.key_chip.isVisibleTo(box)


def test_text_not_yet_committed_still_counts(qtbot, box):
    """Clicking [Cerca] right after typing must not need Space or Enter."""
    qtbot.keyClicks(box.edit, "7c1e")
    assert box.fdi() == "7c1e"
    assert box.template_key() == ""


def test_pasting_an_entry_name_makes_both_chips(qtbot, box):
    QGuiApplication.clipboard().setText(f"### {FDI}_{KEY}_{CALL}.json")
    box.edit.setFocus()
    qtbot.keyClick(box.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert (box.fdi(), box.template_key()) == (FDI, KEY)
    assert box.edit.text() == ""


def test_pasting_a_nameless_entry_makes_only_a_key_chip(qtbot, box):
    box.set_fdi("bbbb")
    QGuiApplication.clipboard().setText(f"correlationId_vuoto_2_KEY_ALPHA_{CALL}")
    box.edit.setFocus()
    qtbot.keyClick(box.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert box.fdi() == ""
    assert box.template_key() == "2_KEY_ALPHA"


def test_pasting_a_bare_fdi_makes_an_fdi_chip(qtbot, box):
    QGuiApplication.clipboard().setText(f"  {FDI}\n")
    box.edit.setFocus()
    qtbot.keyClick(box.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert box.fdi() == FDI
    assert box.fdi_chip.isVisibleTo(box)


def test_pasting_free_text_is_an_ordinary_paste(qtbot, box):
    QGuiApplication.clipboard().setText("due parole")
    box.edit.setFocus()
    qtbot.keyClick(box.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert box.edit.text() == "due parole"
    assert (box.fdi(), box.template_key()) == ("", "")


def test_a_new_fdi_replaces_the_old_chip(box):
    box.set_fdi("aaaa")
    box.set_fdi("bbbb")
    assert box.fdi() == "bbbb"


def test_backspace_on_empty_text_removes_the_last_chip(qtbot, box):
    box.set_fdi(FDI)
    box.set_template_key(KEY)
    box.edit.setFocus()
    qtbot.keyClick(box.edit, Qt.Key.Key_Backspace)
    assert (box.fdi(), box.template_key()) == (FDI, "")
    qtbot.keyClick(box.edit, Qt.Key.Key_Backspace)
    assert box.fdi() == ""


def test_the_chip_close_button_removes_it(box):
    box.set_template_key(KEY)
    box.key_chip.close_button.click()
    assert box.template_key() == ""
    assert not box.key_chip.isVisibleTo(box)


def test_changed_fires_for_every_chip_and_text_change(qtbot, box):
    with qtbot.waitSignal(box.changed, timeout=1000):
        box.set_fdi("aaaa")
    with qtbot.waitSignal(box.changed, timeout=1000):
        qtbot.keyClicks(box.edit, "x")


def test_escape_clears_the_text_first_then_the_chips(qtbot, box):
    box.set_fdi(FDI)
    box.edit.setFocus()
    qtbot.keyClicks(box.edit, "mod")
    qtbot.keyClick(box.edit, Qt.Key.Key_Escape)
    assert box.edit.text() == ""
    assert box.fdi() == FDI
    qtbot.keyClick(box.edit, Qt.Key.Key_Escape)
    assert box.fdi() == ""


def test_the_placeholder_asks_for_the_missing_filter(box):
    assert box.edit.placeholderText() == strings.SEARCH_OMNIBOX_PLACEHOLDER
    box.set_fdi(FDI)
    assert box.edit.placeholderText() == strings.SEARCH_OMNIBOX_PLACEHOLDER_KEY
    box.set_fdi("")
    box.set_template_key(KEY)
    assert box.edit.placeholderText() == strings.SEARCH_OMNIBOX_PLACEHOLDER_FDI


# ---------------------------------------------------------------- focus ---

def test_focus_fdi_puts_the_fdi_back_into_the_text_selected(qtbot, box):
    box.set_fdi(FDI)
    box.focus_fdi()
    assert box.edit.hasFocus()
    assert box.edit.selectedText() == FDI
    assert box.fdi() == FDI, "still the filter while it is being edited"


def test_focus_key_selects_the_key(qtbot, box):
    box.set_fdi(FDI)
    box.set_template_key(KEY)
    box.focus_key()
    assert box.edit.hasFocus()
    assert box.edit.selectedText() == KEY
    assert box.fdi() == FDI and box.template_key() == KEY


# ------------------------------------------------------------ completer ---

def test_the_key_completer_offers_the_index_keys_by_substring(qtbot, box):
    box.set_template_keys([KEY, "MOD_TEST_B", "KEY_ALPHA"])
    completer = box.edit.completer()
    completer.setCompletionPrefix("test")
    matches = [completer.completionModel().index(i, 0).data()
               for i in range(completer.completionModel().rowCount())]
    assert matches == [KEY, "MOD_TEST_B"]


def test_choosing_a_completion_makes_a_key_chip(qtbot, box):
    box.set_template_keys([KEY, "MOD_TEST_B"])
    box.edit.setFocus()
    box.edit.setText("test_b")
    box.edit.completer().activated.emit("MOD_TEST_B")
    assert box.template_key() == "MOD_TEST_B"
    qtbot.waitUntil(lambda: box.edit.text() == "", timeout=1000)


# --------------------------------------------------------------- recents ---

def test_down_on_an_empty_field_offers_the_recent_searches(qtbot, box):
    recents = [Recent("coll", FDI, "", "exact"), Recent("svil", "", KEY, "contains")]
    box.set_recents(recents)
    menu = box.recent_menu()
    labels = [a.text() for a in menu.actions() if not a.isSeparator() and a.isEnabled()]
    assert labels == [r.label() for r in recents]
    with qtbot.waitSignal(box.recent_chosen, timeout=1000) as blocker:
        menu.actions()[-1].trigger()
    assert blocker.args == [recents[1]]
    menu.deleteLater()


def test_down_opens_the_menu_only_when_the_text_is_empty(qtbot, box):
    box.set_recents([Recent("coll", FDI, "", "exact")])
    box.edit.setFocus()
    qtbot.keyClick(box.edit, Qt.Key.Key_Down)
    assert box.open_menu is not None and box.open_menu.isVisible()
    box.open_menu.close()


# ------------------------------------------------- paste replaces selection ---

def test_ctrl_l_then_pasting_a_new_fdi_replaces_the_old_one(qtbot, box):
    """Reproduced in review: the old FDI stayed in the text and came back on
    the next commit, so the search ran on the FDI the user had replaced."""
    new = "bbbbbbbb-1111-4222-8333-444444444444"
    box.set_fdi(FDI)
    box.focus_fdi()
    QGuiApplication.clipboard().setText(new)
    qtbot.keyClick(box.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert box.edit.text() == ""
    assert box.fdi() == new
    box.commit()
    assert box.fdi() == new


def test_pasting_a_token_into_partly_typed_text_is_an_ordinary_paste(qtbot, box):
    box.edit.setFocus()
    qtbot.keyClicks(box.edit, "MOD_")
    QGuiApplication.clipboard().setText("TEST_A")
    qtbot.keyClick(box.edit, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert box.edit.text() == "MOD_TEST_A"
    box.commit()
    assert box.template_key() == KEY


def test_ctrl_k_then_typing_digits_searches_a_key(qtbot, box):
    box.focus_key()
    qtbot.keyClicks(box.edit, "386")
    assert box.template_key() == "386" and box.fdi() == ""
