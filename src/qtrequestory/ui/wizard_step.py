"""What every page of the first-run wizard shares: the header and a muted label.

``QWizard`` would draw a title banner of its own from ``QWizardPage.title()``,
in a look the theme does not control. The pages therefore leave ``title()``
empty and draw :class:`StepHeader` instead — the app icon, the page title and a
muted "Passo i di 3" — so the wizard looks like the rest of the application and
always says how far the user is.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget, QWizardPage

from qtrequestory.ui import icons, strings, theme

__all__ = ["HEADER_ICON_SIZE", "StepHeader", "WizardStepPage", "error_line",
           "muted"]

#: The app icon in the header, in device-independent pixels.
HEADER_ICON_SIZE = 48


def muted(text: str = "") -> QLabel:
    """A wrapping, quiet label — hints and notices."""
    label = QLabel(text)
    label.setWordWrap(True)
    theme.set_role(label, "muted")
    return label


def error_line() -> QLabel:
    """A wrapping label for a validation error: normal text, never muted."""
    label = QLabel()
    label.setWordWrap(True)
    return label


class StepHeader(QWidget):
    """[icon]  Title / Passo i di 3 / subtitle."""

    def __init__(self, step: int, title: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self.icon_label = QLabel()
        self.icon_label.setPixmap(
            icons.app_icon().pixmap(QSize(HEADER_ICON_SIZE, HEADER_ICON_SIZE),
                                    self.devicePixelRatioF())
        )
        self.icon_label.setFixedSize(HEADER_ICON_SIZE, HEADER_ICON_SIZE)
        self.title_label = QLabel(title)
        theme.set_role(self.title_label, "pageTitle")
        self.step_label = muted(strings.WIZARD_STEP.format(i=step))
        self.subtitle_label = muted(subtitle)

        text = QVBoxLayout()
        text.setSpacing(theme.SPACE[0] // 2)
        text.addWidget(self.title_label)
        text.addWidget(self.step_label)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE[3])
        row.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)


class WizardStepPage(QWizardPage):
    """A wizard page with :class:`StepHeader` on top and ``body`` below it."""

    def __init__(self, step: int, title: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self._step_title = title
        self.header = StepHeader(step, title, subtitle)
        outer = QVBoxLayout(self)
        outer.setSpacing(theme.SPACE[3])
        outer.addWidget(self.header)
        outer.addWidget(self.header.subtitle_label)
        #: Where each page puts its own widgets.
        self.body = QVBoxLayout()
        self.body.setSpacing(theme.SPACE[1])
        outer.addLayout(self.body, 1)

    def step_title(self) -> str:
        """The page title shown in the header (``title()`` stays empty)."""
        return self._step_title
