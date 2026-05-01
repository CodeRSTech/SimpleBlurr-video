from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import Qt, Signal, QRect, QPoint, QSize
from PySide6.QtGui import (
    QImage, QPainter, QPen, QBrush, QColor, QCursor, QPaintEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

# --- Constants ---
_BOX_COLOR = QColor(255, 80, 80)
_CENTER_COLOR = QColor(255, 255, 255, 180)
_HANDLE_BORDER = QColor(200, 40, 40)
_HANDLE_COLOR = QColor(255, 255, 255)
_HANDLE_DRAW_R = 5  # px, visual radius of drawn dots
_HANDLE_RADIUS = 6  # px, hit-test radius for handle dots
_MIN_BBOX_PX = 4  # minimum bbox size in widget-space to be accepted


# --- Public Classes ---

class PreviewWidget(QWidget):
    """
    Video preview widget with interactive bounding-box drawing and handle-based visual editing.

    Signals:
        - ``bbox_drawn``: Emitted when a new bounding box is drawn.
          Provides image-space coordinates *(x1, y1, x2, y2)*.
        - ``bbox_edited``: Emitted when an existing bounding box is edited.
          Provides ``item_key``, and image-space coordinates *(x1, y1, x2, y2)*.

    Public Methods:
        - ``confirm_bbox()``: Confirms the current bounding box and emits the ``bbox_drawn`` signal.
        - ``set_drawing_enabled(enabled:bool)``: Enables/disables drawing mode.
        - ``set_active_bboxes(bboxes:dict[str,tuple[int,int,int,int]])``: Sets the active bounding boxes for editing.
          Expects a dictionary where keys are
          unique identifiers and values are tuples of (x1, y1, x2, y2) coordinates.
        - ``set_image(image:QImage)``: Sets the image to be displayed in the widget.
        - ``set_message(message:str)``: Displays a message in the center of the widget.
        - ``cancel_edit()``: Cancels the current edit operation and resets the widget state.

    Workflow:
        - **Instant Draw**: When drawing a new box, releasing the mouse instantly confirms
          the bounding box and emits the `bbox_drawn` signal.
        - **Click-to-Edit**: The preview widget is now dynamically fed a list of
          existing bounding boxes. Active bboxes now include boxes from **detection/trackers**
          based on the active tab. Clicking on or near one of these boxes on the canvas
          instantly makes it active, revealing its handles for visual resizing/moving.
    """

    # 1. Class-level constants / class variables
    bbox_drawn = Signal(int, int, int, int)  # image-space x1,y1,x2,y2
    bbox_edited = Signal(str, int, int, int, int)  # item_key, x1, y1, x2, y2

    # 2. __init__ (constructor)
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(QSize(640, 360))
        self.setMouseTracking(True)  # enable mouse tracking for precise drawing/hovering.

        self._image: QImage | None = None
        self._pixmap_rect: QRect = QRect()  # image render area in widget-space
        self._drawing_enabled: bool = False
        self._state = _BBoxState()
        self._placeholder_text: str = ""

        # Dictionary of active boxes mapping ID -> (x1, y1, x2, y2) in image space.
        # These are injected from the active tab (detection or trackers) in the main UI.
        self._active_bboxes: dict[str, tuple[int, int, int, int]] = {}

        # Tracks the ID of the existing box currently being visually edited
        self._editing_bbox_id: str | None = None

    # 4. Public methods
    # --- Public API ---
    def cancel_edit(self) -> None:
        """Resets all widget state, drops active boxes, and hides overlays."""
        self._editing_bbox_id = None
        self._state = _BBoxState()
        self._drawing_enabled = False
        self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()

    def confirm_bbox(self) -> None:
        """Programmatically confirm the current bbox."""
        self._emit_and_exit()

    def set_active_bboxes(self, bboxes: dict[str, tuple[int, int, int, int]]) -> None:
        """
        Injects the currently visible bounding boxes for click-to-edit hit testing.
        Active bboxes now includes boxes from detection/trackers based on the active tab.
        Called on every frame render by the EditorController.
        """
        self._active_bboxes = bboxes
        # If the box we are editing disappears (e.g. deleted or frame changed), cancel the edit.
        if self._editing_bbox_id and self._editing_bbox_id not in bboxes:
            self.cancel_edit()

    def set_drawing_enabled(self, enabled: bool) -> None:
        """
        Enable or disable fresh drawing of bounding boxes.
        When enabled, resets any active edits.
        """
        self._drawing_enabled = enabled
        self._editing_bbox_id = None
        self._state = _BBoxState()
        # The cursor becomes a crosshair so the user knows they can draw.
        cursor = Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        self.setCursor(QCursor(cursor))
        self.update()

    def set_image(self, image: QImage) -> None:
        self._image = image
        self._update_pixmap_rect()
        self.update()

    def set_message(self, message: str) -> None:
        self._image = None
        self._drawing_enabled = False
        self._state = _BBoxState()
        self.update()
        self._placeholder_text = message
        self.update()

    # --- Public Methods: Qt Event Overrides ---
    def keyPressEvent(self, event) -> None:
        """Handle Escape to cancel edits or drawing."""
        if self._drawing_enabled and event.key() == Qt.Key.Key_Escape:
            self.cancel_edit()
            return
        if self._drawing_enabled and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._state.has_valid_rect:
                self._emit_and_exit()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """
        Legacy double-click confirmation.
        Mostly bypassed by the new instant-release feature, but kept for fallback redundancy.
        """
        if self._drawing_disabled or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._state.has_valid_rect:
            self._emit_and_exit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """
        Handles mouse move events for drawing and handle-resizing.

        If drag mode is NONE: Updates the cursor if hovering over a handle.
        If drag mode is DRAW: Expands rect from the origin to the current mouse position.
        If drag mode is MOVE/HANDLE: Translates the rect or resizes a specific corner.
        """
        if self._drawing_disabled:
            return

        # Get mouse position in widget coordinates
        pos = event.position().toPoint()
        state = self._state

        # Hover state: update cursor based on what's under the pointer
        if state.drag_mode == _DragMode.NONE:
            if state.has_valid_rect:
                hit = self._hit_test_handle(pos)
                if hit != _DragMode.NONE:
                    self.setCursor(QCursor(_CORNER_CURSOR[hit]))
                elif state.rect.contains(pos):
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                else:
                    self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return

        clamped = self._clamp(pos)

        # Update rect state from origin to current mouse position
        if state.drag_mode == _DragMode.DRAW:
            state.rect = QRect(state.drag_origin, clamped).normalized()

        # Update rect state by moving it
        elif state.drag_mode == _DragMode.MOVE:
            delta = pos - state.drag_origin
            moved = state.rect_at_drag_start.translated(delta)
            moved = self._clamp_rect(moved)
            state.rect = moved

        # Update rect state by moving a specific handle
        else:
            state.rect = self._apply_handle_drag(
                state.rect_at_drag_start,
                state.drag_mode,
                pos - state.drag_origin,
            )
        # Schedule a repaint to reflect the new rect state live
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        Handles mouse press events for interacting with boxes.

        Working steps:
            1. Active Interaction: If we are ALREADY editing a box, check if we clicked
               a handle or its interior. If so, update drag_mode and exit.
            2. Click-to-Edit (New Feature): If NOT clicking an already active box, query
               `_active_bboxes` to see if we clicked near an existing bounding box on screen.
            3. Hijack Box: If a close existing box is found, set it to `state.rect`, store
               its ID, and enter visual editing mode automatically.
            4. Start Fresh Draw: If no existing box is hit, start drawing a fresh box.
        """
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position().toPoint()
        state = self._state

        # 1. Interact with currently active rect (Move or Handle Drag)
        if state.has_valid_rect:
            hit = self._hit_test_handle(pos)
            if hit != _DragMode.NONE:
                state.drag_mode = hit
                state.drag_origin = pos
                state.rect_at_drag_start = QRect(state.rect)
                return
            if state.rect.contains(pos):
                state.drag_mode = _DragMode.MOVE
                state.drag_origin = pos
                state.rect_at_drag_start = QRect(state.rect)
                return

        # 2. FEATURE 2: Click-to-edit an existing spatial box
        if self._active_bboxes:
            closest_id = None
            min_dist = float('inf')
            closest_rect = None

            for bbox_id, (x1, y1, x2, y2) in self._active_bboxes.items():
                rect = self._image_rect_to_widget_space(x1, y1, x2, y2)
                if rect.isNull():
                    continue

                if rect.contains(pos):
                    closest_id = bbox_id
                    closest_rect = rect
                    min_dist = 0
                    break  # Direct hit inside a box
                else:
                    # Calculate squared distance to center for proximity checking
                    cx, cy = rect.center().x(), rect.center().y()
                    dist = (pos.x() - cx) ** 2 + (pos.y() - cy) ** 2
                    if dist < min_dist:
                        min_dist = dist
                        closest_id = bbox_id
                        closest_rect = rect

            # Snap threshold: Direct hit inside OR within a ~50px radius squared
            if closest_id and (min_dist == 0 or min_dist < 2500):
                self._editing_bbox_id = closest_id
                state.rect = closest_rect

                # If clicked directly inside, allow immediate movement
                state.drag_mode = _DragMode.MOVE if min_dist == 0 else _DragMode.NONE
                state.drag_origin = pos
                state.rect_at_drag_start = QRect(state.rect)
                self._drawing_enabled = True  # Auto-engage edit mode visually
                self.update()
                return

        # 3. If we clicked empty space while editing, cancel the edit
        if self._editing_bbox_id is not None:
            self.cancel_edit()

        # 4. Fallback: Start fresh draw (Only if app explicitly enabled drawing mode)
        if self._drawing_enabled and self._editing_bbox_id is None:
            clamped = self._clamp(pos)
            state.rect = QRect(clamped, clamped)
            state.drag_mode = _DragMode.DRAW
            state.drag_origin = clamped
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """
        Handles mouse release.

        New Implementation Workflow:
        - If drawing a new box: Instantly confirms it upon release, bypassing the old
          double-click requirement. Emits `bbox_drawn`.
        - If moving/resizing an existing box: Emits the new coordinates via `bbox_edited`
          so the controller can securely update the backend.
        """
        if event.button() != Qt.MouseButton.LeftButton:
            return

        state = self._state

        # FEATURE 1: Instant confirmation for drawn boxes
        if state.drag_mode == _DragMode.DRAW:
            if state.rect.width() < _MIN_BBOX_PX or state.rect.height() < _MIN_BBOX_PX:
                # Too small — cancel
                state.rect = QRect()
                self._drawing_enabled = False
                self.update()
            else:
                # Instantly confirm, skipping the double-click edit phase
                self._emit_and_exit()

            state.drag_mode = _DragMode.NONE
            return

        # FEATURE 2: Emit update when an existing box is modified
        # If we had a box selected and we just finished moving/resizing it
        if self._editing_bbox_id is not None and state.drag_mode != _DragMode.NONE:
            x1, y1, x2, y2 = self._widget_rect_to_image_space(state.rect)
            self.bbox_edited.emit(self._editing_bbox_id, x1, y1, x2, y2)

        state.drag_mode = _DragMode.NONE

    def paintEvent(self, event: QPaintEvent) -> None:
        """
        Paints the preview widget by drawing the background, image, and overlay.
        The image is drawn scaled to fit ``_pixmap_rect`` in one call.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # 1. Dark background (fills letterbox bars if any)
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        # 2. The video frame image
        if self._image is not None:
            painter.drawImage(self._pixmap_rect, self._image)
        else:
            text = getattr(self, "_placeholder_text", "No preview available")
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

        # 3. Overlay — only if drawing mode is active AND a rect exists
        if self._drawing_enabled and self._state.has_valid_rect:
            self._paint_overlay(painter)

        painter.end()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_pixmap_rect()

    # 5. Protected methods
    @property
    def _drawing_disabled(self) -> bool:
        return not self._drawing_enabled

    # --- Protected Methods: Actions ---
    def _emit_and_exit(self) -> None:
        """
        Emit the bbox_drawn signal with the final bounding box coordinates.
        Called immediately upon mouse release for fresh draws.
        """
        # If we are in edit mode for an existing box, don't emit a fresh draw
        if self._editing_bbox_id is not None:
            self.cancel_edit()
            return

        x1, y1, x2, y2 = self._widget_rect_to_image_space(self._state.rect)
        self.cancel_edit()  # resets drawing enabled to False
        self.bbox_drawn.emit(x1, y1, x2, y2)

    # --- Protected Methods: Drawing ---
    def _paint_overlay(self, painter: QPainter) -> None:
        """Draws the bounding box and handles on top of the image."""
        rect = self._state.rect

        # --- Box: The red rectangle ---
        pen = QPen(_BOX_COLOR, 2, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # --- Center move icon: dot with crosshair lines ---
        cx = rect.center().x()
        cy = rect.center().y()
        painter.setPen(QPen(_BOX_COLOR, 1))
        painter.setBrush(QBrush(_CENTER_COLOR))
        r = _HANDLE_DRAW_R + 2
        painter.drawEllipse(QPoint(cx, cy), r, r)

        a = r - 2
        painter.setPen(QPen(_HANDLE_BORDER, 1))
        painter.drawLine(cx - a, cy, cx + a, cy)
        painter.drawLine(cx, cy - a, cx, cy + a)

        # --- Hint text (only while first draw in progress) ---
        if self._state.drag_mode == _DragMode.DRAW:
            painter.setPen(QColor(255, 255, 255, 200))
            font = painter.font()
            font.setPointSize(9)
            painter.setFont(font)
            painter.drawText(
                rect.bottomLeft() + QPoint(4, 14),
                "Release to confirm  •  Esc to cancel"
            )

        # --- Handles: Eight handle dots ---
        for pt in self._handle_points(rect):
            painter.setPen(QPen(_HANDLE_BORDER, 1))
            painter.setBrush(QBrush(_HANDLE_COLOR))
            painter.drawEllipse(pt, _HANDLE_DRAW_R, _HANDLE_DRAW_R)

    # --- Protected Methods: Geometry Helpers ---
    def _apply_handle_drag(self, base: QRect, mode: _DragMode, delta: QPoint) -> QRect:
        """
        Return a new normalized ``rect`` after moving one handle by ``delta``.
        The delta is computed against rect_at_drag_start to avoid drift accumulation.
        """
        x1, y1, x2, y2 = base.left(), base.top(), base.right(), base.bottom()
        dx, dy = delta.x(), delta.y()
        pr = self._pixmap_rect

        def clamp_x(v: int) -> int:
            return max(pr.left(), min(v, pr.right()))

        def clamp_y(v: int) -> int:
            return max(pr.top(), min(v, pr.bottom()))

        if mode == _DragMode.TOP_LEFT:
            x1, y1 = clamp_x(x1 + dx), clamp_y(y1 + dy)
        elif mode == _DragMode.TOP_RIGHT:
            x2, y1 = clamp_x(x2 + dx), clamp_y(y1 + dy)
        elif mode == _DragMode.BOT_LEFT:
            x1, y2 = clamp_x(x1 + dx), clamp_y(y2 + dy)
        elif mode == _DragMode.BOT_RIGHT:
            x2, y2 = clamp_x(x2 + dx), clamp_y(y2 + dy)
        elif mode == _DragMode.TOP:
            y1 = clamp_y(y1 + dy)
        elif mode == _DragMode.BOTTOM:
            y2 = clamp_y(y2 + dy)
        elif mode == _DragMode.LEFT:
            x1 = clamp_x(x1 + dx)
        elif mode == _DragMode.RIGHT:
            x2 = clamp_x(x2 + dx)

        return QRect(QPoint(x1, y1), QPoint(x2, y2)).normalized()

    def _clamp(self, point: QPoint) -> QPoint:
        """Clamp a point to the bounds of the pixmap rect."""
        r = self._pixmap_rect
        return QPoint(
            max(r.left(), min(point.x(), r.right())),
            max(r.top(), min(point.y(), r.bottom())),
        )

    def _clamp_rect(self, rect: QRect) -> QRect:
        """Translate ``rect`` so it stays fully inside ``_pixmap_rect``."""
        pr = self._pixmap_rect
        r = rect.normalized()
        dx = dy = 0
        if r.left() < pr.left():   dx = pr.left() - r.left()
        if r.right() > pr.right():  dx = pr.right() - r.right()
        if r.top() < pr.top():    dy = pr.top() - r.top()
        if r.bottom() > pr.bottom(): dy = pr.bottom() - r.bottom()
        return r.translated(dx, dy)

    def _hit_test_handle(self, pos: QPoint) -> _DragMode:
        """
        Determines the drag mode based on the cursor position relative to the handles.
        Uses manhattanLength for fast distance checking.
        """
        rect = self._state.rect
        x1, y1 = rect.left(), rect.top()
        x2, y2 = rect.right(), rect.bottom()
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        r = _HANDLE_RADIUS

        handles: list[tuple[QPoint, _DragMode]] = [
            (QPoint(x1, y1), _DragMode.TOP_LEFT),
            (QPoint(x2, y1), _DragMode.TOP_RIGHT),
            (QPoint(x1, y2), _DragMode.BOT_LEFT),
            (QPoint(x2, y2), _DragMode.BOT_RIGHT),
            (QPoint(mx, y1), _DragMode.TOP),
            (QPoint(mx, y2), _DragMode.BOTTOM),
            (QPoint(x1, my), _DragMode.LEFT),
            (QPoint(x2, my), _DragMode.RIGHT),
        ]
        for pt, mode in handles:
            if (pos - pt).manhattanLength() <= r * 2:
                return mode
        return _DragMode.NONE

    def _image_rect_to_widget_space(self, x1: int, y1: int, x2: int, y2: int) -> QRect:
        """
        Convert image-space coordinates back to widget-space rect.
        Required to visually overlay existing bounding boxes accurately.
        """
        r = self._pixmap_rect
        if r.width() == 0 or r.height() == 0 or self._image is None:
            return QRect()
        sx = r.width() / self._image.width()
        sy = r.height() / self._image.height()

        wx1 = int((x1 * sx) + r.left())
        wy1 = int((y1 * sy) + r.top())
        wx2 = int((x2 * sx) + r.left())
        wy2 = int((y2 * sy) + r.top())
        return QRect(QPoint(wx1, wy1), QPoint(wx2, wy2)).normalized()

    def _update_pixmap_rect(self) -> None:
        """Calculate the letterboxed rectangle where the actual image is drawn."""
        if self._image is None:
            return
        iw, ih = self._image.width(), self._image.height()
        ww, wh = self.width(), self.height()
        if iw == 0 or ih == 0 or ww == 0 or wh == 0:
            return
        scale = min(ww / iw, wh / ih)
        pw = int(iw * scale)
        ph = int(ih * scale)
        ox = (ww - pw) // 2
        oy = (wh - ph) // 2
        self._pixmap_rect = QRect(ox, oy, pw, ph)

    def _widget_rect_to_image_space(self, rect: QRect) -> tuple[int, int, int, int]:
        """Convert a widget-space rect to true image-space pixel coordinates."""
        r = self._pixmap_rect
        if r.width() == 0 or r.height() == 0 or self._image is None:
            return 0, 0, 0, 0
        sx = self._image.width() / r.width()
        sy = self._image.height() / r.height()

        # Subtract letterbox offset before scaling
        x1 = int((rect.left() - r.left()) * sx)
        y1 = int((rect.top() - r.top()) * sy)
        x2 = int((rect.right() - r.left()) * sx)
        y2 = int((rect.bottom() - r.top()) * sy)
        iw, ih = self._image.width(), self._image.height()
        return max(0, x1), max(0, y1), min(iw, x2), min(ih, y2)

    # 7. Static methods
    @staticmethod
    def _handle_points(rect: QRect) -> list[QPoint]:
        """Computes all 8 handle positions from the rect's corners and midpoints."""
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        return [
            QPoint(x1, y1), QPoint(mx, y1), QPoint(x2, y1),
            QPoint(x1, my), QPoint(x2, my),
            QPoint(x1, y2), QPoint(mx, y2), QPoint(x2, y2),
        ]


# --- Internal Helpers ---

class _DragMode(Enum):
    """Enum for the different drag modes."""
    NONE = auto()
    DRAW = auto()
    MOVE = auto()
    TOP_LEFT = auto()
    TOP_RIGHT = auto()
    BOT_LEFT = auto()
    BOT_RIGHT = auto()
    TOP = auto()
    BOTTOM = auto()
    LEFT = auto()
    RIGHT = auto()


_CORNER_CURSOR = {
    _DragMode.TOP_LEFT: Qt.CursorShape.SizeFDiagCursor,
    _DragMode.TOP_RIGHT: Qt.CursorShape.SizeBDiagCursor,
    _DragMode.BOT_LEFT: Qt.CursorShape.SizeBDiagCursor,
    _DragMode.BOT_RIGHT: Qt.CursorShape.SizeFDiagCursor,
    _DragMode.TOP: Qt.CursorShape.SizeVerCursor,
    _DragMode.BOTTOM: Qt.CursorShape.SizeVerCursor,
    _DragMode.LEFT: Qt.CursorShape.SizeHorCursor,
    _DragMode.RIGHT: Qt.CursorShape.SizeHorCursor,
    _DragMode.MOVE: Qt.CursorShape.SizeAllCursor,
}


@dataclass
class _BBoxState:
    """Mutable state for the in-progress bbox, tracked in widget-space."""
    rect: QRect = field(default_factory=QRect)
    drag_mode: _DragMode = _DragMode.NONE
    drag_origin: QPoint = field(default_factory=QPoint)
    rect_at_drag_start: QRect = field(default_factory=QRect)

    @property
    def has_valid_rect(self) -> bool:
        return not self.rect.isNull()