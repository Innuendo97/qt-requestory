"""The omnibox of the Ricerca bar: one field for FDI, template key and entry names.

People arrive here with *something* on the clipboard — a uuid, a key, a line
copied from a daily log — and used to have to decide which of two fields it
belonged in. The omnibox decides for them: what is typed or pasted becomes a
**chip**, one for the FDI and one for the template key, each removable on its
own (its ✕, or Backspace on an empty field).

When text becomes a chip:

* on paste — an entry name gives both chips (only the key when it has no FDI),
  a single token gives one;
* on Space or Enter, and when the field loses the focus;
* when a key is picked from the completer.

Text that has not become a chip yet still counts: :meth:`SearchOmnibox.fdi`
and :meth:`SearchOmnibox.template_key` classify it, so [Cerca] right after
typing does what the user expects.

Ctrl+L / Ctrl+K (bound by the page) call :meth:`focus_fdi` / :meth:`focus_key`,
which move that chip back into the text, selected, so typing replaces it.
"""
from __future__ import annotations

from collections.abc import Sequence
from functools import partial

from PySide6.QtCore import QEvent, QObject, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QCompleter,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from qtrequestory.ui import strings, theme
from qtrequestory.ui.pages.search_icons import ThemedIcons
from qtrequestory.ui.pages.search_paste import classify_token, parse_pasted_entry
from qtrequestory.ui.pages.search_recents import Recent

__all__ = ["Chip", "SearchOmnibox"]

#: Minimum width of the typing area, so a field full of chips can still be typed in.
EDIT_MIN_WIDTH = 120


class Chip(QFrame):
    """``[FDI 1a2b3c4d-…  ✕]``: a caption, the value in mono, a remove button."""

    removed = Signal()

    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("chip", True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.caption = QLabel(caption)
        self.caption.setProperty("chipCaption", True)
        self.value_label = QLabel()
        self.value_label.setFont(theme.mono_font())
        self.close_button = QToolButton()
        ThemedIcons(self).set(self.close_button, "dismiss", "muted")
        self.close_button.setToolTip(strings.SEARCH_CHIP_REMOVE)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(self.removed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 1, 2, 1)
        layout.setSpacing(4)
        layout.addWidget(self.caption)
        layout.addWidget(self.value_label)
        layout.addWidget(self.close_button)
        self._value = ""
        self.setVisible(False)

    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value
        self.value_label.setText(value)
        self.value_label.setToolTip(value)
        self.setVisible(bool(value))


class SearchOmnibox(QFrame):
    """FDI chip + key chip + the text being typed."""

    submitted = Signal()
    changed = Signal()
    recent_chosen = Signal(object)  # Recent

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("omnibox")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setToolTip(strings.SEARCH_OMNIBOX_TOOLTIP)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.fdi_chip = Chip(strings.SEARCH_CHIP_FDI)
        self.key_chip = Chip(strings.SEARCH_CHIP_KEY)
        self.edit = QLineEdit()
        self.edit.setMinimumWidth(EDIT_MIN_WIDTH)
        self.edit.setFrame(False)
        self._recents: list[Recent] = []
        self._keys = QStringListModel(self)
        #: The recent-search menu while it is open (tests look at it).
        self.open_menu: QMenu | None = None
        #: The user asked for a key (Ctrl+K): ambiguous tokens are keys.
        self._expect_key = False
        self._build()

    def _build(self) -> None:
        self._icon = QLabel()
        ThemedIcons(self).set(self._icon, "search", "muted")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(6)
        layout.addWidget(self._icon)
        layout.addWidget(self.fdi_chip)
        layout.addWidget(self.key_chip)
        layout.addWidget(self.edit, 1)
        self.setFocusProxy(self.edit)
        self.fdi_chip.removed.connect(partial(self.set_fdi, ""))
        self.key_chip.removed.connect(partial(self.set_template_key, ""))
        self.edit.textChanged.connect(lambda _text: self.changed.emit())
        self.edit.installEventFilter(self)
        completer = QCompleter(self._keys, self)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.activated[str].connect(self._on_completion)
        self.edit.setCompleter(completer)
        self._update_placeholder()

    # -- the two filters -----------------------------------------------------

    def fdi(self) -> str:
        """The FDI chip, else the typed text when it reads as an FDI."""
        return self.fdi_chip.value() or self._pending("fdi")

    def template_key(self) -> str:
        return self.key_chip.value() or self._pending("key")

    def set_fdi(self, value: str) -> None:
        self.fdi_chip.set_value((value or "").strip().lower())
        self._chips_changed()

    def set_template_key(self, value: str) -> None:
        self.key_chip.set_value((value or "").strip().upper())
        self._chips_changed()

    def clear(self) -> None:
        self.edit.clear()
        self.fdi_chip.set_value("")
        self.key_chip.set_value("")
        self._chips_changed()

    def commit(self) -> bool:
        """Turn the typed text into a chip when it is an entry name or a token."""
        text = self.edit.text()
        if not text.strip():
            return False
        return self.paste_text(text, replace=True)

    def paste_text(self, text: str, *, replace: bool = False) -> bool:
        """Smart paste of ``text``; False means "paste it as it is".

        ``replace``: ``text`` IS the field's content (a commit). Otherwise the
        paste replaces the selection, as any paste does: a token pasted over
        the selected FDI (Ctrl+L, Ctrl+V) must not leave the old one in the
        text, where the next commit would bring it back. A token pasted INTO
        other text is an ordinary paste — the text is the user's to finish.
        """
        entry = parse_pasted_entry(text)
        token = None
        if entry is None:
            token = (classify_token(text, prefer_key=self._expect_key)
                     if "\n" not in text.strip() else None)
            if token is None:
                return False
            if not replace and self._text_outside_selection().strip():
                return False
        if entry is not None:
            fdi, key = entry
            self.fdi_chip.set_value(fdi or "")
            self.key_chip.set_value(key)
        else:
            kind, value = token
            (self.fdi_chip if kind == "fdi" else self.key_chip).set_value(value)
        self.edit.clear()
        self._expect_key = False
        self._chips_changed()
        return True

    def _text_outside_selection(self) -> str:
        text = self.edit.text()
        if not self.edit.hasSelectedText():
            return text
        start = self.edit.selectionStart()
        return text[:start] + text[start + len(self.edit.selectedText()):]

    # -- template keys and recents ---------------------------------------------

    def set_template_keys(self, keys: Sequence[str]) -> None:
        self._keys.setStringList(list(keys))

    def template_keys(self) -> list[str]:
        return self._keys.stringList()

    def set_recents(self, recents: Sequence[Recent]) -> None:
        self._recents = list(recents)

    def recent_menu(self) -> QMenu:
        """The recent searches as a menu, built without showing it."""
        menu = QMenu(self)
        title = menu.addAction(strings.SEARCH_RECENT_TITLE)
        title.setEnabled(False)
        for recent in self._recents:
            action = menu.addAction(recent.label())
            action.triggered.connect(partial(self.recent_chosen.emit, recent))
        return menu

    # -- focus -----------------------------------------------------------------

    def focus_fdi(self) -> None:
        """Ctrl+L: the FDI back into the text, selected, ready to be replaced."""
        self._focus_on(self.fdi_chip)

    def focus_key(self) -> None:
        """Ctrl+K: the same for the template key."""
        self._focus_on(self.key_chip)

    def _focus_on(self, chip: Chip) -> None:
        self.commit()
        # After Ctrl+K a digits-only or hex-looking token ("386", "CAFE") is a key.
        self._expect_key = chip is self.key_chip
        value = chip.value()
        if value:
            chip.set_value("")
            self.edit.setText(value)
            self._chips_changed()
        self.edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.edit.selectAll()

    # -- keys ------------------------------------------------------------------

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt naming
        if obj is self.edit:
            kind = event.type()
            if kind == QEvent.Type.KeyPress and self._on_key(event):
                return True
            if kind in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
                self._set_focused(kind == QEvent.Type.FocusIn)
                if (kind == QEvent.Type.FocusOut
                        and event.reason() != Qt.FocusReason.PopupFocusReason):
                    self.commit()
        return super().eventFilter(obj, event)

    def _on_key(self, event) -> bool:
        key = event.key()
        empty = not self.edit.text()
        if event.matches(QKeySequence.StandardKey.Paste):
            clipboard = QGuiApplication.clipboard()
            return self.paste_text(clipboard.text() if clipboard is not None else "")
        if key == Qt.Key.Key_Space:
            return self.commit()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.commit()
            self.submitted.emit()
            return True
        if key == Qt.Key.Key_Backspace and empty:
            return self._remove_last_chip()
        if key == Qt.Key.Key_Escape:
            if not empty:
                self.edit.clear()
                return True
            if self.fdi_chip.value() or self.key_chip.value():
                self.clear()
                return True
            return False
        if key == Qt.Key.Key_Down and empty and self._recents:
            self._show_recents()
            return True
        return False

    def _remove_last_chip(self) -> bool:
        for chip in (self.key_chip, self.fdi_chip):
            if chip.value():
                chip.set_value("")
                self._chips_changed()
                return True
        return False

    def _show_recents(self) -> None:
        menu = self.recent_menu()
        menu.aboutToHide.connect(menu.deleteLater)
        self.open_menu = menu
        menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

    # -- reactions -------------------------------------------------------------

    def _on_completion(self, text: str) -> None:
        """A key picked from the list becomes the key chip.

        The line edit writes the completion into its text through its OWN
        connection, made on every focus-in and so always after this one: the
        text is emptied on the next turn of the event loop, once it is there.
        """
        self.set_template_key(text)
        QTimer.singleShot(0, self.edit.clear)

    def _pending(self, kind: str) -> str:
        token = classify_token(self.edit.text(), prefer_key=self._expect_key)
        return token[1] if token is not None and token[0] == kind else ""

    def _chips_changed(self) -> None:
        self._update_placeholder()
        self.changed.emit()

    def _update_placeholder(self) -> None:
        has_fdi, has_key = bool(self.fdi_chip.value()), bool(self.key_chip.value())
        if has_fdi and has_key:
            text = ""
        elif has_fdi:
            text = strings.SEARCH_OMNIBOX_PLACEHOLDER_KEY
        elif has_key:
            text = strings.SEARCH_OMNIBOX_PLACEHOLDER_FDI
        else:
            text = strings.SEARCH_OMNIBOX_PLACEHOLDER
        self.edit.setPlaceholderText(text)

    def _set_focused(self, focused: bool) -> None:
        if self.property("focused") != focused:
            self.setProperty("focused", focused)
            theme.repolish(self)
