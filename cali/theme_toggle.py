"""Native landscape theme button, inspired by the Uiverse circular switch.

Reference: https://uiverse.io/abinandhs_7835/shy-fox-63
Artwork and animation are drawn for CALI with QPainter; no web runtime needed.
"""

from math import hypot

from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QEasingCurve, QEvent
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QPushButton, QWidget


class RadialThemeReveal(QWidget):
    """Reveal live widgets through a wide, feathered circular transition."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._snapshot = QPixmap()
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(360)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._advance)
        self._animation.finished.connect(self.stop)
        parent.installEventFilter(self)
        self.hide()

    def start(self, snapshot):
        self._animation.stop()
        self._snapshot = snapshot
        self._progress = 0.0
        self.setGeometry(self.parentWidget().rect())
        self.show()
        self.raise_()
        self._animation.start()

    def stop(self):
        self._animation.stop()
        self.hide()
        self._snapshot = QPixmap()

    def _advance(self, value):
        self._progress = float(value)
        self.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(self.parentWidget().rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._progress <= 0:
            painter.drawPixmap(self.rect(), self._snapshot)
            painter.end()
            return

        extent = hypot(self.width(), self.height()) * .5
        feather = extent * .4
        outer = (extent + feather) * self._progress
        inner = outer - feather
        mask = QRadialGradient(QPointF(self.width() / 2, self.height() / 2), outer)
        # Smoothstep makes both ends of the broad blend fade without a seam.
        center_alpha = max(0.0, min(1.0, -inner / feather))
        center_alpha = center_alpha ** 2 * (3 - 2 * center_alpha)
        mask.setColorAt(0, QColor(0, 0, 0, round(255 * center_alpha)))
        for step in range(21):
            fraction = step / 20
            distance = inner + fraction * feather
            if distance > 0:
                alpha = fraction ** 2 * (3 - 2 * fraction)
                mask.setColorAt(min(1.0, distance / outer), QColor(0, 0, 0, round(255 * alpha)))

        # Mask a separate layer so opacity removes only the old snapshot.
        layer = QPixmap(self.size() * self.devicePixelRatioF())
        layer.setDevicePixelRatio(self.devicePixelRatioF())
        layer.fill(Qt.transparent)
        blend = QPainter(layer)
        blend.drawPixmap(self.rect(), self._snapshot)
        blend.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        blend.fillRect(self.rect(), mask)
        blend.end()
        painter.drawPixmap(0, 0, layer)
        painter.end()


class LandscapeThemeButton(QPushButton):
    """Show the current theme as a small circular landscape."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("themeToggle")
        self.setFixedSize(42, 42)
        self.setCheckable(True)  # Checked means night, also exposed to accessibility.
        self.setCursor(Qt.PointingHandCursor)
        self._night = 0.0
        self._day_mode = True
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(220)
        self._animation.setEasingCurve(QEasingCurve.InOutCubic)
        self._animation.valueChanged.connect(self._animate)
        self.set_day_mode(True)

    def _animate(self, value):
        self._night = float(value)
        self.update()

    def set_day_mode(self, enabled):
        self._day_mode = bool(enabled)
        self.setChecked(not enabled)
        action = "Switch to night mode" if enabled else "Switch to day mode"
        self.setToolTip(action)
        self.setAccessibleName(action)
        self.setAccessibleDescription(
            "Current theme: sunset beach" if enabled else "Current theme: moonlit mountain"
        )
        self._animation.stop()
        target = 0.0 if enabled else 1.0
        if self.isVisible() and self._night != target:
            self._animation.setStartValue(self._night)
            self._animation.setEndValue(target)
            self._animation.start()
        else:
            self._animate(target)

    @staticmethod
    def _shape(painter, color, start, segments):
        path = QPainterPath(QPointF(*start))
        for segment in segments:
            if len(segment) == 2:
                path.lineTo(*segment)
            else:
                path.cubicTo(*segment)
        path.closeSubpath()
        painter.fillPath(path, QColor(color))

    @staticmethod
    def _beach(painter):
        # Flat sunset bands echo the striped sun in the CALI logo.
        for top, bottom, color in (
            (0, 22, "#F3E79B"), (22, 34, "#FAC484"),
            (34, 45, "#F8A07E"), (45, 58, "#EB7F86"),
            (58, 100, "#A059A0"),
        ):
            painter.fillRect(QRectF(0, top, 100, bottom - top), QColor(color))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F3E79B"))
        painter.drawEllipse(QRectF(34, 32, 32, 32))
        painter.fillRect(QRectF(0, 58, 100, 42), QColor("#5C53A5"))
        painter.setPen(QPen(QColor("#FAC484"), 2.2, Qt.SolidLine, Qt.RoundCap))
        for x1, x2, y in ((40, 60, 63), (44, 56, 68), (38, 62, 73)):
            painter.drawLine(QPointF(x1, y), QPointF(x2, y))
        painter.setPen(Qt.NoPen)
        LandscapeThemeButton._shape(painter, "#CE6693", (0, 79), [
            (23, 71, 38, 88, 61, 84), (78, 81, 92, 77, 100, 80),
            (100, 100), (0, 100),
        ])
        LandscapeThemeButton._shape(painter, "#FAC484", (0, 90), [
            (26, 79, 41, 97, 70, 90), (86, 86, 94, 89, 100, 91),
            (100, 100), (0, 100),
        ])
        painter.setPen(QPen(QColor("#F3E79B"), 1.4, Qt.SolidLine, Qt.RoundCap))
        wave = QPainterPath(QPointF(6, 86))
        wave.cubicTo(26, 77, 40, 94, 64, 87)
        painter.drawPath(wave)

    @staticmethod
    def _mountain(painter):
        painter.fillRect(QRectF(0, 0, 100, 100), QColor("#211D39"))
        painter.fillRect(QRectF(0, 44, 100, 56), QColor("#302748"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F3E79B"))
        painter.drawEllipse(QRectF(48, 18, 32, 32))
        painter.setBrush(QColor("#FAC484"))
        painter.drawEllipse(QRectF(67, 25, 4, 4))
        painter.drawEllipse(QRectF(58, 22, 3, 3))
        painter.setBrush(QColor("#F3E79B"))
        for x, y, radius in ((22, 24, 1.2), (36, 14, 1), (84, 38, 1.1),
                             (14, 43, 1), (42, 37, .8)):
            painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.setPen(QPen(QColor("#FAC484"), 1.2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(30, 31), QPointF(30, 37))
        painter.drawLine(QPointF(27, 34), QPointF(33, 34))
        painter.setPen(Qt.NoPen)
        LandscapeThemeButton._shape(painter, "#5C4380", (0, 78), [
            (24, 48), (39, 67), (63, 39), (100, 78), (100, 100), (0, 100),
        ])
        LandscapeThemeButton._shape(painter, "#16182D", (0, 88), [
            (39, 42), (70, 79), (83, 64), (100, 86), (100, 100), (0, 100),
        ])
        LandscapeThemeButton._shape(painter, "#A059A0", (29, 54), [
            (39, 42), (51, 57), (40, 51), (36, 56), (34, 52),
        ])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.scale(self.width() / 100, self.height() / 100)
        # Leave room around the scene for keyboard focus and hover feedback.
        circle = QRectF(7, 7, 86, 86)
        clip = QPainterPath()
        clip.addEllipse(circle)
        painter.save()
        painter.setClipPath(clip)
        painter.translate(7, 7)
        painter.scale(.86, .86)
        if self.isDown():
            painter.translate(50, 50)
            painter.scale(.95, .95)
            painter.translate(-50, -50)
        self._beach(painter)
        if self._night > 0:
            # Composite the opaque night scene as a whole to avoid layer ghosts.
            scene = QPixmap(round(self.width() * self.devicePixelRatioF()),
                            round(self.height() * self.devicePixelRatioF()))
            scene.fill(Qt.transparent)
            night_painter = QPainter(scene)
            night_painter.setRenderHint(QPainter.Antialiasing)
            night_painter.scale(scene.width() / 100, scene.height() / 100)
            self._mountain(night_painter)
            night_painter.end()
            painter.setOpacity(self._night)
            painter.drawPixmap(QRectF(0, 0, 100, 100), scene, QRectF(scene.rect()))
        painter.restore()
        color = "#A059A0" if self._day_mode else "#FAC484"
        painter.setPen(QPen(QColor(color), 2.5 if self.underMouse() else 1.5))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(circle)
        if self.hasFocus():
            painter.setPen(QPen(QColor(color), 2, Qt.DotLine))
            painter.drawEllipse(QRectF(2, 2, 96, 96))
        painter.end()
