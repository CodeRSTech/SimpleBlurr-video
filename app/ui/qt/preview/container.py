# app/ui/qt/preview/container.py
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget, QStackedLayout, QSizePolicy

from app.ui.state.preview_state import ToolMode
from app.ui.qt.preview.layer_video import VideoDisplayWidget

from app.ui.qt.preview.layer_bbox import AnnotationOverlayWidget
from app.shared.logging_cfg import get_logger
from functools import wraps

logger = get_logger("UI->Preview->Container")

def logit(func):
    """
    A decorator that logs the execution of a function,
    including its name, arguments, and any exceptions.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Log the entry and arguments
        logger.debug(f"Executing '{func.__name__}' | args={args} | kwargs={kwargs}")

        try:
            # Execute the actual function
            result = func(*args, **kwargs)

            # Optional: Log successful completion or even the result
            logger.debug(f"Finished '{func.__name__}'")
            return result

        except Exception as e:
            # Loguru's .exception() automatically captures and formats the traceback
            logger.exception(f"An error occurred in '{func.__name__}': {e}")
            raise  # Re-raise the exception so it doesn't fail silently

    return wrapper


class PreviewContainer(QWidget):
    """
    SRP: Composes the Video Base Layer and Interactive Overlays using QStackedLayout.
    Acts as the single Facade API for the EditorController.
    """

    # --- Signals echoed up to the EditorController ---
    bbox_drawn = Signal(int, int, int, int)
    bbox_edited = Signal(str, int, int, int, int)
    bbox_deleted = Signal(str)
    context_action_triggered = Signal(str, str) # action_name, item_key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(640, 360)

        # 1. Instantiate the Layers
        self.video_layer = VideoDisplayWidget()
        self.bbox_layer = AnnotationOverlayWidget()

        # 2. Stack them (Top to Bottom)
        self._layout = QStackedLayout(self)
        self._layout.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self._layout.addWidget(self.bbox_layer)   # Index 0 (Top - Interactive)
        self._layout.addWidget(self.video_layer)  # Index 1 (Bottom - Visual)

        # 3. Internal Event Routing
        # When the video resizes and calculates new letterbox margins,
        # it tells the overlay so the bounding boxes scale perfectly.
        self.video_layer.pixmap_rect_changed.connect(self.bbox_layer.set_pixmap_rect)

        # Route the overlay's business signals up to the outside world
        self.bbox_layer.bbox_drawn.connect(self.bbox_drawn.emit)
        self.bbox_layer.bbox_edited.connect(self.bbox_edited.emit)
        self.bbox_layer.bbox_deleted.connect(self.bbox_deleted.emit)
        self.bbox_layer.context_action_triggered.connect(self.context_action_triggered.emit)

    # --- Public Facade API for EditorController ---

    @logit
    def set_image(self, image: QImage) -> None:
        """Passes the raw video frame down to the display layer."""
        self.video_layer.set_image(image)

    @logit
    def set_message(self, message: str) -> None:
        """Passes placeholder text down to the display layer."""
        self.video_layer.set_message(message)
        self.bbox_layer.cancel_edit()

    @logit
    def set_tool_mode(self, mode: ToolMode) -> None:
        """
        Changes the active interactive tool.
        In the future, if a Draw Polygon tool is added, this method would disable
        the bbox_layer's hit-testing and enable the polygon_layer's hit-testing.
        """
        self.bbox_layer.set_tool_mode(mode)

    @logit
    def set_active_bboxes(self, bboxes: dict[str, tuple[int, int, int, int]]) -> None:
        """Injects the live bounding boxes from the current data tab into the overlay."""
        self.bbox_layer.set_active_bboxes(bboxes)

    @logit
    def set_tracker_actions_enabled(self, enabled: bool) -> None:
        """
        Tells the overlay whether context menu items specific to tracking
        (e.g. 'Delete Next Occurrences') should be enabled.
        """
        self.bbox_layer.set_tracker_actions_enabled(enabled)

    @logit
    def cancel_active_edits(self) -> None:
        self.bbox_layer.cancel_edit()