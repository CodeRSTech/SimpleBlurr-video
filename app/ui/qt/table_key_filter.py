from __future__ import annotations

from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QKeyEvent

from app.ui.handlers.annotation_handler import AnnotationHandler


class FrameTableKeyFilter(QObject):
    def __init__(self, annotation_handler: AnnotationHandler, render_fn) -> None:
        super().__init__()
        self._handler = annotation_handler
        self._render_fn = render_fn

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            return self._handler.handle_nudge_key(event, self._render_fn)
        return False
