""""Payload e header…": the case's request body and how it is sent.

Two tabs:

* **Payload** — the JSON body (``payload.json``), highlighted, validated as
  you type; OK stays refused while it is not a JSON object. The first save
  keeps the original as ``payload.original.json`` (the model does that).
* **Header e invio** — the generator, the ``correlation_id`` mode, the upload
  link policy, the explicit "no Postman-Token" toggle, and the case's header
  overrides as a two-column table. What is automatic (template_key,
  current_timestamp, correlation_id, Postman-Token) and what comes from the
  Impostazioni profile or the initiative is said in one line under the table.

Nothing is sent from here: the dialog only writes the case (``save_case``) and
its payload (``save_payload``) through ``OfficinaApi``.
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Case, CoreServices, header_problems
from qtrequestory.ui.json_highlighter import JsonHighlighter

__all__ = ["PayloadHeaderDialog", "parse_payload"]

CORRELATION_MODES = (("new", strings.OFFICINA_EDITOR_CORRELATION_NEW),
                     ("source", strings.OFFICINA_EDITOR_CORRELATION_SOURCE),
                     ("fixed", strings.OFFICINA_EDITOR_CORRELATION_FIXED))
LINK_POLICIES = (("remove", strings.OFFICINA_EDITOR_LINKS_REMOVE),
                 ("keep_if_expired", strings.OFFICINA_EDITOR_LINKS_KEEP))


def parse_payload(text: str) -> tuple[dict | None, str]:
    """``(payload, "")`` or ``(None, the problem in Italian)``."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, strings.OFFICINA_EDITOR_JSON_ERROR.format(
            line=exc.lineno, column=exc.colno, message=exc.msg)
    if not isinstance(data, dict):
        return None, strings.OFFICINA_EDITOR_JSON_NOT_OBJECT
    return data, ""


class PayloadHeaderDialog(QDialog):
    """Edit one case's payload and sending options; OK saves both."""

    def __init__(self, services: CoreServices, case: Case, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.OFFICINA_EDITOR_TITLE)
        self._services = services
        self._case = case
        self._original = services.officina.payload(case)

        self.editor = QPlainTextEdit()
        self.editor.setFont(theme.mono_font())
        self.editor.setPlainText(json.dumps(self._original, indent=2, ensure_ascii=False))
        self.highlighter = JsonHighlighter(self.editor.document())
        self.json_state = QLabel()
        self.json_state.setWordWrap(True)
        self.format_button = QPushButton(strings.OFFICINA_EDITOR_FORMAT)

        self.env = QComboBox()
        self.correlation = QComboBox()
        self.correlation_value = QLineEdit(case.correlation_value)
        self.links = QComboBox()
        self.drop_token = QCheckBox(strings.OFFICINA_EDITOR_DROP_TOKEN)
        self.drop_token.setChecked(case.drop_postman_token)
        self.headers = QTableWidget(0, 2)
        self.headers.setHorizontalHeaderLabels([strings.OFFICINA_EDITOR_HEADER_NAME,
                                                strings.OFFICINA_EDITOR_HEADER_VALUE])
        self.headers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.headers.verticalHeader().setVisible(False)
        self.headers.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        theme.set_table_look(self.headers)
        self.add_header = QPushButton(strings.OFFICINA_EDITOR_ADD_HEADER)
        self.remove_header = QPushButton(strings.OFFICINA_EDITOR_REMOVE_HEADER)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setProperty("dot", "bad")
        self.error.setVisible(False)

        self._fill()
        self._build()
        self.editor.textChanged.connect(self._validate_json)
        self.format_button.clicked.connect(self._format)
        self.correlation.currentIndexChanged.connect(self._sync_correlation)
        self.add_header.clicked.connect(lambda: self._add_row("", ""))
        self.remove_header.clicked.connect(self._remove_rows)
        self._validate_json()
        self._sync_correlation()
        self.resize(760, 560)

    # -- construction ------------------------------------------------------

    def _fill(self) -> None:
        cfg = self._services.config.load()
        names = [g.name for g in cfg.officina.generators if g.enabled]
        if self._case.env and self._case.env not in names:
            names.insert(0, self._case.env)  # keep what the case says; generate will refuse it
        self.env.addItems(names)
        if self._case.env in names:
            self.env.setCurrentIndex(names.index(self._case.env))
        for mode, label in CORRELATION_MODES:
            offered = self._case.source_fdi or self._case.correlation == "source"
            if mode == "source" and not offered:
                continue
            self.correlation.addItem(label, mode)
        self.correlation.setCurrentIndex(max(0, self.correlation.findData(self._case.correlation)))
        for policy, label in LINK_POLICIES:
            self.links.addItem(label, policy)
        self.links.setCurrentIndex(max(0, self.links.findData(self._case.link_policy)))
        for name, value in self._case.headers.items():
            self._add_row(name, value)

    def _build(self) -> None:
        payload = QWidget()
        column = QVBoxLayout(payload)
        column.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addWidget(self.json_state, 1)
        row.addWidget(self.format_button)
        column.addLayout(row)

        sending = QWidget()
        form = QFormLayout()
        form.addRow(strings.OFFICINA_EDITOR_ENV, self.env)
        correlation = QHBoxLayout()
        correlation.addWidget(self.correlation)
        correlation.addWidget(self.correlation_value, 1)
        form.addRow(strings.OFFICINA_EDITOR_CORRELATION, correlation)
        form.addRow(strings.OFFICINA_EDITOR_LINKS, self.links)
        form.addRow("", self.drop_token)
        hint = QLabel(strings.OFFICINA_EDITOR_HEADERS_HINT)
        hint.setWordWrap(True)
        theme.set_role(hint, "muted")
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_header)
        buttons.addWidget(self.remove_header)
        buttons.addStretch(1)
        column2 = QVBoxLayout(sending)
        column2.addLayout(form)
        column2.addWidget(self.headers, 1)
        column2.addLayout(buttons)
        column2.addWidget(hint)

        self.tabs = QTabWidget()
        self.tabs.addTab(payload, strings.OFFICINA_EDITOR_PAYLOAD_TAB)
        self.tabs.addTab(sending, strings.OFFICINA_EDITOR_HEADERS_TAB)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                               | QDialogButtonBox.StandardButton.Cancel)
        box.button(QDialogButtonBox.StandardButton.Save).setText(strings.BTN_SAVE)
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.BTN_CANCEL)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self.save_button = box.button(QDialogButtonBox.StandardButton.Save)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.error)
        layout.addWidget(box)

    # -- behaviour ---------------------------------------------------------

    def header_rows(self) -> list[tuple[str, str]]:
        rows = []
        for row in range(self.headers.rowCount()):
            name = (self.headers.item(row, 0) or QTableWidgetItem("")).text().strip()
            value = (self.headers.item(row, 1) or QTableWidgetItem("")).text()
            rows.append((name, value))
        return rows

    def problem(self) -> str:
        """Why the dialog cannot be saved yet ("" when it can)."""
        _payload, error = parse_payload(self.editor.toPlainText())
        if error:
            return error
        # The same rules as the Impostazioni profile and the generator (core).
        rows = [(name, value) for name, value in self.header_rows() if name or value.strip()]
        for problems in header_problems(rows):
            if problems:
                return problems[0]
        if self.correlation.currentData() == "fixed" and not self.correlation_value.text().strip():
            return strings.OFFICINA_EDITOR_FIXED_EMPTY
        return ""

    def save(self) -> str:
        """Write the case and (if changed) the payload; "" or the failure."""
        problem = self.problem()
        if problem:
            return problem
        payload, _error = parse_payload(self.editor.toPlainText())
        case = self._case
        case.env = self.env.currentText()
        case.correlation = self.correlation.currentData()
        case.correlation_value = (self.correlation_value.text().strip()
                                  if case.correlation == "fixed" else "")
        case.link_policy = self.links.currentData()
        case.drop_postman_token = self.drop_token.isChecked()
        case.headers = {name: value for name, value in self.header_rows() if name}
        try:
            self._services.officina.save_case(case)
            if payload != self._original:
                self._services.officina.save_payload(case, payload)
        except (OSError, ValueError) as exc:
            return strings.OFFICINA_EDITOR_SAVE_FAILED.format(reason=exc)
        return ""

    def accept(self) -> None:  # noqa: D102 - save first, close only if it worked
        failure = self.save()
        self.error.setText(failure)
        self.error.setVisible(bool(failure))
        theme.repolish(self.error)
        if not failure:
            super().accept()

    def _validate_json(self) -> None:
        _payload, error = parse_payload(self.editor.toPlainText())
        self.json_state.setText(error or strings.OFFICINA_EDITOR_JSON_OK)
        self.json_state.setProperty("dot", "bad" if error else "ok")
        theme.repolish(self.json_state)
        self.format_button.setEnabled(not error)

    def _format(self) -> None:
        payload, error = parse_payload(self.editor.toPlainText())
        if not error:
            self.editor.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))

    def _sync_correlation(self) -> None:
        self.correlation_value.setVisible(self.correlation.currentData() == "fixed")

    def _add_row(self, name: str, value: str) -> None:
        row = self.headers.rowCount()
        self.headers.insertRow(row)
        self.headers.setItem(row, 0, QTableWidgetItem(name))
        self.headers.setItem(row, 1, QTableWidgetItem(value))
        if not name:
            self.headers.editItem(self.headers.item(row, 0))

    def _remove_rows(self) -> None:
        for row in sorted({i.row() for i in self.headers.selectedIndexes()}, reverse=True):
            self.headers.removeRow(row)
