"""One environment's card on the Sincronizzazione page.

The card answers, at a glance, the only question the page exists for: *is my
local copy of this environment any good?* Its header is the name, a badge and
the host; below come two labelled rows ("Ultima sincronizzazione", "Archivio
locale"), the index backlog when there is one, and the 30-day coverage
calendar. While a run is on this environment the card also shows the current
file, a bar, the totals and the rate with the ETA — each card its own progress,
so two cards can no longer both say "in corso".

The card decides nothing: the badge comes ready-made from
:func:`~.sync_badge.badge_for` (through the page's presenter, which also feeds
the app-bar chip, so the two always agree), and the progress texts from
:func:`~.sync_format.strip_texts`. Colours are the theme's: the badge is a
``QLabel`` with a ``pill`` property, the card a ``QFrame[role="card"]``.
"""
from __future__ import annotations

from datetime import date
from urllib.parse import urlsplit

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.contracts import CoverageDays, EnvStatus
from qtrequestory.ui.pages.coverage_strip import CoverageStrip
from qtrequestory.ui.pages.sync_badge import NEVER, Badge, badge_for
from qtrequestory.ui.pages.sync_format import StripTexts, format_days, format_size, format_when

__all__ = ["CARD_MIN_WIDTH", "EnvCard"]

CARD_MIN_WIDTH = 320


class EnvCard(QFrame):
    """The card of one environment: header, facts, coverage and its own progress."""

    def __init__(self, env_name: str, url: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.env_name = env_name
        self._host = urlsplit(url).netloc or url
        self.pill_kind = NEVER

        self.setFrameShape(QFrame.Shape.NoFrame)
        theme.set_role(self, "card")
        self.setMinimumWidth(CARD_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(theme.SPACE[3], theme.SPACE[2], theme.SPACE[3], theme.SPACE[2])
        layout.setSpacing(theme.SPACE[1])
        layout.addLayout(self._build_header(url))
        layout.addLayout(self._build_rows())
        self.strip = CoverageStrip()
        layout.addWidget(self.strip)
        self.progress_box = self._build_progress()
        layout.addWidget(self.progress_box)

        self.set_status(None, None)
        self.set_badge(badge_for(None))
        self.set_progress(None)

    # -- construction ------------------------------------------------------

    def _build_header(self, url: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE[1])
        self.name_label = QLabel(self.env_name)
        theme.set_role(self.name_label, "section")
        self.pill = QLabel()
        self.pill.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.host_label = QLabel(self._host)
        self.host_label.setToolTip(url)
        self.host_label.setFont(theme.mono_font())
        theme.set_role(self.host_label, "muted")
        self.host_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.host_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row.addWidget(self.name_label)
        row.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.host_label, 1)
        return row

    def _build_rows(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setContentsMargins(0, theme.SPACE[0], 0, theme.SPACE[0])
        grid.setHorizontalSpacing(theme.SPACE[2])
        grid.setVerticalSpacing(theme.SPACE[0])
        self.row_labels: list[QLabel] = []

        def row(r: int, text: str) -> QLabel:
            key = QLabel(text)
            theme.set_role(key, "muted")
            value = QLabel()
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(key, r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, r, 1)
            self.row_labels.append(key)
            return value

        self.last_value = row(0, strings.SYNC_CARD_LAST_LABEL)
        self.archive_value = row(1, strings.SYNC_CARD_ARCHIVE_LABEL)
        self.index_value = row(2, strings.SYNC_CARD_INDEX_LABEL)
        self._index_key = self.row_labels[-1]
        grid.setColumnStretch(1, 1)
        return grid

    def _build_progress(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, theme.SPACE[0], 0, 0)
        layout.setSpacing(2)
        top = QHBoxLayout()
        self.progress_label = QLabel()
        self.progress_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.totals_label = QLabel()
        theme.set_role(self.totals_label, "muted")
        top.addWidget(self.progress_label, 1)
        top.addWidget(self.totals_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.rate_label = QLabel()
        theme.set_role(self.rate_label, "muted")
        layout.addLayout(top)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.rate_label)
        return box

    # -- state -------------------------------------------------------------

    def set_status(self, status: EnvStatus | None, coverage: CoverageDays | None,
                   today: date | None = None) -> None:
        """Fill the rows and the calendar from what the core knows (no network)."""
        when = format_when(status.last_success if status else None)
        downloaded = status.last_downloaded if status is not None else 0
        if status is not None and status.last_success is not None and downloaded:
            when += (strings.SYNC_CARD_DOWNLOADED_ONE if downloaded == 1
                     else strings.SYNC_CARD_DOWNLOADED.format(n=downloaded))
        self.last_value.setText(strings.SYNC_CARD_LAST.format(when=when))
        n_files = status.n_local_files if status else 0
        first = coverage.first_local if coverage is not None else None
        self.archive_value.setText(
            strings.SYNC_CARD_ARCHIVE.format(
                days=format_days(n_files), size=format_size(status.local_bytes),
                first=first.strftime("%d/%m/%Y"))
            if status is not None and n_files and first is not None
            else strings.SYNC_CARD_ARCHIVE_EMPTY
        )
        pending = status.index_pending if status else 0
        self.index_value.setText(strings.SYNC_CARD_INDEX_PENDING.format(n=pending))
        self.index_value.setVisible(pending > 0)
        self._index_key.setVisible(pending > 0)
        self.strip.set_coverage(coverage, today)

    def set_badge(self, badge: Badge) -> None:
        self.pill_kind = badge.kind
        self.pill.setText(badge.text)
        self.pill.setProperty("pill", badge.tone)
        theme.repolish(self.pill)

    def set_progress(self, texts: StripTexts | None) -> None:
        """This card's run progress; ``None`` hides it (not this env's turn)."""
        self.progress_box.setVisible(texts is not None)
        if texts is None:
            self.progress_bar.setValue(0)
            return
        if texts.label:
            self.progress_label.setText(texts.label)
        self.totals_label.setText(texts.totals)
        self.rate_label.setText(texts.rate)
        self.rate_label.setVisible(bool(texts.rate))
        self.progress_bar.setValue(texts.percent)

    def set_progress_text(self, text: str) -> None:
        """"Avvio…" / "Annullamento…" in place of the file name."""
        self.progress_label.setText(text)

    # -- painting ----------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        """Elide the host: a long URL must not stretch the whole cards grid."""
        super().resizeEvent(event)
        width = max(0, self.host_label.width())
        self.host_label.setText(
            QFontMetrics(self.host_label.font()).elidedText(
                self._host, Qt.TextElideMode.ElideMiddle, width)
            if width else self._host
        )
