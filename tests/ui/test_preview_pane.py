"""The preview pane: the body the user actually walks away with.

The hardest requirement of the whole tool lives here — what the pane copies,
saves and opens is the PURE request body from ``extract.pretty_json``: it
starts with ``{\\n    "documents": [``, it carries no wrapper, no header and no
comment, and the accents survive. The 4000-line cap is a *display* device, so
every assertion about Copia/Salva/Apri is made against the FULL text.

The pane is tested standalone, hosted by nothing: it is a plain ``QWidget`` the
Ricerca page embeds, and everything it needs arrives through ``set_hit`` and
the fake ``CoreServices``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QGuiApplication, QShortcut, QTextCursor
from PySide6.QtWidgets import QFileDialog

from qtrequestory.ui import actions, strings
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.pages.preview_pane import MAX_LINES, PreviewPane

BODY_PREFIX = '{\n    "documents": [\n'


@pytest.fixture
def status_messages() -> list[str]:
    return []


@pytest.fixture
def pane(qtbot, fake_core, runner, status_messages) -> PreviewPane:
    widget = PreviewPane(fake_core, runner, status=status_messages.append)
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def hit(fake_core) -> SearchHit:
    return fake_core.index.hits[0]


@pytest.fixture
def other_hit(fake_core) -> SearchHit:
    return fake_core.index.hits[1]


def show(qtbot, pane: PreviewPane, hit: SearchHit | None) -> str:
    """``set_hit`` plus the wait for the worker; returns the full body."""
    pane.set_hit(hit)
    qtbot.waitUntil(lambda: pane.body_text() != "", timeout=5000)
    return pane.body_text()


def big_body(n_documents: int) -> bytes:
    """A body whose pretty form is far past the cap, accents included."""
    documents = [
        {"attachmentId": f"a-{i}", "citta": "Màrio & città", "ndocs": i}
        for i in range(n_documents)
    ]
    return json.dumps({"documents": documents}, ensure_ascii=False).encode("utf-8")


def line_count(text: str) -> int:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return len(lines)


# ------------------------------------------------------------ showing a hit ---

def test_set_hit_shows_the_pure_pretty_json_body(qtbot, pane, hit, fake_core):
    text = show(qtbot, pane, hit)

    assert text.startswith(BODY_PREFIX), repr(text[:40])
    assert pane.editor.toPlainText() == text, "a short body is shown verbatim"
    assert text == fake_core.extract.pretty_json(fake_core.index.read_body(hit))


def test_the_header_names_the_file_the_actions_will_produce(qtbot, pane, hit, fake_core):
    show(qtbot, pane, hit)
    assert pane.name_label.text() == fake_core.extract.output_name(hit)


def test_the_actions_are_disabled_until_a_body_has_arrived(pane, hit):
    assert not pane.copy_button.isEnabled()
    pane.set_hit(hit)
    assert not pane.copy_button.isEnabled(), "still loading: nothing to copy yet"


def test_the_actions_are_enabled_once_the_body_is_there(qtbot, pane, hit):
    show(qtbot, pane, hit)
    for button in (pane.open_button, pane.save_button, pane.copy_button, pane.folder_button):
        assert button.isEnabled()


def test_set_hit_none_shows_the_empty_state(qtbot, pane, hit):
    show(qtbot, pane, hit)

    pane.set_hit(None)

    assert pane.body_text() == ""
    assert pane.editor.toPlainText() == ""
    assert pane.editor.placeholderText() == strings.PREVIEW_EMPTY
    assert pane.name_label.text() == ""
    assert not pane.copy_button.isEnabled()
    assert not pane.footer.isVisibleTo(pane)


def test_the_body_font_asks_for_cascadia_then_consolas(pane):
    families = pane.editor.font().families()
    assert families[:2] == ["Cascadia Mono", "Consolas"]


def test_the_editor_is_read_only_and_does_not_wrap(pane):
    assert pane.editor.isReadOnly()
    assert pane.editor.lineWrapMode() == pane.editor.LineWrapMode.NoWrap


# ------------------------------------------------------------------ the cap ---

def test_a_long_body_is_capped_on_screen_but_kept_whole_in_memory(qtbot, pane, hit, fake_core):
    fake_core.index.bodies[hit.entry_id] = big_body(1500)

    full = show(qtbot, pane, hit)

    total = line_count(full)
    assert total > MAX_LINES
    assert pane.editor.toPlainText() == "\n".join(full.split("\n")[:MAX_LINES])
    assert pane.editor.blockCount() == MAX_LINES
    assert full.startswith(BODY_PREFIX)


def test_the_footer_says_how_much_was_left_out(qtbot, pane, hit, fake_core):
    fake_core.index.bodies[hit.entry_id] = big_body(1500)

    full = show(qtbot, pane, hit)

    assert pane.footer.isVisibleTo(pane)
    assert pane.footer.text() == strings.PREVIEW_TRUNCATED.format(
        shown="4.000", total=f"{line_count(full):,}".replace(",", ".")
    )


def test_a_short_body_has_no_footer(qtbot, pane, hit):
    show(qtbot, pane, hit)
    assert not pane.footer.isVisibleTo(pane)


def test_copy_puts_the_full_body_on_the_clipboard_not_the_capped_one(qtbot, pane, hit, fake_core):
    fake_core.index.bodies[hit.entry_id] = big_body(1500)
    full = show(qtbot, pane, hit)

    pane.copy_body()

    clipboard = QGuiApplication.clipboard().text()
    assert clipboard == full
    assert line_count(clipboard) > MAX_LINES
    assert "Màrio & città" in clipboard, "accents and & survive the round trip"
    assert clipboard.startswith(BODY_PREFIX)


# ------------------------------------------------------------- four actions ---

def test_copy_reports_the_size_in_the_status_bar(qtbot, pane, hit, status_messages):
    show(qtbot, pane, hit)

    pane.copy_body()

    assert status_messages, "the user must be told the copy happened"
    assert status_messages[-1].startswith(strings.PREVIEW_STATUS_COPIED.split("{")[0])


def test_open_in_editor_writes_the_temp_file_and_hands_it_to_the_opener(
    qtbot, pane, hit, fake_core
):
    full = show(qtbot, pane, hit)

    pane.open_in_editor()

    assert len(fake_core.extract.opened) == 1
    (written,) = fake_core.extract.opened[0]
    assert written.is_file()
    assert written.read_text(encoding="utf-8") == full, "the file is the full body"
    assert written.name == fake_core.extract.output_name(hit)


def test_save_as_writes_the_chosen_file_and_remembers_the_folder(
    qtbot, pane, hit, monkeypatch, tmp_path
):
    full = show(qtbot, pane, hit)
    target = tmp_path / "scelto" / "body.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(target), "")),
    )

    saved = pane.save_as()

    assert saved == target
    assert target.read_text(encoding="utf-8") == full
    assert actions.last_save_dir() == target.parent


def test_save_as_cancelled_writes_nothing(qtbot, pane, hit, monkeypatch, tmp_path):
    show(qtbot, pane, hit)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))

    assert pane.save_as() is None
    assert list(tmp_path.glob("*.json")) == []


def test_save_as_offers_the_output_name_as_the_default(qtbot, pane, hit, monkeypatch, fake_core):
    show(qtbot, pane, hit)
    seen: list[str] = []

    def dialog(parent, caption, directory, filter_):
        seen.append(directory)
        return "", ""

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(dialog))
    pane.save_as()

    assert Path(seen[0]).name == fake_core.extract.output_name(hit)


def test_open_folder_writes_the_body_and_opens_the_output_directory(
    qtbot, pane, hit, fake_core
):
    full = show(qtbot, pane, hit)

    pane.open_folder()

    assert fake_core.extract.folders == [fake_core.extract.output_dir()]
    written = fake_core.extract.output_dir() / fake_core.extract.output_name(hit)
    assert written.read_text(encoding="utf-8") == full


def test_the_actions_do_nothing_without_a_body(pane, fake_core):
    pane.copy_body()
    pane.open_in_editor()
    pane.open_folder()

    assert fake_core.extract.opened == []
    assert fake_core.extract.folders == []


# ----------------------------------------------------------------- workers ---

def test_a_superseded_preview_never_overwrites_the_newer_one(
    qtbot, pane, hit, other_hit, fake_core
):
    """Two rapid selections: the second one wins, whatever the first does."""
    pane.set_hit(hit)
    pane.set_hit(other_hit)

    qtbot.waitUntil(lambda: pane.body_text() != "", timeout=5000)
    expected = fake_core.extract.pretty_json(fake_core.index.read_body(other_hit))
    assert pane.body_text() == expected
    assert pane.name_label.text() == fake_core.extract.output_name(other_hit)

    qtbot.wait(150)  # give a late first result every chance to arrive
    assert pane.body_text() == expected


def test_clearing_the_selection_while_a_body_loads_leaves_the_pane_empty(qtbot, pane, hit):
    """Deselecting is not "supersede": that job is still on its way back."""
    pane.set_hit(hit)
    pane.set_hit(None)

    qtbot.wait(300)

    assert pane.body_text() == ""
    assert pane.editor.toPlainText() == ""
    assert not pane.copy_button.isEnabled()


def test_a_body_that_cannot_be_read_reports_instead_of_showing_half_a_json(
    qtbot, pane, hit, fake_core, status_messages
):
    fake_core.index.set_missing(hit)

    pane.set_hit(hit)
    qtbot.waitUntil(lambda: pane.footer.text() != "", timeout=5000)

    assert pane.body_text() == ""
    assert pane.editor.toPlainText() == ""
    assert strings.PREVIEW_ERROR.split("{")[0] in pane.footer.text()
    assert not pane.copy_button.isEnabled()
    assert status_messages


# --------------------------------------------------------------- keyboard ----

def test_the_pane_binds_the_four_documented_shortcuts(pane):
    bound = {shortcut.key().toString() for shortcut in pane.findChildren(QShortcut)}
    assert {"Ctrl+C", "Ctrl+S", "Ctrl+O", "Ctrl+Shift+O", "Ctrl+F"} <= bound


def test_ctrl_c_without_a_selection_copies_the_whole_body(qtbot, pane, hit):
    full = show(qtbot, pane, hit)
    QGuiApplication.clipboard().setText("vecchio")

    pane.copy_selection_or_body()

    assert QGuiApplication.clipboard().text() == full


def test_ctrl_c_with_a_selection_copies_only_the_selection(qtbot, pane, hit):
    full = show(qtbot, pane, hit)
    assert pane.editor.find("documents"), "the sample body must contain the word"

    pane.copy_selection_or_body()

    copied = QGuiApplication.clipboard().text()
    assert copied == "documents"
    assert copied != full


# --------------------------------------------------------------- find bar ----

def test_the_find_bar_is_hidden_until_it_is_asked_for(pane):
    assert not pane.find_bar.isVisibleTo(pane)


def test_ctrl_f_shows_the_find_bar_and_focuses_it(qtbot, pane, hit):
    show(qtbot, pane, hit)

    pane.show_find()

    assert pane.find_bar.isVisibleTo(pane)


def test_find_next_selects_the_match_in_the_body(qtbot, pane, hit):
    show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("documents")

    assert pane.find_next() is True
    assert pane.editor.textCursor().selectedText() == "documents"


def test_find_wraps_around_at_the_end_of_the_body(qtbot, pane, hit):
    show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("documents")
    pane.editor.moveCursor(QTextCursor.MoveOperation.End)

    assert pane.find_next() is True, "the search must wrap instead of stopping"


def test_a_term_that_is_not_there_reports_and_keeps_the_cursor(qtbot, pane, hit, status_messages):
    show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("zzz-non-esiste")

    assert pane.find_next() is False
    assert status_messages[-1] == strings.PREVIEW_FIND_NOT_FOUND.format(text="zzz-non-esiste")


def test_hiding_the_find_bar_gives_the_focus_back_to_the_body(pane):
    pane.show_find()
    pane.hide_find()
    assert not pane.find_bar.isVisibleTo(pane)


# -------------------------------------------------- the shared action layer ---

def test_copy_text_returns_the_number_of_characters():
    assert actions.copy_text("città") == 5
    assert QGuiApplication.clipboard().text() == "città"


def test_open_output_folder_reuses_an_already_written_file(fake_core, hit):
    """Rewriting would clobber the copy the user may already have open."""
    text = fake_core.extract.pretty_json(fake_core.index.read_body(hit))
    first = fake_core.extract.write_temp_file(hit, text)
    first.write_text("SENTINELLA", encoding="utf-8")

    actions.open_output_folder(fake_core, hit, text)

    assert first.read_text(encoding="utf-8") == "SENTINELLA"
    assert fake_core.extract.folders == [fake_core.extract.output_dir()]


def test_open_hit_in_editor_returns_what_the_opener_reports(fake_core, hit):
    text = fake_core.extract.pretty_json(fake_core.index.read_body(hit))
    assert actions.open_hit_in_editor(fake_core, hit, text) == "default"
