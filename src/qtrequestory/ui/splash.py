"""The splash screen: the one window on screen while the pages are built (D7).

``run_gui`` shows it right after the ``QApplication`` (and the single-instance
check), before the main window module and its pages are imported and built,
and closes it with ``finish(window)`` once the window is visible. Until then
the user used to look at a bare desktop — or, worse, at the stray windows of
widgets shown before they had a parent (see ``tests/ui/test_startup_windows.py``).

Pure Qt on purpose: PyInstaller's ``--splash`` draws with Tcl/Tk, which the
spec excludes (research fase25-identita-ux §4).

The look is palette B: the app bar's blue gradient (so it follows light and
dark), the icon, the name in white, an amber identity stroke, the version and
the current phase ("Apro l'archivio…", "Preparo le pagine…"). The pixmap is
painted at the screen's device pixel ratio and the icon rendered from the SVG,
so it is sharp at 125-200 % scaling. No screen (a headless run) means no
splash and no waiting.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import QApplication, QSplashScreen

from qtrequestory.ui import icons, strings, theme

__all__ = ["HEIGHT", "WIDTH", "Splash", "start_splash"]

#: Logical size of the splash (device-independent pixels).
WIDTH, HEIGHT = 440, 248
RADIUS = 14
MARGIN = 32
ICON_PX = 72
#: Where the name, the amber stroke and the version start (right of the icon).
TEXT_X = MARGIN + ICON_PX + 20


class Splash(QSplashScreen):
    """Branded, frameless, centred; :meth:`phase` says what is happening."""

    def __init__(self, version: str, screen: QScreen) -> None:
        self.app_name = strings.APP_NAME
        self.version_text = strings.SPLASH_VERSION.format(version=version) if version else ""
        self._tokens = theme.tokens()
        super().__init__(screen, _render(self.app_name, self.version_text, self._tokens,
                                         _pixel_ratio(screen)))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowTitle(strings.APP_NAME)

    def phase(self, text: str) -> None:
        """Show ``text`` as the current phase and paint it now.

        The event loop is not running yet during startup: without the explicit
        ``processEvents`` the new text would appear only when it is too late.
        """
        self.showMessage(text)
        QApplication.processEvents()

    def drawContents(self, painter: QPainter) -> None:  # noqa: N802 (Qt API)
        text = self.message()
        if not text:
            return
        t = self._tokens
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        baseline = HEIGHT - MARGIN
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.identity))
        painter.drawEllipse(QPointF(MARGIN + 3, baseline - 4), 3, 3)
        painter.setFont(_font(9.5))
        painter.setPen(QColor(t.on_header_muted))
        painter.drawText(QRectF(MARGIN + 14, baseline - 16, WIDTH - 2 * MARGIN - 14, 20),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)


def start_splash(app: QApplication, version: str) -> Splash | None:
    """Show the splash on the screen under the mouse; ``None`` without a screen."""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    if screen is None:
        return None
    splash = Splash(version, screen)
    splash.showMessage(strings.SPLASH_OPENING)
    splash.show()
    app.processEvents()
    return splash


def _pixel_ratio(screen: QScreen) -> float:
    return max(1.0, float(screen.devicePixelRatio()))


def _font(point_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont()
    font.setFamilies(list(theme.UI_FAMILIES))
    font.setPointSizeF(point_size)
    font.setWeight(weight)
    return font


def _render(name: str, version: str, t: theme.Tokens, ratio: float) -> QPixmap:
    """The static part of the splash, painted in device pixels."""
    pixmap = QPixmap(round(WIDTH * ratio), round(HEIGHT * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    gradient = QLinearGradient(0, 0, WIDTH, 0)  # left to right, like the app bar
    for position, colour in theme.header_stops(t):
        gradient.setColorAt(position, QColor(colour))
    shape = QPainterPath()
    shape.addRoundedRect(QRectF(0, 0, WIDTH, HEIGHT), RADIUS, RADIUS)
    painter.fillPath(shape, gradient)

    icon_top = 52
    mark = QIcon(str(icons.ICON_DIR / "app.svg")).pixmap(QSize(ICON_PX, ICON_PX), ratio)
    painter.drawPixmap(MARGIN, icon_top, mark)

    painter.setPen(QColor(t.on_header))
    painter.setFont(_font(20, QFont.Weight.DemiBold))
    painter.drawText(QRectF(TEXT_X, icon_top, WIDTH - TEXT_X - MARGIN, 36),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(t.identity))
    painter.drawRoundedRect(QRectF(TEXT_X, icon_top + 42, 36, 4), 2, 2)
    if version:
        painter.setPen(QColor(t.on_header_muted))
        painter.setFont(_font(10))
        painter.drawText(QRectF(TEXT_X, icon_top + 52, WIDTH - TEXT_X - MARGIN, 22),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, version)
    painter.end()
    return pixmap
