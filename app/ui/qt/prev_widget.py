from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QColor, QCursor
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class PreviewWidget(QWidget):
    # Emitted with (x1, y1, x2, y2) in image-space pixels when a bbox draw is completed
    bbox_drawn = Signal(int, int, int, int)

    def __init__(self) -> None:
        super().__init__()

        self._image: QImage | None = None
        self._drawing_enabled: bool = False

        # Rubber-band state (widget-space)
        self._drag_start: QPoint | None = None
        self._drag_current: QPoint | None = None

        # The rect of the scaled pixmap within the label (for coordinate unprojection)
        self._pixmap_rect: QRect = QRect()

        self._label = QLabel("No preview available")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFrameShape(QFrame.Shape.StyledPanel)
        self._label.setMinimumSize(640, 360)

        # Mouse tracking is needed to update rubber-band during drag
        self._label.setMouseTracking(True)
        self._label.installEventFilter(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    # --- Public API ---

    def set_message(self, message: str) -> None:
        self._image = None
        self._label.clear()
        self._label.setText(message)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._refresh_pixmap()

    def set_drawing_enabled(self, enabled: bool) -> None:
        """Enable or disable interactive bbox drawing mode."""
        self._drawing_enabled = enabled
        self._drag_start = None
        self._drag_current = None
        cursor = QCursor(Qt.CursorShape.CrossCursor) if enabled else QCursor(Qt.CursorShape.ArrowCursor)
        self._label.setCursor(cursor)
        self._label.update()

    # --- Events ---

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_pixmap()

    def eventFilter(self, watched, event) -> bool:
        """Intercept mouse events on the label for rubber-band drawing."""
        if watched is not self._label or not self._drawing_enabled:
            return False

        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QMouseEvent

        if event.type() == QEvent.Type.MouseButtonPress:
            assert isinstance(event, QMouseEvent)
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_start = event.position().toPoint()
                self._drag_current = self._drag_start
                self._label.update()
                return True

        elif event.type() == QEvent.Type.MouseMove:
            assert isinstance(event, QMouseEvent)
            if self._drag_start is not None:
                self._drag_current = event.position().toPoint()
                self._label.update()
                return True

        elif event.type() == QEvent.Type.MouseButtonRelease:
            assert isinstance(event, QMouseEvent)
            if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
                self._drag_current = event.position().toPoint()
                self._finalise_bbox()
                return True

        elif event.type() == QEvent.Type.Paint:
            # Let the label paint itself first, then draw our overlay
            # We handle this by installing a custom paintEvent instead — see _refresh_pixmap
            pass

        return False

    # --- Private helpers ---

    def _refresh_pixmap(self) -> None:
        if self._image is None:
            return

        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Calculate where the scaled pixmap sits within the label (centered)
        lw, lh = self._label.width(), self._label.height()
        pw, ph = scaled.width(), scaled.height()
        ox = (lw - pw) // 2
        oy = (lh - ph) // 2
        self._pixmap_rect = QRect(ox, oy, pw, ph)

        if self._drawing_enabled and self._drag_start is not None and self._drag_current is not None:
            # Draw rubber-band overlay on top of the pixmap
            overlay = QPixmap(scaled)
            painter = QPainter(overlay)
            painter.setPen(QPen(QColor(255, 80, 80), 2, Qt.PenStyle.DashLine))

            # Clamp drag points to pixmap rect, then translate to pixmap-local space
            start = self._clamp_to_pixmap(self._drag_start)
            end = self._clamp_to_pixmap(self._drag_current)
            local_start = QPoint(start.x() - ox, start.y() - oy)
            local_end = QPoint(end.x() - ox, end.y() - oy)
            painter.drawRect(QRect(local_start, local_end).normalized())
            painter.end()
            self._label.setPixmap(overlay)
        else:
            self._label.setPixmap(scaled)

    def _clamp_to_pixmap(self, point: QPoint) -> QPoint:
        """Clamp a widget-space point to the pixmap rect boundaries."""
        r = self._pixmap_rect
        x = max(r.left(), min(point.x(), r.right()))
        y = max(r.top(), min(point.y(), r.bottom()))
        return QPoint(x, y)

    def _finalise_bbox(self) -> None:
        """Convert rubber-band rect to image-space coords and emit signal."""
        if self._drag_start is None or self._drag_current is None or self._image is None:
            self._drag_start = None
            self._drag_current = None
            return

        start = self._clamp_to_pixmap(self._drag_start)
        end = self._clamp_to_pixmap(self._drag_current)
        rect = QRect(start, end).normalized()

        # Must be non-trivial
        if rect.width() < 3 or rect.height() < 3:
            self._drag_start = None
            self._drag_current = None
            self._refresh_pixmap()
            return

        r = self._pixmap_rect
        scale_x = self._image.width() / r.width()
        scale_y = self._image.height() / r.height()

        x1 = int((rect.left() - r.left()) * scale_x)
        y1 = int((rect.top() - r.top()) * scale_y)
        x2 = int((rect.right() - r.left()) * scale_x)
        y2 = int((rect.bottom() - r.top()) * scale_y)

        # Clamp to image bounds
        iw, ih = self._image.width(), self._image.height()
        x1, x2 = max(0, x1), min(iw, x2)
        y1, y2 = max(0, y1), min(ih, y2)

        self._drag_start = None
        self._drag_current = None
        self.set_drawing_enabled(False)

        self.bbox_drawn.emit(x1, y1, x2, y2)
