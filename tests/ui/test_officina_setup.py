"""Release 1.3.2 (U3): the Officina in the first-run setup, and its inline card.

The document generator used to be reachable only through Impostazioni. Now:

* the first-run wizard has a fourth step, "Officina" — the folder and the
  generator, prefilled from the ``generators`` of environments.json when it
  carries them — which "Più tardi" skips, leaving the Officina as it was;
* where the folder or the generator is missing, the Officina tab shows a
  setup card with the same two fields and [Salva], writing through
  ``services.config`` exactly as Impostazioni does, and the tab goes on
  without a restart.

Synthetic data only: example.invalid hosts, MOD_TEST keys.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QWizard

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import Environment, GeneratorEndpoint, OfficinaSettings
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.wizard import FirstRunWizard

GEN = GeneratorEndpoint("svil", "https://example.invalid/svil/rest/api/submit-job/documentGenerator")
GEN_COLL = GeneratorEndpoint("coll", "https://example.invalid/coll/rest/api/submit-job/documentGenerator")
ENVS = [Environment("coll", "https://example.invalid/coll/", True)]


def unconfigured(fake_core) -> None:
    """A genuine first run as far as the Officina goes: nothing chosen."""
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(cfg, officina=OfficinaSettings())


def type_generator(form, row: int, generator: GeneratorEndpoint) -> None:
    table = form.generators
    while table.rowCount() <= row:
        table.add_row()
    table.item(row, table.COL_NAME).setText(generator.name)
    table.item(row, table.COL_URL).setText(generator.url)


# ------------------------------------------------------------------ the wizard ---

@pytest.fixture
def wizard(qtbot, fake_core, runner):
    fake_core.config.first_run = True
    unconfigured(fake_core)
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    return widget


def advance_to_officina(wizard, tmp_path: Path) -> None:
    wizard.restart()
    wizard.folder_page.set_path(tmp_path / "logs")
    wizard.next()
    wizard.environments_page.table.set_environments(ENVS)
    wizard.next()
    wizard.next()
    assert wizard.currentPage() is wizard.officina_page


def test_the_officina_step_comes_after_the_others(wizard):
    titles = [wizard.page(pid).step_title() for pid in wizard.pageIds()]
    assert titles == [strings.WIZARD_P1_TITLE, strings.WIZARD_P2_TITLE, strings.WIZARD_P3_TITLE,
                      strings.WIZARD_P4_TITLE]
    assert wizard.officina_page.header.step_label.text() == "Passo 4 di 4"


def test_the_generator_is_prefilled_from_the_sidecar(wizard, fake_core, tmp_path):
    fake_core.config.sidecar_gens = [GEN_COLL, GEN]
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    assert form.generators.generators() == [GEN_COLL, GEN]
    assert form.default_combo.currentText() == "svil"  # the configured default, when offered
    assert form.source_hint.text() == strings.OFFICINA_SETUP_FROM_SIDECAR


def test_without_a_sidecar_an_empty_row_waits_to_be_filled(wizard, tmp_path):
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    assert form.generators.rowCount() == 1 and form.generators.generators() == []
    assert form.source_hint.text() == strings.OFFICINA_SETUP_EMPTY_HINT


def test_fine_saves_the_folder_and_the_generator(wizard, fake_core, tmp_path):
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    form.folder_edit.setText(str(tmp_path / "officina"))
    type_generator(form, 0, GEN)
    assert wizard.officina_page.validatePage()
    wizard.accept()
    saved = fake_core.config.saved[-1].officina
    assert saved.root == tmp_path / "officina" and (tmp_path / "officina").is_dir()
    assert saved.generators == [GEN] and saved.default_generator == "svil"
    assert fake_core.config.saved[-1].environments == ENVS


def test_the_default_is_the_one_chosen(wizard, fake_core, tmp_path):
    fake_core.config.sidecar_gens = [GEN, GEN_COLL]
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    form.folder_edit.setText(str(tmp_path / "officina"))
    form.default_combo.setCurrentText("coll")
    assert wizard.officina_page.validatePage()
    wizard.accept()
    assert fake_core.config.saved[-1].officina.default_generator == "coll"


def test_piu_tardi_finishes_and_leaves_the_officina_unconfigured(wizard, fake_core, tmp_path):
    fake_core.config.sidecar_gens = [GEN]
    advance_to_officina(wizard, tmp_path)
    later = wizard.button(QWizard.WizardButton.CustomButton1)
    assert later.text() == strings.WIZARD_BTN_LATER and later.isVisibleTo(wizard)
    wizard.officina_page.form.folder_edit.setText(str(tmp_path / "officina"))
    later.click()
    assert wizard.result() == int(QWizard.DialogCode.Accepted)
    saved = fake_core.config.saved[-1]
    assert saved.officina == OfficinaSettings()
    assert saved.mirror_root == tmp_path / "logs"  # the other steps are kept
    assert not (tmp_path / "officina").exists()


def test_piu_tardi_is_only_on_the_officina_step(wizard, tmp_path):
    wizard.restart()
    assert not wizard.button(QWizard.WizardButton.CustomButton1).isVisibleTo(wizard)


def test_an_empty_step_changes_nothing(wizard, fake_core, tmp_path):
    advance_to_officina(wizard, tmp_path)
    assert wizard.officina_page.validatePage()
    wizard.accept()
    assert fake_core.config.saved[-1].officina == OfficinaSettings()


@pytest.mark.parametrize("url, why", [
    ("http://example.invalid/gen", "https"),
    ("https://prod.example.invalid/gen", "prod"),
])
def test_an_unsafe_generator_blocks_the_step(wizard, tmp_path, url, why):
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    type_generator(form, 0, GeneratorEndpoint("svil", url))
    assert not wizard.officina_page.validatePage()
    assert why in form.generators.problem_text(0)


def test_a_folder_inside_the_log_mirror_is_refused(wizard, tmp_path):
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    form.folder_edit.setText(str(tmp_path / "logs" / "officina"))
    assert not wizard.officina_page.validatePage()
    assert "log" in form.folder_problem.text() and form.folder_problem.isVisibleTo(form)


def test_a_rerun_shows_what_is_configured_not_the_sidecar(qtbot, fake_core, runner, tmp_path):
    fake_core.config.first_run = False
    fake_core.config.sidecar_gens = [GEN_COLL]
    configured = fake_core.config.config.officina
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    advance_to_officina(widget, tmp_path)
    form = widget.officina_page.form
    assert form.folder_edit.text() == str(configured.root)
    assert form.generators.generators() == configured.generators
    assert form.source_hint.text() == strings.OFFICINA_SETUP_CONFIGURED


def test_a_rerun_skipped_keeps_the_officina_as_it_was(qtbot, fake_core, runner, tmp_path):
    fake_core.config.first_run = False
    configured = fake_core.config.config.officina
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    advance_to_officina(widget, tmp_path)
    widget.officina_page.form.folder_edit.setText("")
    widget.button(QWizard.WizardButton.CustomButton1).click()
    assert fake_core.config.saved[-1].officina == configured


def test_fine_before_the_officina_step_keeps_the_officina(qtbot, fake_core, runner, tmp_path):
    """[Fine] reached without the step (as the older tests drive it): untouched."""
    fake_core.config.first_run = False
    configured = fake_core.config.config.officina
    widget = FirstRunWizard(fake_core, runner)
    qtbot.addWidget(widget)
    widget.accept()
    assert fake_core.config.saved[-1].officina == configured


# -------------------------------------------------------------- the card in the tab ---

class Shell:
    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []
        self.shown: list[str] = []
        self.statuses: list[str] = []

    def set_status(self, text: str) -> None:
        self.statuses.append(text)

    def show_toast(self, text: str, tone: str = "neutral", ms: int = 0, action=None,
                   hint: str = "") -> None:
        self.toasts.append((text, tone))

    def show_page(self, key: str) -> None:
        self.shown.append(key)

    def page(self, key: str):
        return self.settings if key == "settings" else None

    class _Settings:
        def __init__(self) -> None:
            self.sections: list[str] = []

        def show_section(self, key: str) -> None:
            self.sections.append(key)

    settings = _Settings()


def make_page(qtbot, fake_core, runner) -> tuple[OfficinaPage, Shell]:
    shell = Shell()
    shell.settings = Shell._Settings()
    page = OfficinaPage(fake_core, runner, shell)
    qtbot.addWidget(page)
    page.resize(1300, 760)
    page.show()
    return page, shell


def test_no_folder_shows_the_card_prefilled_from_the_sidecar(qtbot, fake_core, runner):
    unconfigured(fake_core)
    fake_core.config.sidecar_gens = [GEN]
    page, _shell = make_page(qtbot, fake_core, runner)
    assert page.view() == "setup"
    card = page.setup_card
    assert card.form.generators.generators() == [GEN]
    assert card.form.folder_edit.text() == ""


def test_saving_the_card_makes_the_tab_usable(qtbot, fake_core, runner, tmp_path):
    unconfigured(fake_core)
    page, shell = make_page(qtbot, fake_core, runner)
    card = page.setup_card
    card.form.folder_edit.setText(str(tmp_path / "officina"))
    type_generator(card.form, 0, GEN)
    seen = []
    page.config_changed.connect(seen.append)

    card.save_button.click()

    officina = fake_core.config.config.officina
    assert officina.root == tmp_path / "officina" and officina.generators == [GEN]
    assert seen and seen[-1].officina == officina
    assert page.view() == "list" and not page.list_setup.isVisibleTo(page)
    assert (strings.OFFICINA_SETUP_SAVED, "ok") in shell.toasts
    ini = fake_core.officina.create_initiative("Acme-Servizi")
    page.show_list()
    assert ini.name in page.list.names()


def test_the_card_needs_a_folder(qtbot, fake_core, runner):
    unconfigured(fake_core)
    page, _shell = make_page(qtbot, fake_core, runner)
    type_generator(page.setup_card.form, 0, GEN)
    page.setup_card.save_button.click()
    assert not fake_core.config.saved
    assert page.setup_card.form.folder_problem.text() == strings.OFFICINA_SETUP_NEED_FOLDER
    assert page.view() == "setup"


def test_the_card_refuses_what_impostazioni_refuses(qtbot, fake_core, runner, tmp_path):
    unconfigured(fake_core)
    page, _shell = make_page(qtbot, fake_core, runner)
    form = page.setup_card.form
    form.folder_edit.setText(str(tmp_path / "officina"))
    type_generator(form, 0, GeneratorEndpoint("prod", GEN.url))
    page.setup_card.save_button.click()
    assert not fake_core.config.saved
    assert "prod" in form.generators.problem_text(0)


def test_a_folder_but_no_generator_shows_the_card_over_the_list(qtbot, fake_core, runner, tmp_path):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[]))
    fake_core.config.sidecar_gens = [GEN]
    page, _shell = make_page(qtbot, fake_core, runner)
    assert page.view() == "list"
    card = page.list_setup
    assert card.isVisibleTo(page)
    assert card.form.folder_edit.text() == str(cfg.officina.root)
    assert card.form.generators.generators() == [GEN]

    card.save_button.click()

    assert fake_core.config.config.officina.generators == [GEN]
    assert not card.isVisibleTo(page)


def test_the_card_over_the_list_needs_a_generator(qtbot, fake_core, runner):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[]))
    page, _shell = make_page(qtbot, fake_core, runner)
    page.list_setup.save_button.click()
    assert not fake_core.config.saved
    assert page.list_setup.form.problem.text() == strings.OFFICINA_SETUP_NEED_GENERATOR


def test_a_generation_refused_for_no_generator_points_to_the_card(qtbot, fake_core, runner,
                                                                  tmp_path):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[]))
    api = fake_core.officina
    ini = api.create_initiative("Acme-Servizi")
    src = tmp_path / "p.json"
    src.write_text(json.dumps({"documents": [{"template": {"templateKey": "MOD_TEST_A"}}]}),
                   encoding="utf-8")
    case = api.case_from_file(ini, src, "MOD_TEST_A")
    _version, result = api.generate(api.load(ini.id), case, "asis")
    assert not result.ok and strings.OFFICINA_SETUP_TITLE in result.reason
    assert "Impostazioni" not in result.reason


def test_altre_impostazioni_opens_the_officina_section(qtbot, fake_core, runner):
    unconfigured(fake_core)
    page, shell = make_page(qtbot, fake_core, runner)
    page.setup_card.more_label.linkActivated.emit("settings")
    assert shell.shown[-1] == "settings" and shell.settings.sections == ["officina"]


def test_impostazioni_saving_a_generator_hides_the_card(qtbot, fake_core, runner):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[]))
    page, _shell = make_page(qtbot, fake_core, runner)
    assert page.list_setup.isVisibleTo(page)
    fake_core.config.config = cfg
    page.on_config_changed(cfg)
    assert not page.list_setup.isVisibleTo(page)


def test_piu_tardi_works_even_with_a_half_typed_generator(wizard, fake_core, tmp_path):
    advance_to_officina(wizard, tmp_path)
    type_generator(wizard.officina_page.form, 0, GeneratorEndpoint("svil", "http://x"))
    wizard.button(QWizard.WizardButton.CustomButton1).click()
    assert wizard.result() == int(QWizard.DialogCode.Accepted)
    assert fake_core.config.saved[-1].officina == OfficinaSettings()


def test_a_failed_save_after_piu_tardi_does_not_skip_the_next_fine(wizard, fake_core, tmp_path,
                                                                   monkeypatch):
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    form.folder_edit.setText(str(tmp_path / "officina"))
    type_generator(form, 0, GEN)
    real_save = fake_core.config.save

    def refuse(_cfg):
        raise OSError("disco pieno")

    monkeypatch.setattr(fake_core.config, "save", refuse)
    monkeypatch.setattr("qtrequestory.ui.wizard.QMessageBox.critical", lambda *_a, **_k: None)
    wizard.button(QWizard.WizardButton.CustomButton1).click()
    assert wizard.result() != int(QWizard.DialogCode.Accepted)

    monkeypatch.setattr(fake_core.config, "save", real_save)
    assert wizard.officina_page.validatePage()
    wizard.accept()
    assert fake_core.config.saved[-1].officina.generators == [GEN]


# ------------------------------------------------------- fix round 1 (review S1) ---

def test_a_card_on_screen_takes_the_values_impostazioni_saved(qtbot, fake_core, runner):
    """I1: the card must not keep stale values its [Salva] would write back."""
    unconfigured(fake_core)
    page, _shell = make_page(qtbot, fake_core, runner)
    assert page.view() == "setup" and page.setup_card.form.generators.generators() == []
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[GEN], default_generator="svil"))
    page.on_config_changed(fake_core.config.config)
    assert page.view() == "setup"
    assert page.setup_card.form.generators.generators() == [GEN]


def test_the_card_over_the_list_takes_the_new_folder(qtbot, fake_core, runner, tmp_path):
    cfg = fake_core.config.config
    fake_core.config.config = dataclasses.replace(
        cfg, officina=dataclasses.replace(cfg.officina, generators=[]))
    page, _shell = make_page(qtbot, fake_core, runner)
    card = page.list_setup
    assert card.isVisibleTo(page)
    moved = tmp_path / "altrove"
    moved.mkdir()
    fake_core.config.config = dataclasses.replace(
        fake_core.config.config,
        officina=dataclasses.replace(fake_core.config.config.officina, root=moved))
    page.on_config_changed(fake_core.config.config)
    assert card.isVisibleTo(page) and card.form.folder_edit.text() == str(moved)
    type_generator(card.form, 0, GEN)
    card.save_button.click()
    assert fake_core.config.config.officina.root == moved


def test_the_url_cell_shows_the_shape_of_a_generator_address(wizard, tmp_path):
    """I2: without a sidecar the empty row says what the URL looks like."""
    from PySide6.QtWidgets import QLineEdit, QStyleOptionViewItem
    advance_to_officina(wizard, tmp_path)
    table = wizard.officina_page.form.generators
    shape = strings.OFFICINA_SETUP_URL_PLACEHOLDER
    assert shape.startswith("https://") and shape.endswith("/rest/api/submit-job/documentGenerator")
    index = table.model().index(0, table.COL_URL)
    delegate = table.itemDelegateForColumn(table.COL_URL)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.text == shape
    editor = delegate.createEditor(table.viewport(), option, index)
    assert isinstance(editor, QLineEdit) and editor.placeholderText() == shape
    table.item(0, table.COL_URL).setText(GEN.url)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.text == GEN.url
    assert "/rest/api/submit-job/documentGenerator" in strings.OFFICINA_SETUP_EMPTY_HINT


def test_no_wording_sends_the_user_to_a_colleague_for_the_sidecar():
    """M1 (U4): the exe comes from GitHub, the generator is typed by hand."""
    for text in (strings.OFFICINA_SETUP_EMPTY_HINT, strings.WIZARD_P2_HINT):
        assert "collega" not in text


def test_the_writable_check_is_public():
    from qtrequestory.ui import wizard_officina_page
    from qtrequestory.ui.folder_check import is_writable
    assert wizard_officina_page.is_writable is is_writable


def test_a_cancelled_wizard_leaves_no_folder_behind(wizard, fake_core, tmp_path):
    """M4: validating the step checks the folder, Annulla leaves nothing."""
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    target = tmp_path / "nuova" / "officina"
    form.folder_edit.setText(str(target))
    type_generator(form, 0, GEN)
    assert wizard.officina_page.validatePage()
    assert not (tmp_path / "nuova").exists()
    wizard.reject()
    assert not (tmp_path / "nuova").exists()


def test_fine_creates_the_folder_it_checked(wizard, fake_core, tmp_path):
    advance_to_officina(wizard, tmp_path)
    form = wizard.officina_page.form
    target = tmp_path / "nuova" / "officina"
    form.folder_edit.setText(str(target))
    type_generator(form, 0, GEN)
    assert wizard.officina_page.validatePage()
    wizard.accept()
    assert target.is_dir() and fake_core.config.saved[-1].officina.root == target


def test_the_generator_table_fits_its_rows(wizard, tmp_path):
    """M5: one row, no empty band; it grows to four rows, then scrolls."""
    advance_to_officina(wizard, tmp_path)
    table = wizard.officina_page.form.generators
    one = table.height()
    table.add_row()
    two = table.height()
    for _ in range(4):
        table.add_row()
    many = table.height()
    assert one < two < many
    rows = table.rowCount()
    assert rows == 6
    visible = table.horizontalHeader().height() + sum(table.rowHeight(r) for r in range(4))
    assert abs(many - visible - 2 * table.frameWidth()) <= 2
    assert table.maximumHeight() == many
