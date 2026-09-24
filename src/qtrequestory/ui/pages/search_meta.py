"""The line under the Ricerca bar, and the coverage warning under it.

``12 chiamate · 3 FDI · 2 giorni · ordinate dalla più recente | log coll dal …``

The left half describes the results on screen, the right half what can be
searched at all. Neither says anything about *today* any more ("le chiamate
di oggi arrivano domani" is in the tooltip and in the no-results hints): the
line is data only.

The warning — ``2 giorni da scaricare in coll · [Vai a Sincronizzazione]`` —
is the honest part. It counts only the days the core knows had calls and are
not local (:meth:`IndexApi.coverage_days`): ``pending`` ones, still on the
server, and ``lost`` ones, purged before they were downloaded (the banner
turns red when there are any). A 0-byte quiet day or a day nobody can vouch
for is not a hole, and the freshness of the mirror is the Sincronizzazione
page's business.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import Coverage, SearchHit
from qtrequestory.ui.pages.search_icons import ThemedIcons

__all__ = [
    "GapBanner", "MetaLine", "TitleContext", "summary_text",
]

def summary_text(hits: Sequence[SearchHit], tail: str = strings.SEARCH_SUMMARY_TAIL) -> str:
    """"12 chiamate · 1 FDI · 4 giorni · ordinate dalla più recente"."""
    return strings.SEARCH_SUMMARY.format(
        calls=_count(len(hits), strings.SEARCH_SUMMARY_CALLS_ONE, strings.SEARCH_SUMMARY_CALLS_MANY),
        fdis=_count(len({h.fdi for h in hits}), strings.SEARCH_SUMMARY_FDIS_ONE,
                    strings.SEARCH_SUMMARY_FDIS_MANY),
        days=_count(len({h.day for h in hits}), strings.SEARCH_SUMMARY_DAYS_ONE,
                    strings.SEARCH_SUMMARY_DAYS_MANY),
        tail=tail,
    )


def _count(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


class MetaLine(QWidget):
    """Summary of the results, what is searchable, and [Raggruppa per FDI]."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.summary_label = QLabel()
        self.separator = QLabel("|")
        self.coverage_label = QLabel()
        self.coverage_label.setToolTip(strings.SEARCH_COVERAGE_TOOLTIP)
        for label in (self.summary_label, self.separator, self.coverage_label):
            theme.set_role(label, "muted")
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(2, 0, 2, 0)
        self.layout_.setSpacing(10)
        self.layout_.addWidget(self.summary_label)
        self.layout_.addWidget(self.separator)
        self.layout_.addWidget(self.coverage_label)
        self.layout_.addStretch(1)
        self.group_button = QPushButton(strings.SEARCH_GROUP_TOGGLE)
        self.group_button.setCheckable(True)
        self.group_button.setProperty("toggle", True)
        self.group_button.setToolTip(strings.SEARCH_GROUP_TOGGLE_TOOLTIP)
        ThemedIcons(self).set(self.group_button, "text-bullet-list-tree", "muted")
        self.layout_.addWidget(self.group_button)
        self._update_separator()

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)
        self._update_separator()

    def set_coverage(self, env: str, coverage: Coverage | None) -> None:
        if coverage is None:
            self.coverage_label.setText(strings.SEARCH_COVERAGE_NONE.format(env=env))
        else:
            self.coverage_label.setText(strings.SEARCH_COVERAGE.format(
                env=env, first=f"{coverage.first_day:%d/%m/%Y}",
                last=f"{coverage.last_day:%d/%m/%Y}"))
        self._update_separator()

    def _update_separator(self) -> None:
        self.summary_label.setVisible(bool(self.summary_label.text()))
        self.separator.setVisible(bool(self.summary_label.text() and self.coverage_label.text()))


class GapBanner(QFrame):
    """"2 giorni da scaricare in coll · [Vai a Sincronizzazione]".

    Warn tone while every hole is still on the server, bad tone as soon as one
    was purged before it was downloaded.
    """

    go_sync = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("banner", "warn")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.label = QLabel()
        self.button = QPushButton(strings.SEARCH_GAP_BTN)
        self.button.clicked.connect(self.go_sync)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 6, 4)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.button)
        self.setVisible(False)

    def set_gap(self, env: str, pending: Sequence[date] = (),
                lost: Sequence[date] = ()) -> None:
        self.setVisible(bool(pending or lost))
        if not (pending or lost):
            return
        parts, tips = [], []
        if pending:
            parts.append(strings.SEARCH_GAP_PENDING_ONE.format(env=env) if len(pending) == 1
                         else strings.SEARCH_GAP_PENDING_MANY.format(n=len(pending), env=env))
            tips.append(strings.SEARCH_GAP_TOOLTIP_PENDING.format(days=_days(pending)))
        if lost:
            if pending:
                parts.append(strings.SEARCH_GAP_LOST_ONE if len(lost) == 1
                             else strings.SEARCH_GAP_LOST_MANY.format(n=len(lost)))
            else:
                parts.append(strings.SEARCH_GAP_LOST_ONE_ALONE.format(env=env) if len(lost) == 1
                             else strings.SEARCH_GAP_LOST_MANY_ALONE.format(n=len(lost), env=env))
            tips.append(strings.SEARCH_GAP_TOOLTIP_LOST.format(days=_days(lost)))
        self.label.setText(strings.SEARCH_GAP_SEP.join(parts))
        self.setToolTip("\n".join(tips))
        self.setProperty("banner", "bad" if lost else "warn")
        for widget in (self, self.label):  # the label's colour hangs off the frame's
            theme.repolish(widget)


def _days(days: Sequence[date]) -> str:
    return ", ".join(f"{day:%d/%m}" for day in sorted(days))


class TitleContext(QObject):
    """The window title names the selected call — only while Ricerca shows.

    ``set(text)`` remembers "coll · 1a2b3c4d"; the page being hidden (another
    page is on screen) clears the title, being shown again restores it. It
    watches the page's own show/hide events, so the shell needs no hook.
    """

    def __init__(self, page: QWidget, window: object | None) -> None:
        super().__init__(page)
        self._page = page
        self._window = window
        self.text: str | None = None
        page.installEventFilter(self)

    def set(self, text: str | None) -> None:
        self.text = text
        if self._page.isVisible():
            self._apply(text)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if obj is self._page and not event.spontaneous():
            if event.type() == QEvent.Type.Show:
                self._apply(self.text)
            elif event.type() == QEvent.Type.Hide:
                self._apply(None)
        return super().eventFilter(obj, event)

    def _apply(self, text: str | None) -> None:
        # While the application shuts down the page is hidden after the window
        # it would name is already gone.
        if isinstance(self._window, QObject) and not shiboken6.isValid(self._window):
            return
        setter = getattr(self._window, "set_context", None)
        if callable(setter):
            setter(text)
