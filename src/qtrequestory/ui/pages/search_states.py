"""The Ricerca page's empty states: what the results area says when it has no rows.

One widget, :class:`EmptyState` — an icon, a title, a left-aligned list of
hints, optional clickable rows and buttons — instanced once per state:

``start``        nothing searched yet: what can be pasted, the recent searches,
                 the keyboard shortcuts
``no_results``   the query found nothing: why that may be, [Allarga a 90 giorni]
``no_log``       the environment has nothing indexed: [Vai a Sincronizzazione]
                 (or "L'indice è in ricostruzione" when the mirror IS there)
``no_env``       no environment is enabled: [Apri Impostazioni]

The block is centred on the page but its text is left-aligned: a list of hints
set centred reads as a poem, not as instructions.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import SearchQuery
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.pages.search_recents import Recent

__all__ = ["FULL_FDI_LEN", "WIDE_WINDOW_DAYS", "EmptyState", "SearchStates"]

#: Below this many characters an FDI is treated as a prefix in the hints.
FULL_FDI_LEN = 8
#: The window the "nessun risultato" state offers to widen to.
WIDE_WINDOW_DAYS = 90

#: The width the text block wraps at; wider reads badly on a 1920 px screen.
BLOCK_MAX_WIDTH = 560
ICON_PX = 32


class EmptyState(QWidget):
    """Icon, title, hints, rows, buttons — all optional but the title."""

    def __init__(self, icon_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.icon = QLabel()
        self.title = QLabel()
        self.title.setWordWrap(True)
        theme.set_role(self.title, "section")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        theme.set_role(self.hint, "muted")
        self.hint.setTextFormat(Qt.TextFormat.PlainText)
        self.rows_title = QLabel()
        theme.set_role(self.rows_title, "section")
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(0)
        self._rows: list[QPushButton] = []
        self._buttons_layout = QHBoxLayout()
        self._buttons_layout.setSpacing(8)
        self.buttons: list[QPushButton] = []
        self.footer = QLabel()
        self.footer.setWordWrap(True)
        theme.set_role(self.footer, "muted")
        if icon_name:
            ThemedIcons(self).set(self.icon, icon_name, "muted", ICON_PX)
        self.icon.setVisible(bool(icon_name))

        block = QWidget()
        block.setMaximumWidth(BLOCK_MAX_WIDTH)
        inner = QVBoxLayout(block)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(8)
        for widget in (self.icon, self.title, self.hint):
            inner.addWidget(widget)
        inner.addSpacing(4)
        inner.addWidget(self.rows_title)
        inner.addLayout(self._rows_layout)
        inner.addLayout(self._buttons_layout)
        inner.addWidget(self.footer)
        self._buttons_layout.addStretch(1)
        for widget in (self.rows_title, self.footer):
            widget.setVisible(False)

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(block, 3)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    # -- content ---------------------------------------------------------------

    def set_text(self, title: str, hints: Sequence[str] = ()) -> None:
        self.title.setText(title)
        self.hint.setText("\n".join(f"• {hint}" for hint in hints) if len(hints) > 1
                          else "".join(hints))
        self.hint.setVisible(bool(hints))

    def add_button(self, text: str, slot: Callable[[], object], *,
                   primary: bool = False) -> QPushButton:
        button = QPushButton(text)
        if primary:
            theme.set_role(button, "primary")
        button.clicked.connect(lambda _checked=False: slot())
        self._buttons_layout.insertWidget(len(self.buttons), button)
        self.buttons.append(button)
        return button

    @property
    def button(self) -> QPushButton:
        """The first button (most states have exactly one)."""
        return self.buttons[0]

    def set_rows(self, title: str, rows: Sequence[tuple[str, Callable[[], object]]]) -> None:
        """Clickable rows under a small title (the recent searches)."""
        for button in self._rows:
            self._rows_layout.removeWidget(button)
            button.hide()  # deleteLater is deferred: without this both lists show
            button.deleteLater()
        self._rows = []
        for label, slot in rows:
            button = QPushButton(label)
            theme.set_role(button, "row")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, s=slot: s())
            self._rows_layout.addWidget(button)
            self._rows.append(button)
        self.rows_title.setText(title)
        self.rows_title.setVisible(bool(rows))

    def rows(self) -> list[QPushButton]:
        return list(self._rows)

    def set_footer(self, text: str) -> None:
        self.footer.setText(text)
        self.footer.setVisible(bool(text))

    def text(self) -> str:
        """Everything the state says, for tests and for accessibility tools."""
        parts = [self.title.text(), self.hint.text(), self.footer.text()]
        parts += [row.text() for row in self._rows]
        return "\n".join(part for part in parts if part)


class SearchStates:
    """The four empty states of the page, and how each describes its situation."""

    def __init__(self, *, on_sync: Callable[[], object], on_widen: Callable[[], object],
                 on_settings: Callable[[], object]) -> None:
        self.start = EmptyState("search")
        self.start.set_text(strings.SEARCH_START_TITLE, [
            strings.SEARCH_START_HINT_FDI, strings.SEARCH_START_HINT_KEY,
            strings.SEARCH_START_HINT_NAME])
        self.start.set_footer(strings.SEARCH_START_SHORTCUTS)
        self.no_log = EmptyState("folder-open")
        self.no_log.add_button(strings.SEARCH_EMPTY_NO_LOG_BTN, on_sync, primary=True)
        self.no_results = EmptyState("search")
        self.no_results.add_button(strings.SEARCH_EMPTY_WIDEN_BTN, on_widen)
        self.no_env = EmptyState("settings")
        self.no_env.set_text(strings.SEARCH_EMPTY_NO_ENV_TITLE, [strings.SEARCH_EMPTY_NO_ENV_HINT])
        self.no_env.add_button(strings.SEARCH_EMPTY_NO_ENV_BTN, on_settings, primary=True)

    def widgets(self) -> dict[str, EmptyState]:
        return {"start": self.start, "no_log": self.no_log,
                "no_results": self.no_results, "no_env": self.no_env}

    def set_recents(self, recents: Sequence[Recent],
                    choose: Callable[[Recent], object]) -> None:
        self.start.set_rows(strings.SEARCH_RECENT_TITLE,
                            [(recent.label(), partial(choose, recent)) for recent in recents])

    def describe_no_log(self, env: str, *, rebuilding: bool) -> None:
        """Nothing indexed. "In ricostruzione" when the mirror does have files:
        the index was thrown away (a schema upgrade) and will be rebuilt."""
        if rebuilding:
            self.no_log.set_text(strings.SEARCH_EMPTY_REBUILDING_TITLE,
                                 [strings.SEARCH_EMPTY_REBUILDING_HINT.format(env=env)])
        else:
            self.no_log.set_text(strings.SEARCH_EMPTY_NO_LOG_TITLE.format(env=env),
                                 [strings.SEARCH_EMPTY_NO_LOG_HINT])

    def describe_no_results(self, query: SearchQuery | None, today: date) -> None:
        """The hints describe the query that just ran, not the bar as it is now."""
        day_from = query.day_from if query and query.day_from else today
        day_to = query.day_to if query and query.day_to else today
        fdi = (query.fdi_prefix or "") if query else ""
        hints = [strings.SEARCH_EMPTY_NO_RESULTS_HINT]
        if day_to == today:
            hints.append(strings.SEARCH_EMPTY_HINT_TODAY.format(file=f"{day_to:%Y%m%d}.txt"))
        if 0 < len(fdi) < FULL_FDI_LEN:
            hints.append(strings.SEARCH_EMPTY_HINT_SHORT_FDI)
        if query is not None and query.template_key and query.key_mode == "exact":
            hints.append(strings.SEARCH_EMPTY_HINT_EXACT_KEY)
        self.no_results.set_text(strings.SEARCH_EMPTY_NO_RESULTS_TITLE, hints)
        self.no_results.button.setVisible((day_to - day_from).days + 1 < WIDE_WINDOW_DAYS)
