# app/ui/qt/preview/layer_video.py
from __future__ import annotations

from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QPaintEvent
from PySide6.QtWidgets import QWidget


class VideoDisplayWidget(QWidget):
    """
    SRP: Strictly renders the video frame and calculates layout geometry.
    It sits at the bottom of the QStackedLayout and ignores all mouse inputs.
    """

    # Emitted whenever the window resizes or image aspect ratio changes.
    # The Coordinator uses this to keep the transparent overlays perfectly aligned.
    pixmap_rect_changed = Signal(QRect)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Crucial: This layer doesn't need to intercept clicks.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._image: QImage | None = None
        self._pixmap_rect: QRect = QRect()
        self._placeholder_text: str = "No preview available"

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._update_pixmap_rect()
        self.update()

    def set_message(self, message: str) -> None:
        self._image = None
        self._placeholder_text = message
        self._update_pixmap_rect()
        self.update()

    def get_pixmap_rect(self) -> QRect:
        return self._pixmap_rect

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Draw the letterbox background
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if self._image is not None:
            painter.drawImage(self._pixmap_rect, self._image)
        else:
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder_text)

        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_pixmap_rect()

    def _update_pixmap_rect(self) -> None:
        if self._image is None:
            new_rect = QRect()
        else:
            iw, ih = self._image.width(), self._image.height()
            ww, wh = self.width(), self.height()
            if iw == 0 or ih == 0 or ww == 0 or wh == 0:
                new_rect = QRect()
            else:
                scale = min(ww / iw, wh / ih)
                pw = int(iw * scale)
                ph = int(ih * scale)
                ox = (ww - pw) // 2
                oy = (wh - ph) // 2
                new_rect = QRect(ox, oy, pw, ph)

        if self._pixmap_rect != new_rect:
            self._pixmap_rect = new_rect
            self.pixmap_rect_changed.emit(self._pixmap_rect)