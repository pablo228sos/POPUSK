from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class RingGauge(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        self._accent = QColor("#ffb020")
        self._track = QColor(255, 255, 255, 35)
        self._primary = "0%"
        self._headline = "MISSION"
        self._subline = "0.0 km"
        self.setMinimumSize(170, 170)

    def set_value(
        self,
        progress: float,
        primary_text: str,
        headline: str,
        subline: str,
        accent: str = "#ffb020",
    ) -> None:
        self._progress = max(0.0, min(1.0, progress))
        self._primary = primary_text
        self._headline = headline
        self._subline = subline
        self._accent = QColor(accent)
        self.update()

    def paintEvent(self, event) -> None:  # pragma: no cover - custom widget paint
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        bounds = self.rect().adjusted(10, 10, -10, -10)
        size = min(bounds.width(), bounds.height())
        outer = QRectF(
            (self.width() - size) / 2,
            (self.height() - size) / 2,
            size,
            size,
        )
        ring_rect = outer.adjusted(12, 12, -12, -12)

        painter.setPen(QPen(self._track, 12))
        painter.drawArc(ring_rect, 0, 360 * 16)

        painter.setPen(QPen(self._accent, 12, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(ring_rect, 90 * 16, int(-360 * self._progress * 16))

        inner = outer.adjusted(30, 30, -30, -30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 11, 16, 170))
        painter.drawEllipse(inner)

        painter.setPen(QColor("#b5c6db"))
        font = QFont("Segoe UI", 10)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        painter.setFont(font)
        painter.drawText(
            QRectF(inner.left(), inner.top() + 18, inner.width(), 18),
            Qt.AlignmentFlag.AlignCenter,
            self._headline,
        )

        painter.setPen(QColor("#ffffff"))
        primary_font = QFont("Segoe UI", 24, QFont.Weight.Bold)
        painter.setFont(primary_font)
        painter.drawText(
            QRectF(inner.left(), inner.center().y() - 24, inner.width(), 38),
            Qt.AlignmentFlag.AlignCenter,
            self._primary,
        )

        painter.setPen(QColor("#38d39f"))
        sub_font = QFont("Segoe UI", 12, QFont.Weight.DemiBold)
        painter.setFont(sub_font)
        painter.drawText(
            QRectF(inner.left(), inner.bottom() - 42, inner.width(), 20),
            Qt.AlignmentFlag.AlignCenter,
            self._subline,
        )
