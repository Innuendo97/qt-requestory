"""The two coverage banners above the Sincronizzazione cards.

The server keeps its daily files until a manual purge, so a day with calls
that is not in the local archive is one of two very different things:

* **pending** (warn): still on the server. One click fixes it, so the banner
  carries its own [Sincronizza ora], limited to the environments concerned;
* **lost** (bad): purged before anybody downloaded it. Nothing to click:
  the banner only says it cannot be recovered.

The sentences come from :mod:`~.sync_format`; this module only lays them out.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages import sync_format as fmt

__all__ = ["CoverageBanners"]


def _banner(role: str) -> tuple[QFrame, QLabel, QHBoxLayout]:
    frame = QFrame()
    theme.set_role(frame, role)
    row = QHBoxLayout(frame)
    row.setContentsMargins(theme.SPACE[2], theme.SPACE[1], theme.SPACE[1], theme.SPACE[1])
    label = QLabel()
    label.setWordWrap(True)
    row.addWidget(label, 1)
    frame.hide()
    return frame, label, row


class CoverageBanners(QWidget):
    """Pending days (warn, with a sync button) and lost days (bad)."""

    #: The environments with pending days, for ``SyncPage.start_sync``.
    sync_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE[1])
        self.pending_banner, self.pending_label, row = _banner("syncBanner")
        self.sync_button = QPushButton(strings.SYNC_BTN_NOW)
        self.sync_button.setToolTip(strings.SYNC_BTN_NOW_TOOLTIP)
        self.sync_button.clicked.connect(lambda: self.sync_requested.emit(list(self._envs)))
        row.addWidget(self.sync_button)
        self.lost_banner, self.lost_label, _row = _banner("syncBannerBad")
        # Same height with or without the button: two stacked banners of
        # different heights read as two different kinds of thing.
        self.lost_banner.setMinimumHeight(self.pending_banner.sizeHint().height())
        layout.addWidget(self.pending_banner)
        layout.addWidget(self.lost_banner)
        self._envs: list[str] = []

    def set_days(self, pending: Mapping[str, Sequence[date]],
                 lost: Mapping[str, Sequence[date]]) -> None:
        self._envs = [env for env, days in pending.items() if days]
        shown = False
        for frame, label, text in (
                (self.pending_banner, self.pending_label, fmt.pending_days_text(pending)),
                (self.lost_banner, self.lost_label, fmt.lost_days_text(lost))):
            label.setText(text)
            frame.setVisible(bool(text))
            shown = shown or bool(text)
        self.setVisible(shown)  # no empty gap in the page's spacing

    def set_sync_enabled(self, enabled: bool) -> None:
        """Off while a run is on, or while the scheduled task holds the lock."""
        self.sync_button.setEnabled(enabled)
