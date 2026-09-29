"""The dropdown panel under the header's sync chip (Officina 2.5, D5).

::

    ┌──────────────────────────────────────────┐
    │ Sincronizzazione                         │
    │ coll                        [aggiornato] │
    │ Ultima sincronizzazione: oggi 09:23      │
    │ ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪ (30 days) │
    │ svil                     [1 giorno perso]│
    │ Ultima sincronizzazione: ieri 18:40      │
    │ Giorni ripuliti dal server prima…        │
    │ ▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪▪           │
    │ ──────────────────────────────────────── │
    │ [Sincronizza ora]  Apri la pagina completa → │
    └──────────────────────────────────────────┘

A ``Qt.Popup``: it closes on a click outside and on Esc, and the focus goes
back where it was. It keeps no state: every row is the Sincronizzazione page's
own badge (:meth:`~.sync_presenter.SyncPresenter.badge`, the same
:func:`~.sync_badge.badge_for` the cards and the chip read), last sync and
30-day coverage, re-read whenever the page publishes a new state. "Sincronizza
ora" starts the page's sync without leaving the current page; the registro,
the automatic sync and the legend stay on the full page, one click away.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoreServices, CoverageDays
from qtrequestory.ui.pages import sync_badge as sb
from qtrequestory.ui.pages.coverage_strip import CoverageStrip
from qtrequestory.ui.pages.sync_format import format_when

__all__ = ["PANEL_WIDTH", "PanelRow", "SyncPanel"]

PANEL_WIDTH = 380
#: The rows' width: the panel's, less its side margins.
ROW_WIDTH = PANEL_WIDTH - 2 * theme.SPACE[3]
#: Gap between the chip's bottom edge and the panel, and from the screen edge.
ANCHOR_GAP = 6
SCREEN_MARGIN = 8


class PanelRow(QWidget):
    """One environment: name and badge, last sync, what to do, the calendar."""

    def __init__(self, env_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.env_name = env_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACE[1], 0, theme.SPACE[1])
        layout.setSpacing(3)
        head = QHBoxLayout()
        self.name_label = QLabel(env_name)
        theme.set_role(self.name_label, "section")
        self.pill = QLabel()
        head.addWidget(self.name_label)
        head.addStretch(1)
        head.addWidget(self.pill)
        layout.addLayout(head)
        self.last_label = QLabel()
        theme.set_role(self.last_label, "muted")
        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.setFixedWidth(ROW_WIDTH)
        self.strip = CoverageStrip()
        for widget in (self.last_label, self.hint_label, self.strip):
            layout.addWidget(widget)

    def set_state(self, badge: sb.Badge, when: str, coverage: CoverageDays | None) -> None:
        self.pill.setText(badge.text)
        self.pill.setProperty("pill", badge.tone)
        self.pill.setToolTip(badge.tooltip)
        theme.repolish(self.pill)
        self.last_label.setText(strings.SYNC_PANEL_LAST.format(when=when))
        hint = sb.hint_for(badge.kind)
        self.hint_label.setText(hint)
        self.hint_label.setVisible(bool(hint))
        # A wrapped label's size hint guesses its width: give it the real height.
        box = self.hint_label.fontMetrics().boundingRect(
            QRect(0, 0, ROW_WIDTH, 10_000), Qt.TextFlag.TextWordWrap, hint)
        self.hint_label.setFixedHeight(box.height())
        self.strip.set_coverage(coverage)
        self.setAccessibleName(strings.SYNC_SUMMARY_ENTRY.format(env=self.env_name, when=badge.text))


class SyncPanel(QFrame):
    """The popup itself; ``page`` is the (hidden) Sincronizzazione page."""

    #: "Apri la pagina completa": the window shows the full page.
    open_page = Signal()

    def __init__(self, services: CoreServices, page: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("syncPanel")
        self.setAccessibleName(strings.SYNC_PANEL_ACCESSIBLE)
        self.setFixedWidth(PANEL_WIDTH)
        self._services = services
        self._page = page
        self._anchor: QWidget | None = None
        self._rows: list[PanelRow] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.setSpacing(theme.SPACE[1])
        title = QLabel(strings.SYNC_PANEL_TITLE)
        theme.set_role(title, "pageTitle")
        layout.addWidget(title)
        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(theme.SPACE[1])
        layout.addLayout(self._rows_layout)
        rule = QFrame()
        rule.setObjectName("syncPanelRule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        actions = QHBoxLayout()
        self.sync_button = QPushButton(strings.SYNC_BTN_NOW)
        theme.set_role(self.sync_button, "primary")
        self.sync_button.setToolTip(strings.SYNC_BTN_NOW_TOOLTIP)
        self.sync_button.clicked.connect(self._sync_now)
        self.page_link = QPushButton(strings.SYNC_PANEL_OPEN_PAGE)
        theme.set_role(self.page_link, "link")
        self.page_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.page_link.setToolTip(strings.SYNC_PANEL_OPEN_PAGE_TOOLTIP)
        self.page_link.clicked.connect(self._open_page)
        actions.addWidget(self.sync_button)
        actions.addStretch(1)
        actions.addWidget(self.page_link)
        layout.addLayout(actions)

        page.state_changed.connect(self._on_state)

    # -- API ---------------------------------------------------------------

    def rows(self) -> list[PanelRow]:
        return list(self._rows)

    def row(self, env_name: str) -> PanelRow | None:
        return next((r for r in self._rows if r.env_name == env_name), None)

    def toggle(self, anchor: QWidget) -> None:
        """Open under ``anchor``, or close when already open."""
        if self.isVisible():
            self.close()
        else:
            self.open_under(anchor)

    def open_under(self, anchor: QWidget) -> None:
        """Re-read the disk (as showing the page would), then drop down."""
        self._anchor = anchor
        if not self._syncing():
            self._page.refresh_cards()  # coverage: a directory listing
        self._page.presenter.emit_summary()  # the chip and this panel, in step
        self._page.probe.check()  # throttled; answers through the page's state
        self.refresh()
        self._place(anchor)
        self.show()
        self.raise_()
        self.activateWindow()
        (self.sync_button if self.sync_button.isEnabled() else self.page_link).setFocus(
            Qt.FocusReason.PopupFocusReason)

    def refresh(self) -> None:
        """One row per enabled environment, from the page's presenter."""
        presenter = self._page.presenter
        envs = presenter.environments()
        if [r.env_name for r in self._rows] != envs:
            for old in self._rows:
                self._rows_layout.removeWidget(old)
                old.hide()
                old.deleteLater()
            self._rows = [PanelRow(env, self) for env in envs]
            for row in self._rows:
                self._rows_layout.addWidget(row)
        for row in self._rows:
            status = self._services.sync.env_status(row.env_name)
            row.set_state(presenter.badge(row.env_name), format_when(status.last_success),
                          presenter.coverage.get(row.env_name))
        running = self._syncing()
        self.sync_button.setText(strings.SYNC_PANEL_RUNNING if running else strings.SYNC_BTN_NOW)
        self.sync_button.setEnabled(not running and self._page.sync_button.isEnabled())
        self._fit()

    # -- internals ---------------------------------------------------------

    def _fit(self) -> None:
        """Height to the rows shown now (a hint appears or goes; top edge stays)."""
        for row in self._rows:  # a hint shown or hidden: the row's own layout first
            row.layout().invalidate()
            row.layout().activate()
        layout = self.layout()
        layout.invalidate()
        layout.activate()
        self.setFixedHeight(layout.sizeHint().height())

    def _syncing(self) -> bool:
        job = getattr(self._page, "sync_job", None)
        return job is not None and job.is_running()

    def _on_state(self, _items: list) -> None:
        if self.isVisible():
            self.refresh()

    def _sync_now(self) -> None:
        self._page.start_sync()
        self.refresh()

    def _open_page(self) -> None:
        self.close()
        self.open_page.emit()

    def _place(self, anchor: QWidget) -> None:
        """Right-aligned under the chip, kept on the screen."""
        corner = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height() + ANCHOR_GAP))
        x, y = corner.x() - self.width(), corner.y()
        screen = anchor.screen()
        if screen is not None:
            area = screen.availableGeometry()
            x = max(area.left() + SCREEN_MARGIN, min(x, area.right() - self.width() - SCREEN_MARGIN))
        self.move(x, y)

    # -- Qt ----------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """A click on the chip that closes the panel must not reopen it."""
        anchor = self._anchor
        if anchor is not None and not self.rect().contains(event.position().toPoint()):
            inside = anchor.rect().contains(anchor.mapFromGlobal(event.globalPosition().toPoint()))
            self.setAttribute(Qt.WidgetAttribute.WA_NoMouseReplay, inside)
        super().mousePressEvent(event)
