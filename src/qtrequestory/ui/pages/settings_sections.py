"""The eight sections of the Impostazioni page, one builder each.

Every builder takes the :class:`~qtrequestory.ui.pages.settings_page.SettingsPage`
being built, creates its section's widgets *as attributes of that page* (the
page and its tests address them as ``page.schedule_every``, ``page.env_table``…),
wires them to the page's slots and returns the section widget the page puts in
its stack. Behaviour lives in the page; this module is layout only.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import REPEAT_EVERY_RANGE, REPEAT_FOR_RANGE
from qtrequestory.ui.env_table import EnvTable
from qtrequestory.ui.pages.archive_summary import ArchiveSummary
from qtrequestory.ui.pages.settings_officina import OfficinaSection
from qtrequestory.ui.pages.settings_widgets import (
    ElidedLabel,
    PathField,
    button,
    form_card,
    form_label,
    hours_spin,
    icon_button,
    muted,
    row,
)
from qtrequestory.ui.theme import Mode

if TYPE_CHECKING:  # pragma: no cover - typing only
    from qtrequestory.ui.pages.settings_page import SettingsPage

__all__ = ["BUILDERS", "KEY_MODES", "THEME_CHOICES", "TIME_FORMAT", "WINDOW_CHOICES"]

#: The three "Periodo predefinito" buttons (same periods as the Ricerca page).
WINDOW_CHOICES = (7, 30, 90)
#: What ``QTimeEdit`` shows and what ``ScheduleSettings.start_time`` stores.
TIME_FORMAT = "HH:mm"
THEME_CHOICES = (
    (Mode.SYSTEM, strings.SETTINGS_THEME_SYSTEM),
    (Mode.LIGHT, strings.SETTINGS_THEME_LIGHT),
    (Mode.DARK, strings.SETTINGS_THEME_DARK),
)
#: ``search/key_mode`` values, in button order.
KEY_MODES = (
    ("exact", strings.SETTINGS_KEY_MODE_EXACT),
    ("contains", strings.SETTINGS_KEY_MODE_CONTAINS),
)


def _section(*cards: QWidget) -> QWidget:
    """The cards of one section, top-aligned."""
    section = QWidget()
    layout = QVBoxLayout(section)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(theme.SPACE[2])
    for card in cards:
        layout.addWidget(card)
    layout.addStretch(1)
    return section


def _segmented(page: SettingsPage, choices, slot) -> tuple[dict, QWidget]:
    """Checkable buttons in one exclusive group, drawn as a segmented control."""
    buttons: dict = {}
    group = QButtonGroup(page)
    group.setExclusive(True)
    for value, label in choices:
        segment = QPushButton(label)
        segment.setCheckable(True)
        segment.clicked.connect(lambda _checked=False, v=value: slot(v))
        group.addButton(segment)
        buttons[value] = segment
    theme.set_segmented(list(buttons.values()))
    return buttons, row(*buttons.values(), spacing=0)


def _folder_button(slot) -> QPushButton:
    return icon_button("folder-open", strings.BTN_OPEN_FOLDER, slot)


# -- the sections ------------------------------------------------------------

def appearance(page: SettingsPage) -> QWidget:
    card, form = form_card(strings.SETTINGS_SECTION_APPEARANCE)
    page.theme_buttons, segments = _segmented(page, THEME_CHOICES, page.set_theme)
    page.theme_note = muted(strings.SETTINGS_THEME_NOTE)
    form.addRow(form_label(strings.SETTINGS_THEME_LABEL),
                row(segments, page.theme_note, stretch_at_end=True, spacing=theme.SPACE[3]))
    page.group_by_fdi = QCheckBox(strings.SETTINGS_GROUP_BY_FDI)
    page.group_by_fdi.toggled.connect(page.on_edited)
    form.addRow(form_label(strings.SETTINGS_RESULTS_LABEL), page.group_by_fdi)
    return _section(card)


def archive(page: SettingsPage) -> QWidget:
    card, form = form_card(strings.SETTINGS_SECTION_ARCHIVE)
    page.mirror_path = PathField()
    page.browse_mirror_button = page.mirror_path.add(button(
        strings.BTN_BROWSE,
        lambda: page.browse_folder(page.mirror_path, strings.SETTINGS_MIRROR_CAPTION)))
    page.open_mirror_button = page.mirror_path.add(_folder_button(page.open_mirror))
    form.addRow(form_label(strings.SETTINGS_MIRROR_LABEL), page.mirror_path)

    page.output_path = PathField(strings.SETTINGS_OUTPUT_DEFAULT)
    page.browse_output_button = page.output_path.add(button(
        strings.BTN_BROWSE,
        lambda: page.browse_folder(page.output_path, strings.SETTINGS_OUTPUT_CAPTION)))
    page.output_default_button = page.output_path.add(
        button(strings.SETTINGS_BTN_OUTPUT_DEFAULT, lambda: page.output_path.setText("")))
    form.addRow(form_label(strings.SETTINGS_OUTPUT_LABEL), page.output_path)

    page.index_label = muted()
    page.rebuild_button = button(strings.SETTINGS_BTN_REBUILD, page.rebuild_index)
    index_row = QWidget()
    layout = QHBoxLayout(index_row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(page.index_label, 1)
    layout.addWidget(page.rebuild_button)
    form.addRow(form_label(strings.SETTINGS_INDEX_LABEL), index_row)
    page.archive_summary = ArchiveSummary(page._services, page._runner, page._window)
    form.addRow(form_label(strings.ARCHIVE_SUMMARY_LABEL), page.archive_summary)
    for path in (page.mirror_path, page.output_path):
        path.changed.connect(page.on_edited)
    return _section(card)


def environments(page: SettingsPage) -> QWidget:
    card, form = form_card(strings.SETTINGS_SECTION_ENVIRONMENTS)
    page.env_table = EnvTable()
    page.env_table.setMinimumHeight(140)
    page.env_table.changed.connect(page.on_edited)
    form.addRow(page.env_table)
    page.add_button = button(strings.BTN_ADD, page.env_table.add_row)
    page.remove_button = button(strings.BTN_REMOVE, page.env_table.remove_selected)
    page.check_button = button(strings.SETTINGS_BTN_CHECK, page.check_environments)
    page.import_button = button(strings.BTN_IMPORT_FILE, page.import_environments)
    form.addRow(row(page.add_button, page.remove_button, page.check_button, page.import_button,
                    stretch_at_end=True))
    page.check_label = QLabel()
    page.check_label.setWordWrap(True)
    page.check_label.hide()
    form.addRow(page.check_label)
    form.addRow(muted(strings.SETTINGS_CHECK_HINT, wrap=True))
    return _section(card)


def automation(page: SettingsPage) -> QWidget:
    """Ora di avvio · Riprova ogni · Ripeti per · al login, and the banner.

    The widgets, not the validation, are what stops an impossible schedule:
    the ranges are the core's own ``REPEAT_*_RANGE``, so the form can never
    even offer a value ``config.validate`` would refuse.
    """
    page.schedule_banner = QFrame()
    page.schedule_banner.setObjectName("settingsBanner")
    page.schedule_banner_label = QLabel()
    page.schedule_banner_label.setWordWrap(True)
    page.schedule_retry_button = button(strings.SETTINGS_BTN_RETRY, page.update_scheduled_task)
    banner = QHBoxLayout(page.schedule_banner)
    banner.setContentsMargins(theme.SPACE[2], theme.SPACE[1], theme.SPACE[1], theme.SPACE[1])
    banner.addWidget(page.schedule_banner_label, 1)
    banner.addWidget(page.schedule_retry_button)
    page.schedule_banner.hide()

    card, form = form_card(strings.SETTINGS_SECTION_AUTOMATION)
    page.schedule_start = QTimeEdit()
    page.schedule_start.setDisplayFormat(TIME_FORMAT)
    page.schedule_start.timeChanged.connect(page.on_edited)
    page.schedule_every = hours_spin(REPEAT_EVERY_RANGE)
    page.schedule_for = hours_spin(REPEAT_FOR_RANGE, special=strings.SETTINGS_SCHEDULE_NO_REPEAT)
    for spin in (page.schedule_every, page.schedule_for):
        spin.valueChanged.connect(page.on_edited)
    # One width for the three boxes, so they line up (the widest is "nessuna ripetizione").
    boxes = (page.schedule_start, page.schedule_every, page.schedule_for)
    width = max(box.sizeHint().width() for box in boxes)
    for box in boxes:
        box.setMinimumWidth(width)
    page.schedule_logon = QCheckBox(strings.SETTINGS_SCHEDULE_LOGON)
    page.schedule_logon.toggled.connect(page.on_edited)
    page.schedule_summary = QLabel()
    page.schedule_summary.setWordWrap(True)

    form.addRow(form_label(strings.SETTINGS_SCHEDULE_START),
                row(page.schedule_start, stretch_at_end=True))
    form.addRow(form_label(strings.SETTINGS_SCHEDULE_EVERY),
                row(page.schedule_every, stretch_at_end=True))
    form.addRow(form_label(strings.SETTINGS_SCHEDULE_FOR),
                row(page.schedule_for, stretch_at_end=True))
    form.addRow(form_label(strings.SETTINGS_SCHEDULE_LOGON_LABEL), page.schedule_logon)
    page.schedule_hint = muted(strings.SETTINGS_SCHEDULE_LOGON_HINT, wrap=True)
    form.addRow(QWidget(), page.schedule_hint)
    form.addRow(form_label(strings.SETTINGS_SCHEDULE_SUMMARY_LABEL), page.schedule_summary)
    return _section(page.schedule_banner, card)


def search(page: SettingsPage) -> QWidget:
    card, form = form_card(strings.SETTINGS_SECTION_SEARCH)
    page.window_buttons, periods = _segmented(
        page, [(d, strings.SETTINGS_WINDOW_DAYS.format(days=d)) for d in WINDOW_CHOICES],
        page.set_window_days)
    form.addRow(form_label(strings.SETTINGS_WINDOW_LABEL), row(periods, stretch_at_end=True))
    page.key_mode_buttons, modes = _segmented(page, KEY_MODES, page.set_key_mode)
    form.addRow(form_label(strings.SETTINGS_KEY_MODE_LABEL), row(modes, stretch_at_end=True))
    return _section(card)


def officina(page: SettingsPage) -> QWidget:
    """Three cards of their own (``settings_officina``): the section is the widget."""
    page.officina_section = OfficinaSection(page.browse_folder)
    page.officina_section.changed.connect(page.on_edited)
    return page.officina_section


def editor(page: SettingsPage) -> QWidget:
    card, form = form_card(strings.SETTINGS_SECTION_EDITOR)
    page.editor_path = PathField(strings.SETTINGS_EDITOR_NONE)
    page.browse_editor_button = page.editor_path.add(
        button(strings.BTN_BROWSE, page.browse_editor))
    page.detect_button = page.editor_path.add(
        button(strings.SETTINGS_BTN_DETECT, page.detect_editor))
    page.editor_path.changed.connect(page.on_edited)
    form.addRow(form_label(strings.SETTINGS_EDITOR_LABEL), page.editor_path)
    return _section(card)


def advanced(page: SettingsPage) -> QWidget:
    card, form = form_card(strings.SETTINGS_SECTION_ADVANCED)
    page.config_path_label = ElidedLabel()
    page.config_path_label.setObjectName("pathField")
    page.config_path_label.setFont(theme.mono_font())
    page.config_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    page.open_config_button = _folder_button(page.open_config_folder)
    form.addRow(form_label(strings.SETTINGS_CONFIG_LABEL),
                row(page.config_path_label, page.open_config_button))
    page.wizard_button = button(strings.SETTINGS_BTN_RERUN_WIZARD, page.rerun_wizard)
    form.addRow(form_label(strings.SETTINGS_WIZARD_LABEL),
                row(page.wizard_button, stretch_at_end=True))
    return _section(card)


#: ``(key, list label, builder)`` in page order; ``show_section`` takes the key.
BUILDERS = (
    ("appearance", strings.SETTINGS_SECTION_APPEARANCE, appearance),
    ("archive", strings.SETTINGS_SECTION_ARCHIVE, archive),
    ("environments", strings.SETTINGS_SECTION_ENVIRONMENTS, environments),
    ("automation", strings.SETTINGS_SECTION_AUTOMATION, automation),
    ("search", strings.SETTINGS_SECTION_SEARCH, search),
    ("officina", strings.SETTINGS_SECTION_OFFICINA, officina),
    ("editor", strings.SETTINGS_SECTION_EDITOR, editor),
    ("advanced", strings.SETTINGS_SECTION_ADVANCED, advanced),
)
