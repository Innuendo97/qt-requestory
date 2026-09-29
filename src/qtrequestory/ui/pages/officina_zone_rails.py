"""The ZONE RAILS of the viewer (phase 2.5, spec §5, D15): a thin coloured
line on the left margin of the page beside each zone box
(``Comparison.left_zones`` / ``right_zones``, one ``ZoneBox`` per page and
zone), its name on hover — never a label over the text. The colours are the
zone's token (``officina_types.ZONE_TOKENS``) in paper values; the page is
white in both themes. ``corpo`` has no rail.
"""
from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene

from qtrequestory.ui import strings
from qtrequestory.ui.pages.officina_overlays import paper
from qtrequestory.ui.pages.officina_types import ZONE_TOKENS, zone_name

__all__ = ["RAIL_GAP", "RAIL_WIDTH", "ZoneRail", "ZoneRails"]

#: Points: the rail's width and its distance from the page's left edge (the
#: scene keeps a 12 pt margin around the column).
RAIL_WIDTH = 3.0
RAIL_GAP = 4.0


class ZoneRail(QGraphicsRectItem):
    """One rail; ``zone`` and ``page`` say what it marks (tooltip: its name)."""

    def __init__(self, rect: QRectF, zone: str, page: int) -> None:
        super().__init__(rect)
        self.zone, self.page = zone, page
        self.setPen(Qt.PenStyle.NoPen)
        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)  # the view handles clicks
        self.setToolTip(strings.PANNELLO_RAIL_TIP.format(zone=zone_name(zone), page=page + 1))
        self.recolour()

    def recolour(self) -> None:
        self.setBrush(QBrush(paper(ZONE_TOKENS.get(self.zone, "muted"))))


class ZoneRails:
    """The rails of one view's scene."""

    def __init__(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        self.items: list[ZoneRail] = []

    def clear(self) -> None:
        for item in self.items:
            if item.scene() is self._scene:
                self._scene.removeItem(item)
        self.items = []

    def show(self, zones: Sequence[object], pages: Sequence[QRectF]) -> None:
        """A rail per zone box whose page is shown (``pages``: scene rects)."""
        self.clear()
        for box in zones:
            zone, page = getattr(box, "zone", "corpo"), getattr(box, "page", -1)
            if zone == "corpo" or not 0 <= page < len(pages):
                continue
            rect = pages[page]
            top = rect.top() + max(0.0, min(box.y0, rect.height()))
            bottom = rect.top() + max(0.0, min(box.y1, rect.height()))
            if bottom - top < 2.0:  # a hairline zone (a divider): still visible
                top, bottom = top - 1.0, top + 1.0
            left = rect.left() - RAIL_GAP - RAIL_WIDTH
            item = ZoneRail(QRectF(left, top, RAIL_WIDTH, bottom - top), zone, page)
            self._scene.addItem(item)
            self.items.append(item)

    def recolour(self) -> None:
        for item in self.items:
            item.recolour()
