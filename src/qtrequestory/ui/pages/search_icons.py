"""Icons of the Ricerca page that follow the theme.

``icons.icon`` tints a glyph for the theme that is applied *now*; a button
keeps that pixmap after a light/dark switch. :class:`ThemedIcons` remembers
which glyph (and which colour token) every button or label was given and sets
them again on ``theme.signals.changed``. It is a ``QObject`` parented to the
widget that owns the targets, so the connection dies with that widget.
"""
from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from qtrequestory.ui import icons, theme

__all__ = ["ThemedIcons"]

#: Size of an icon shown in a label (the omnibox's magnifier).
LABEL_ICON_PX = 16


class ThemedIcons(QObject):
    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self._targets: list[tuple[QWidget, str, str | None, int]] = []
        theme.signals.changed.connect(self._retint)

    def set(self, target: QAbstractButton | QLabel, name: str, tone: str | None = None,
            size: int = LABEL_ICON_PX) -> None:
        """Give ``target`` the ``name`` glyph in the ``tone`` token (default: text).

        ``size`` is for a label, which shows a pixmap; a button scales its icon.
        """
        self._targets = [t for t in self._targets if t[0] is not target]
        self._targets.append((target, name, tone, size))
        _apply(target, name, tone, size)

    def _retint(self) -> None:
        for target, name, tone, size in self._targets:
            _apply(target, name, tone, size)


def _apply(target: QWidget, name: str, tone: str | None, size: int) -> None:
    colour = getattr(theme.tokens(), tone) if tone else None
    glyph = icons.icon(name, colour)
    if isinstance(target, QLabel):
        target.setPixmap(glyph.pixmap(size, size))
    else:
        target.setIcon(glyph)
