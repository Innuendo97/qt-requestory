"""One environment's card on the Sincronizzazione page.

The card answers, at a glance, the only question the page exists for: *is my
local copy of this environment any good?* — a status pill, when it was last
filled, how much of it there is, and whether the index has caught up.

Two rules from DESIGN-ui shape it:

* **The pill is never red.** An unreachable endpoint is the normal state of
  this tool outside the office VPN, and a red badge would turn "you are not on
  the VPN" into "something is broken". Unreachable and never-synced are grey,
  errors are amber, everything else is the ordinary text colour.
* **Colours are derived, not chosen.** Grey is the palette's ``Mid`` role, so
  the card follows light and dark on its own; only the amber is a literal, and
  it has one value per scheme. :meth:`EnvCard.retune` re-applies it when the
  system switches — the page calls it, so there is one connection for the whole
  page instead of one per card.

The state comes from two different places and neither is enough on its own:
``EnvStatus`` describes the mirror on disk (cheap, no network), while "in
corso", "non raggiungibile" and "completato con N errori" are outcomes of a
run. They are kept apart (:meth:`set_status`, :meth:`set_running`,
:meth:`set_outcome`) and combined by :meth:`_refresh_pill`.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPalette
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import EnvStatus
from qtrequestory.ui.pages.sync_format import format_size, format_when

__all__ = [
    "AMBER_DARK", "AMBER_LIGHT", "EnvCard",
    "PILL_ERRORS", "PILL_FRESH", "PILL_NEVER", "PILL_RUNNING", "PILL_STALE",
    "PILL_UNREACHABLE", "pill_color", "pill_text",
]

PILL_FRESH = "fresh"
PILL_STALE = "stale"
PILL_UNREACHABLE = "unreachable"
PILL_RUNNING = "running"
PILL_NEVER = "never"
PILL_ERRORS = "errors"

#: DESIGN-ui §Visual style: the one literal colour of the application.
AMBER_LIGHT = "#B7791F"
AMBER_DARK = "#E3A23A"

CARD_MIN_WIDTH = 240


def _dark() -> bool:
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def pill_color(kind: str) -> QColor:
    """The muted colour of a pill; never a red, whatever the palette says."""
    palette = QGuiApplication.palette()
    if kind == PILL_ERRORS:
        return QColor(AMBER_DARK if _dark() else AMBER_LIGHT)
    if kind in (PILL_UNREACHABLE, PILL_NEVER):
        return palette.color(QPalette.ColorRole.Mid)
    return palette.color(QPalette.ColorRole.WindowText)


def pill_text(kind: str, failed: int = 0) -> str:
    """The Italian label of a pill; ``failed`` only matters for ``PILL_ERRORS``."""
    if kind == PILL_ERRORS:
        if failed == 1:
            return strings.SYNC_PILL_ERROR_ONE
        return strings.SYNC_PILL_ERRORS.format(n=failed)
    return {
        PILL_FRESH: strings.SYNC_PILL_FRESH,
        PILL_STALE: strings.SYNC_PILL_STALE,
        PILL_UNREACHABLE: strings.SYNC_PILL_UNREACHABLE,
        PILL_RUNNING: strings.SYNC_PILL_RUNNING,
        PILL_NEVER: strings.SYNC_PILL_NEVER,
    }[kind]


class EnvCard(QFrame):
    """The card of one environment: name, pill, four facts and the host."""

    def __init__(self, env_name: str, url: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.env_name = env_name
        self._url = url
        self._status: EnvStatus | None = None
        self._running = False
        self._outcome: str | None = None
        self._failed = 0
        self.pill_kind = PILL_NEVER

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        self.name_label = QLabel(env_name)
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        self.pill = QLabel()
        self.last_label = QLabel()
        self.local_label = QLabel()
        self.latest_label = QLabel()
        self.index_label = QLabel()
        self.url_label = QLabel(urlsplit(url).netloc or url)
        self.url_label.setToolTip(url)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(self.name_label)
        header_layout.addWidget(self.pill)
        layout.addWidget(header)
        layout.addSpacing(4)
        for label in (self.last_label, self.local_label, self.latest_label, self.index_label,
                      self.url_label):
            layout.addWidget(label)

        self.set_status(None)

    # -- state -------------------------------------------------------------

    def set_status(self, status: EnvStatus | None) -> None:
        """Fill the four fact lines from what the core knows about the mirror."""
        self._status = status
        self.last_label.setText(strings.SYNC_CARD_LAST.format(when=self._when()))
        self.local_label.setText(strings.SYNC_CARD_LOCAL.format(
            days=status.n_local_files if status else 0,
            size=format_size(status.local_bytes if status else 0),
        ))
        self.latest_label.setText(
            strings.SYNC_CARD_LATEST.format(day=status.latest_day.strftime("%d/%m/%Y"))
            if status is not None and status.latest_day is not None
            else strings.SYNC_CARD_LATEST_NONE
        )
        pending = status.index_pending if status else 0
        self.index_label.setText(
            strings.SYNC_CARD_INDEX_OK if pending == 0
            else strings.SYNC_CARD_INDEX_PENDING.format(n=pending)
        )
        self._refresh_pill()

    def set_running(self, running: bool) -> None:
        """A run has this environment in hand; it also clears the old verdict.

        Starting a new run makes "non raggiungibile" from ten minutes ago a
        stale claim, so it goes as soon as the card starts spinning.
        """
        self._running = running
        if running:
            self._outcome, self._failed = None, 0
        self._refresh_pill()

    def set_outcome(self, status: str | None, failed: int = 0) -> None:
        """What the finished run said about this env (``EnvResult.status``)."""
        self._outcome, self._failed = status, failed
        self._refresh_pill()

    def retune(self) -> None:
        """Re-apply the pill colour after a light/dark switch."""
        self.pill.setStyleSheet(f"color: {pill_color(self.pill_kind).name()};")

    # -- internals ---------------------------------------------------------

    def _when(self) -> str:
        return format_when(self._status.last_success if self._status else None)

    def _refresh_pill(self) -> None:
        self.pill_kind = self._kind()
        self.pill.setText(pill_text(self.pill_kind, self._failed))
        self.retune()

    def _kind(self) -> str:
        """The single pill that describes this environment right now.

        Order matters: what is happening beats what happened, and what happened
        during the last run beats what the mirror looks like on disk.
        """
        if self._running:
            return PILL_RUNNING
        if self._outcome == "unreachable":
            return PILL_UNREACHABLE
        if self._outcome == "errors" and self._failed:
            return PILL_ERRORS
        if self._status is None:
            return PILL_NEVER
        if self._status.fresh:
            return PILL_FRESH
        if self._status.never_synced:
            return PILL_NEVER
        return PILL_STALE

    # -- painting ----------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Elide the host: a long URL must not stretch the whole cards row."""
        super().resizeEvent(event)
        host = urlsplit(self._url).netloc or self._url
        width = max(0, self.url_label.width())
        self.url_label.setText(
            QFontMetrics(self.url_label.font()).elidedText(host, Qt.TextElideMode.ElideMiddle, width)
            if width else host
        )
