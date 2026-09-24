"""The environment cards of the Sincronizzazione page, in one or two columns.

A layout, not a widget: the cards sit directly in the page's content so the
page keeps deciding the number of columns from its own width (a card grid that
measured itself would oscillate while the scroll bar comes and goes).
"""
from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QWidget

from qtrequestory.ui import theme
from qtrequestory.ui.contracts import Environment
from qtrequestory.ui.pages.env_card import EnvCard

__all__ = ["EnvCardsGrid"]


class EnvCardsGrid(QGridLayout):
    """One :class:`EnvCard` per environment; ``set_columns`` re-flows them."""

    def __init__(self) -> None:
        super().__init__()
        self.setHorizontalSpacing(theme.SPACE[2])
        self.setVerticalSpacing(theme.SPACE[2])
        self._cards: list[EnvCard] = []
        self._columns = 2

    def rebuild(self, environments: Iterable[Environment], parent: QWidget) -> None:
        for card in self._cards:
            self.removeWidget(card)
            card.deleteLater()
        self._cards = [EnvCard(env.name, env.url, parent) for env in environments]
        self._place()

    def cards(self) -> list[EnvCard]:
        return list(self._cards)

    def card(self, env_name: str) -> EnvCard | None:
        return next((c for c in self._cards if c.env_name == env_name), None)

    def columns(self) -> int:
        return self._columns

    def set_columns(self, columns: int) -> None:
        if columns != self._columns:
            self._columns = columns
            self._place()

    def _place(self) -> None:
        for card in self._cards:
            self.removeWidget(card)
        for i, card in enumerate(self._cards):
            self.addWidget(card, i // self._columns, i % self._columns,
                           Qt.AlignmentFlag.AlignTop)
        for column in range(2):
            self.setColumnStretch(column, 1 if column < self._columns else 0)
