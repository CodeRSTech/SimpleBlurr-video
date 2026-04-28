from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class PreviewWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self._image: QImage | None = None

        self._label = QLabel("No preview available")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setFrameShape(QFrame.Shape.StyledPanel)
        self._label.setMinimumSize(640, 360)

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)

    def set_message(self, message: str) -> None:
        self._image = None
        self._label.clear()
        self._label.setText(message)

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._refresh_pixmap()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_pixmap()

    def _refresh_pixmap(self) -> None:
        if self._image is None:
            return

        pixmap = QPixmap.fromImage(self._image)
        scaled = pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)
