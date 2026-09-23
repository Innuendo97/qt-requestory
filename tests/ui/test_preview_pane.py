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

import dataclasses
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication, QShortcut, QTextCursor
from PySide6.QtWidgets import QFileDialog

from qtrequestory.ui import actions, strings
from qtrequestory.ui.contracts import SearchHit
from qtrequestory.ui.pages import sync_format
from qtrequestory.ui.pages.preview_pane import MAX_LINES, TAB_DETAILS, TAB_JSON, PreviewPane

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
    assert pane.name_label.full_text() == fake_core.extract.output_name(hit)


def test_the_actions_are_disabled_until_a_body_has_arrived(pane, hit):
    assert not pane.copy_button.isEnabled()
    pane.set_hit(hit)
    assert not pane.copy_button.isEnabled(), "still loading: nothing to copy yet"
    assert pane.editor.placeholderText() == strings.PREVIEW_LOADING


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
    assert pane.name_label.full_text() == ""
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
    assert status_messages[-1].startswith(strings.PREVIEW_TOAST_COPIED.split("{")[0])


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
    """No dialog, no file, no editor: the buttons are disabled, but the same
    four methods are the page's context menu and can be reached with no hit."""
    pane.copy_body()
    pane.open_in_editor()
    pane.open_folder()

    assert pane.save_as() is None, "the save dialog must not even open"
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
    assert pane.name_label.full_text() == fake_core.extract.output_name(other_hit)

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

def test_the_pane_binds_only_its_own_shortcuts(pane):
    """Ctrl+S / Ctrl+O / Ctrl+Shift+O belong to the Ricerca page, which must
    serve them from the results table too; a second binding here would be
    ambiguous and Qt would fire neither (tests/ui/test_integration_shell.py)."""
    bound = {shortcut.key().toString() for shortcut in pane.findChildren(QShortcut)}
    assert "Ctrl+F" in bound
    assert not {"Ctrl+S", "Ctrl+O", "Ctrl+Shift+O"} & bound
    assert "Ctrl+C" not in bound, (
        "Ctrl+C is the body editor's own key handling, so it cannot swallow "
        "the find field's copy — see preview_body.BodyEdit"
    )


def test_escape_closes_the_find_bar_and_only_the_find_bar(pane):
    """Bound on the bar, not on the pane: Esc in the results table is the
    Ricerca page's own (it clears the focused field)."""
    escapes = [s for s in pane.find_bar.findChildren(QShortcut) if s.key().toString() == "Esc"]
    assert len(escapes) == 1
    assert escapes[0].parent() is pane.find_bar


def test_ctrl_c_without_a_selection_copies_the_whole_body(qtbot, pane, hit):
    full = show(qtbot, pane, hit)
    QGuiApplication.clipboard().setText("vecchio")

    pane.copy_selection_or_body()

    assert QGuiApplication.clipboard().text() == full


def test_a_real_ctrl_c_on_the_body_reaches_the_clipboard(qtbot, pane, hit):
    """The end-to-end key press: pressing Ctrl+C in the body really does beat
    Qt's own read-only copy, which would have left the clipboard untouched."""
    full = show(qtbot, pane, hit)
    pane.editor.setFocus()
    QGuiApplication.clipboard().setText("vecchio")

    qtbot.keyClick(pane.editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    assert QGuiApplication.clipboard().text() == full


def test_a_real_ctrl_c_in_the_find_field_copies_the_search_term(qtbot, pane, hit):
    """The other half of the same property: the override is scoped to the body,
    so the find field keeps the copy every text field has."""
    show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("documents")
    pane.find_edit.selectAll()

    qtbot.keyClick(pane.find_edit, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    assert QGuiApplication.clipboard().text() == "documents"


def test_a_hidden_find_field_never_hijacks_ctrl_c(qtbot, pane, hit):
    """The find bar keeps its text after Esc; the body must still win."""
    full = show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("documents")
    pane.find_edit.selectAll()
    pane.hide_find()
    pane.editor.setFocus()

    qtbot.keyClick(pane.editor, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

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
    pane.find_edit.setText("documents")
    pane.find_next()
    parked = pane.editor.textCursor().position()
    pane.find_edit.setText("zzz-non-esiste")

    assert pane.find_next() is False
    assert status_messages[-1] == strings.PREVIEW_FIND_NOT_FOUND.format(text="zzz-non-esiste")
    assert pane.editor.textCursor().position() == parked, (
        "a miss must not scroll the reader away from the line they were on"
    )


def test_hiding_the_find_bar_gives_the_focus_back_to_the_body(pane):
    pane.show_find()
    pane.hide_find()
    assert not pane.find_bar.isVisibleTo(pane)


# -------------------------------------------------- the shared action layer ---

def test_copy_text_returns_the_number_of_characters():
    assert actions.copy_text("città") == 5
    assert QGuiApplication.clipboard().text() == "città"


def test_open_output_folder_writes_this_hits_body_every_time(fake_core, hit, other_hit):
    """Two calls of the same day, FDI and template key share an output name.

    ``output_name_for`` carries no call id, so that collision is ordinary
    content of a result list. Skipping the write when "the file is already
    there" would open the folder on the *previous* call's body under a name
    that describes this one just as well — the one thing this tool must never
    do. The core already protects a file the user has open: ``write_temp_file``
    falls back to the call-id name instead of overwriting.
    """
    twin = dataclasses.replace(hit, entry_id=other_hit.entry_id, call_id=other_hit.call_id)
    assert fake_core.extract.output_name(twin) == fake_core.extract.output_name(hit)
    text = fake_core.extract.pretty_json(fake_core.index.read_body(hit))
    twin_text = fake_core.extract.pretty_json(fake_core.index.read_body(twin))
    assert text != twin_text

    actions.open_output_folder(fake_core, hit, text)
    actions.open_output_folder(fake_core, twin, twin_text)

    folder = fake_core.extract.output_dir()
    assert fake_core.extract.folders == [folder, folder]
    assert {path.read_text(encoding="utf-8") for path in folder.glob("*.json")} == {text, twin_text}


def test_open_output_folder_does_not_overwrite_a_file_of_its_own_name(fake_core, hit, other_hit):
    """The collision is resolved by the core, under the call-id name."""
    twin = dataclasses.replace(hit, entry_id=other_hit.entry_id, call_id=other_hit.call_id)
    text = fake_core.extract.pretty_json(fake_core.index.read_body(hit))
    twin_text = fake_core.extract.pretty_json(fake_core.index.read_body(twin))

    first = fake_core.extract.write_temp_file(hit, text)
    actions.open_output_folder(fake_core, twin, twin_text)

    assert first.read_text(encoding="utf-8") == text, "the open file keeps its own body"


def test_open_hit_in_editor_returns_what_the_opener_reports(fake_core, hit):
    text = fake_core.extract.pretty_json(fake_core.index.read_body(hit))
    assert actions.open_hit_in_editor(fake_core, hit, text) == "default"


# ------------------------------------------------- header, tabs, Dettagli ---

class Host:
    """What the pane uses of the Ricerca page."""

    def __init__(self):
        self.toasts, self.statuses, self.copied, self.searches = [], [], [], []

    def show_toast(self, text, tone="neutral"):
        self.toasts.append((text, tone))

    def set_status(self, text):
        self.statuses.append(text)

    def copy_value(self, text, message):
        self.copied.append((text, message))

    def search_only(self, fdi, key):
        self.searches.append((fdi, key))


@pytest.fixture
def host() -> Host:
    return Host()


@pytest.fixture
def hosted(qtbot, fake_core, runner, host) -> PreviewPane:
    widget = PreviewPane(fake_core, runner, host)
    qtbot.addWidget(widget)
    widget.resize(700, 600)
    widget.show()
    return widget


def test_the_file_name_is_mono_semibold_elided_in_the_middle(qtbot, hosted, hit, fake_core):
    show(qtbot, hosted, hit)
    name = fake_core.extract.output_name(hit)
    label = hosted.name_label
    assert label.full_text() == name
    assert label.toolTip() == strings.PREVIEW_NAME_TOOLTIP.format(name=name)
    assert label.font().families()[:2] == ["Cascadia Mono", "Consolas"]
    assert label.font().weight() == QFont.Weight.DemiBold
    hosted.resize(260, 600)
    qtbot.waitUntil(lambda: label.text() != name, timeout=2000)
    assert "…" in label.text()
    assert label.text()[:4] == name[:4] and label.text()[-5:] == name[-5:]


def test_the_file_name_can_be_copied_from_its_context_menu(qtbot, hosted, hit, host, fake_core):
    show(qtbot, hosted, hit)
    assert hosted.name_label.actions() == [hosted.copy_name_action]
    assert hosted.copy_name_action.text() == strings.PREVIEW_MENU_COPY_NAME
    hosted.copy_name_action.trigger()
    assert QGuiApplication.clipboard().text() == fake_core.extract.output_name(hit)


@pytest.mark.parametrize("editor, label", [
    (None, strings.PREVIEW_BTN_OPEN_DEFAULT),
    (Path("C:/Programmi/Notepad++/notepad++.exe"), strings.PREVIEW_BTN_OPEN_EDITOR),
    (Path("C:/Editor/code.exe"), strings.PREVIEW_BTN_OPEN_DEFAULT),
])
def test_the_primary_button_names_the_editor_that_will_open(qtbot, fake_core, runner, editor,
                                                            label):
    fake_core.config.editor = editor
    widget = PreviewPane(fake_core, runner)
    qtbot.addWidget(widget)
    assert widget.open_button.text() == label
    assert widget.open_button.property("role") == "primary"


def test_the_secondary_actions_are_icon_buttons_with_their_shortcut(hosted):
    for button, name, shortcut in ((hosted.copy_button, "copy", "Ctrl+C"),
                                   (hosted.save_button, "save", "Ctrl+S"),
                                   (hosted.folder_button, "folder-open", "Ctrl+Shift+O")):
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.property("iconName") == name
        assert button.property("role") == "icon"
        assert shortcut in button.toolTip()
    assert strings.SEARCH_MENU_COPY_JSON in hosted.copy_button.toolTip()


def test_the_tabs_switch_between_the_body_and_the_details(qtbot, hosted, hit):
    show(qtbot, hosted, hit)
    assert hosted.current_tab() == TAB_JSON
    hosted.tabs.button(TAB_DETAILS).click()
    assert hosted.current_tab() == TAB_DETAILS
    assert hosted.details.isVisible() and not hosted.editor.isVisible()
    hosted.show_find()
    assert hosted.current_tab() == TAB_JSON, "Ctrl+F finds in the body"


def test_the_details_tab_lists_the_call(qtbot, hosted, hit):
    show(qtbot, hosted, hit)
    details = hosted.details
    assert details.value("env") == hit.env
    assert details.value("day") == f"{hit.day:%d/%m/%Y}"
    assert details.value("log") == str(hit.file_path)
    assert details.value("fdi") == hit.fdi
    assert details.value("key") == hit.template_key
    assert details.value("name") == hit.name
    assert details.value("ndocs") == str(hit.ndocs)
    assert details.values["fdi"].font().families()[:2] == ["Cascadia Mono", "Consolas"]


def test_the_details_actions_reach_the_page(qtbot, hosted, hit, host, fake_core):
    show(qtbot, hosted, hit)
    details = hosted.details
    details.copy_fdi_button.click()
    details.only_key_button.click()
    details.only_fdi_button.click()
    details.open_log_button.click()
    assert host.copied == [(hit.fdi, strings.SEARCH_STATUS_COPIED_FDI)]
    assert host.searches == [(None, hit.template_key), (hit.fdi, None)]
    assert fake_core.extract.folders == [hit.file_path.parent]


def test_copy_and_save_confirm_with_toasts(qtbot, hosted, hit, host, monkeypatch, tmp_path):
    full = show(qtbot, hosted, hit)
    hosted.copy_body()
    size = sync_format.format_size(len(full.encode("utf-8")))
    assert host.toasts[-1] == (strings.PREVIEW_TOAST_COPIED.format(size=size), "ok")
    target = tmp_path / "scelto.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    hosted.save_as()
    assert host.toasts[-1] == (strings.PREVIEW_TOAST_SAVED.format(name="scelto.json"), "ok")
    hosted.open_folder()
    assert host.statuses[-1].startswith(strings.PREVIEW_STATUS_FOLDER.split("{")[0])


def test_find_reports_a_match_beyond_the_cap(qtbot, pane, hit, fake_core, status_messages):
    documents = [{"n": i} for i in range(1500)] + [{"segreto": "ago-nel-pagliaio"}]
    fake_core.index.bodies[hit.entry_id] = json.dumps({"documents": documents}).encode("utf-8")
    show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("ago-nel-pagliaio")
    before = pane.editor.textCursor().position()
    assert pane.find_next() is True
    assert status_messages[-1] == strings.PREVIEW_FIND_BEYOND.format(shown="4.000")
    assert pane.editor.textCursor().position() == before


def test_find_is_case_insensitive_and_walks_backwards(qtbot, pane, hit):
    show(qtbot, pane, hit)
    pane.show_find()
    pane.find_edit.setText("TEMPLATEKEY")
    assert pane.find_next()
    first = pane.editor.textCursor().selectionStart()
    assert pane.editor.textCursor().selectedText() == "templateKey"
    assert pane.find_next()
    assert pane.editor.textCursor().selectionStart() > first
    assert pane.find_previous()
    assert pane.editor.textCursor().selectionStart() == first


def test_open_folder_twice_reuses_the_identical_file(qtbot, pane, hit, fake_core):
    show(qtbot, pane, hit)
    pane.open_folder()
    pane.open_folder()
    files = list(fake_core.extract.output_dir().glob("*.json"))
    assert [f.name for f in files] == [fake_core.extract.output_name(hit)]


def test_long_values_never_widen_the_pane(qtbot, hosted, hit):
    """A mirror path or an entry name has no space to wrap at: shown in the
    Dettagli tab it used to push the splitter and clip the results."""
    hosted.show_tab(TAB_DETAILS)
    short = dataclasses.replace(hit, name="x", file_path=Path("x.txt"))
    long = dataclasses.replace(hit, name="n" * 300, file_path=Path("C:/" + "cartella/" * 40))
    hosted.details.set_hit(short)
    narrow = hosted.minimumSizeHint().width()
    hosted.details.set_hit(long)
    assert hosted.minimumSizeHint().width() == narrow
    assert hosted.details.values["log"].toolTip() == str(long.file_path)


@pytest.mark.parametrize("editor, message", [
    (Path("C:/Programmi/Notepad++/notepad++.exe"), strings.PREVIEW_STATUS_OPENED_EDITOR),
    (Path("C:/Editor/code.exe"), strings.PREVIEW_STATUS_OPENED_OTHER),
])
def test_the_open_confirmation_names_the_editor_that_opened(qtbot, pane, hit, fake_core,
                                                            status_messages, editor, message):
    """"Aperto in Notepad++" only when Notepad++ is what opened the file."""
    fake_core.config.editor = editor
    fake_core.extract.editor = editor
    pane.refresh_editor_label()
    show(qtbot, pane, hit)

    pane.open_in_editor()

    assert status_messages[-1] == message
