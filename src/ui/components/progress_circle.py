"""
progress_circle.py
────────────────────────────────────────────────────────────────
Samsung One UI 감성의 부드러운 원형 회전 로딩 인디케이터 (스피너)
"""

from typing import Optional
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ProgressCircle(QWidget):
    """
    Samsung One UI 감성의 부드러운 원형 회전 로딩 인디케이터 (스피너)
    """

    def __init__(self, size: int = 42, color: str = "#0072DE", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._size = size
        self._color = QColor(color)
        self._angle = 0
        self.setFixedSize(size, size)

        self._timer = QTimer(self)
        self._timer.setInterval(25)  # 40 fps
        self._timer.timeout.connect(self._rotate)

    def _rotate(self):
        self._angle = (self._angle + 9) % 360
        self.update()

    def start(self):
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        pen_width = max(3.5, self._size / 10.0)
        margin = pen_width / 2.0 + 2.0
        rect = self.rect().adjusted(int(margin), int(margin), -int(margin), -int(margin))

        # 1. 배경 트랙 링 (은은한 라이트 그레이)
        bg_pen = QPen(QColor("#E1E6EB"), pen_width)
        bg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(bg_pen)
        painter.drawEllipse(rect)

        # 2. 전경 회전 호 (Samsung One UI Blue)
        fg_pen = QPen(self._color, pen_width)
        fg_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(fg_pen)

        # Qt drawArc 각도는 1/16도 단위
        start_angle = -self._angle * 16
        span_angle = -110 * 16
        painter.drawArc(rect, start_angle, span_angle)
