from __future__ import annotations

from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import QImage, QPainter, QColor, QPaintEvent
from PySide6.QtWidgets import QWidget


class VideoDisplayWidget(QWidget):
    """
    SRP: Strictly renders the video frame and calculates layout geometry.
    It sits at the bottom of the QStackedLayout and ignores all mouse inputs.
    """

    # UPGRADED: Now broadcasts both the layout margins AND the true image dimensions
    pixmap_rect_changed = Signal(QRect, QSize)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
            img_size = QSize()
        else:
            img_size = self._image.size()
            iw, ih = img_size.width(), img_size.height()
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

        # Cache the emission so we don't spam the signal 30 times a second
        current_state = (new_rect, img_size)
        if not hasattr(self, "_last_emitted") or self._last_emitted != current_state:
            self._pixmap_rect = new_rect
            self._last_emitted = current_state
            self.pixmap_rect_changed.emit(self._pixmap_rect, img_size)