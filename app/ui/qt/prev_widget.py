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
    Video preview widget with interactive bounding-box drawing and handle-based resizing.

    Workflow:
        1. Call ``set_drawing_enabled(True)`` to enter drawing mode.
        2. User draws a ``rect`` by clicking and dragging on the image.
        3. Handles appear; user can refine by dragging corners/edges or move the whole box.
        4. On double-click (or external call to ``confirm_bbox()`` ), ``bbox_drawn`` is emitted
           with image-space (x1, y1, x2, y2) coordinates and drawing mode is exited.
        5. Press Escape to cancel without emitting.
    """

    # 1. Class-level constants / class variables
    bbox_drawn = Signal(int, int, int, int)  # image-space x1,y1,x2,y2

    # 2. __init__ (constructor)
    def __init__(self) -> None:
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(QSize(640, 360))
        self.setMouseTracking(True) # enable mouse tracking for precise drawing.

        self._image: QImage | None = None
        self._pixmap_rect: QRect = QRect()  # image render area in widget-space
        self._drawing_enabled: bool = False
        self._state = _BBoxState()
        self._placeholder_text: str = ""

    # 3. Public properties (None)
    @property
    def _drawing_disabled(self) -> bool:
        return not self._drawing_enabled

    # 4. Public methods
    # --- Public API ---
    def confirm_bbox(self) -> None:
        """Programmatically confirm the current bbox (same as double-click)."""
        self._emit_and_exit()

    def set_drawing_enabled(self, enabled: bool) -> None:
        """
        Enable or disable drawing of bounding boxes.

        When disabled, the widget will not respond to mouse events for drawing.

        This is the very first step in the drawing workflow.

        ``set_drawing_enabled(True)``
            → ``_state`` reset, ``cursor = crosshair``, ``update()``

        ``mousePressEvent``: *[user presses the mouse button]*
            → ``_clamp(pos)``
                → ``drag_origin`` set,
                ``rect`` = zero-size ``QRect``,
                ``drag_mode`` = ``DRAW``

        ``mouseMoveEvent`` *[user moves mouse — fires many times]*
            → ``state.rect`` = ``QRect(origin,clamped_pos).normalized()``
            → ``self.update()``
                → ``paintEvent``
                    → ``drawImage(_pixmap_rect, _image)``
                    → ``_paint_overlay`` → ``drawRect``, ``drawEllipse`` ×8

        ``mouseReleaseEvent`` *[user releases mouse]*
            → ``size`` check → ``drag_mode = NONE``

        *[user drags a handle — repeat move cycle above with different drag_mode]*

        ``mouseDoubleClickEvent`` / ``keyPressEvent`` *[user double-clicks or presses ``Enter``]*
            → ``_emit_and_exit()``
                → ``_widget_rect_to_image_space`` → image-space coords
                → ``set_drawing_enabled(False)``
                → ``bbox_drawn.emit(x1, y1, x2, y2)``
                    → ``AnnotationHandler._on_bbox_drawn``
                        → ``add_manual_frame_item(session_id, label, bbox_xyxy)``
                        → ``render_fn(session_id)``
        """
        self._drawing_enabled = enabled
        self._state = _BBoxState() # reset bbox state (rect becomes a null QRect, drag mode is NONE).
        # The cursor becomes a crosshair so the user knows they can draw.
        cursor = Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        self.setCursor(QCursor(cursor))
        # ask Qt to repaint — but there's nothing to draw yet, so the widget just shows the image
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
        # We no longer use a QLabel; just repaint with text
        self._placeholder_text = message
        self.update()

    # --- Public Methods: Qt Event Overrides ---
    def keyPressEvent(self, event) -> None:
        if self._drawing_enabled and event.key() == Qt.Key.Key_Escape:
            self.set_drawing_enabled(False)
            return
        if self._drawing_enabled and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._state.has_valid_rect:
                self._emit_and_exit()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._drawing_disabled or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._state.has_valid_rect:
            self._emit_and_exit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """
        Handles mouse move events for drawing and interaction with the preview widget.
        Updates the drag mode and position based on the mouse movement.

        In ``mouseMoveEvent``,
        when ``drag_mode`` is a handle,
        ``_apply_handle_drag`` is called.
        """
        if self._drawing_disabled:
            return

        # Get mouse position in widget coordinates
        pos = event.position().toPoint()
        state = self._state

        # If drag mode is NONE and rect exists
        if state.drag_mode == _DragMode.NONE:
            # Hover: update cursor based on what's under the pointer
            if state.has_valid_rect:
                hit = self._hit_test_handle(pos)
                # If a handle is hit, change cursor to the appropriate one
                if hit != _DragMode.NONE:
                    self.setCursor(QCursor(_CORNER_CURSOR[hit]))
                elif state.rect.contains(pos):
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                else:
                    self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return

        # clamp mouse position to pixmap bounds
        clamped = self._clamp(pos)

        # If drag mode is DRAW, update rect state from origin to current mouse position
        if state.drag_mode == _DragMode.DRAW:
            # Expand rect from the origin to the current mouse position.
            # QRect can be constructed from two QPoints regardless of which is top-left or bottom-right.
            # ``.normalized()`` ensures that if the user drags left or upward,
            # the rect's coordinates are corrected so left < right and top < bottom
            # — without this, the rect would have negative dimensions and draw incorrectly.
            state.rect = QRect(state.drag_origin, clamped).normalized()

        # If drag mode is MOVE, update rect state by moving it
        elif state.drag_mode == _DragMode.MOVE:
            delta = pos - state.drag_origin
            moved = state.rect_at_drag_start.translated(delta)
            # Clamp movement so rect stays within pixmap
            moved = self._clamp_rect(moved)
            state.rect = moved

        # If drag mode is a handle, update rect state by moving the handle
        else:
            # Handle resize
            state.rect = self._apply_handle_drag(
                state.rect_at_drag_start,
                state.drag_mode,
                pos - state.drag_origin,
            )
        #schedules a repaint. Qt coalesces these calls
        # — it won't repaint 200 times a second,
        # it repaints as fast as it can sensibly render.
        # This is how the box appears live while dragging
        self.update() # ← Update to reflect the new rect state

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        Handles mouse press events for drawing and interaction with the preview widget.

        Runs only if drawing is enabled and the left mouse button is pressed.

        Working steps:
            1. Get the mouse position ``pos`` by converting the ``event`` position to ``QPoint``.

            2. If the current `` state `` has a valid rectangle.
                2.1. Check handle:
                    2.1.1. If the handle is **not** ``NONE``,
                    2.1.2. Update state's ``drag_mode`` to that handle,
                    ``drag_origin`` to ``pos``, and
                    ``rect_at_drag_start`` to ``state.rect``.
                    2.1.3. Exit the function.

                    2.1.4. If the handle is ``NONE`` and,
                    current state's ``rect`` contains ``pos``,
                    2.1.5. Update state's ``drag_mode`` to ``MOVE``,
                    ``drag_origin`` to ``pos``, and
                    ``rect_at_drag_start`` to ``state.rect``.
                    2.1.6. Exit the function.
            3. If the current `` state `` does NOT have a valid rectangle.
                3.1. Start a fresh draw by setting
                ``state.rect`` to the current ``pos`` and
                ``state.drag_mode`` to ``DRAW``.
                3.2. Exit the function.
        """
        if self._drawing_disabled or event.button() != Qt.MouseButton.LeftButton:
            # TODO: update this to choose bbox coinciding with the mouse cursor
            return

        pos = event.position().toPoint()
        state = self._state

        if state.has_valid_rect:
            # Check handles first, then interior move, then new draw
            hit = self._hit_test_handle(pos)
            if hit != _DragMode.NONE:   # if a handle is hit, start dragging it from `pos`
                state.drag_mode = hit
                state.drag_origin = pos
                state.rect_at_drag_start = QRect(state.rect)
                return
            if state.rect.contains(pos):
                state.drag_mode = _DragMode.MOVE
                state.drag_origin = pos
                state.rect_at_drag_start = QRect(state.rect)
                return

        # Start a fresh draw
        clamped = self._clamp(pos)
        state.rect = QRect(clamped, clamped)
        state.drag_mode = _DragMode.DRAW
        state.drag_origin = clamped
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drawing_disabled or event.button() != Qt.MouseButton.LeftButton:
            return
        state = self._state
        if state.drag_mode == _DragMode.DRAW:
            if state.rect.width() < _MIN_BBOX_PX or state.rect.height() < _MIN_BBOX_PX:
                # Too small — cancel
                state.rect = QRect()
                self.update()

        # After this,
        # `drag_mode` is `NONE` but `state.rect` is non-null.
        # The handles are still painted.
        # The widget is now in its editing phase
        state.drag_mode = _DragMode.NONE

    def paintEvent(self, event: QPaintEvent) -> None:
        """
        Paints the preview widget by drawing the background, image, and overlay based on the current state.

        Every time ``self.update()`` is called from ``mouseMoveEvent``,
        Qt eventually calls ``paintEvent``, where everything is actually drawn.

        A ``QPainter`` object is used to draw the widget.

        ``painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)`` is used to smooth the image rendering.

        The image is drawn using ``painter.drawImage(self._pixmap_rect, self._image)``,
        which draws the image **scaled** to fit ``_pixmap_rect`` in one call.
        No intermediate ``QPixmap`` is created on every frame.

        Then ``_paint_overlay`` draws the box and handles on top.
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
    # --- Protected Methods: Actions ---
    def _emit_and_exit(self) -> None:
        """
        Emit the bbox_drawn signal with the final bounding box coordinates,
        and exit drawing mode.

        Called when the user double-clicks or presses Enter.
        """
        x1, y1, x2, y2 = self._widget_rect_to_image_space(self._state.rect)
        self.set_drawing_enabled(False)
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
        # Draw a small four-way arrow glyph as crosshair lines
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
                "Double-click or Enter to confirm  •  Esc to cancel"
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

        The ``delta`` is always computed against ``rect_at_drag_start`` (the snapshot taken at press),
        **not** the current ``rect``.
        This avoids **drift accumulation** —
        where small rounding errors compound across hundreds of move events.
        """
        x1, y1, x2, y2 = base.left(), base.top(), base.right(), base.bottom()
        dx, dy = delta.x(), delta.y()
        pr = self._pixmap_rect

        def clamp_x(v: int) -> int:
            return max(pr.left(), min(v, pr.right()))

        def clamp_y(v: int) -> int:
            return max(pr.top(), min(v, pr.bottom()))

        if mode == _DragMode.TOP_LEFT:
            x1, y1 = clamp_x(x1 + dx), clamp_y(y1 + dy) # Moves both X and Y axes
        elif mode == _DragMode.TOP_RIGHT:
            x2, y1 = clamp_x(x2 + dx), clamp_y(y1 + dy)
        elif mode == _DragMode.BOT_LEFT:
            x1, y2 = clamp_x(x1 + dx), clamp_y(y2 + dy)
        elif mode == _DragMode.BOT_RIGHT:
            x2, y2 = clamp_x(x2 + dx), clamp_y(y2 + dy)
        elif mode == _DragMode.TOP:
            y1 = clamp_y(y1 + dy)   # Moves only Y
        elif mode == _DragMode.BOTTOM:
            y2 = clamp_y(y2 + dy)
        elif mode == _DragMode.LEFT:
            x1 = clamp_x(x1 + dx)
        elif mode == _DragMode.RIGHT: # Moves only X
            x2 = clamp_x(x2 + dx)

        return QRect(QPoint(x1, y1), QPoint(x2, y2)).normalized()

    def _clamp(self, point: QPoint) -> QPoint:
        """
        Clamp a point to the bounds of the pixmap rect.

        Ensures the point remains within the visible area of the image.
        """
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
        Determines the drag mode based on the position of the mouse cursor relative to the preview widget's handles.

        ``_hit_test_handle`` checks each of the 8 handle points using ``manhattanLength``
        (faster than Euclidean distance, fine for small areas):

        Returns the corresponding drag mode or None if no handle is hit.
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

    def _update_pixmap_rect(self) -> None:
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
        """
        Convert a widget-space rect to image-space coordinates.

        This is a **critical step** because,
        the ``rect`` is in **widget pixels** and,
        the application needs **image pixels**.

        Returns (x1, y1, x2, y2) in image-space coordinates.
        """
        r = self._pixmap_rect
        if r.width() == 0 or r.height() == 0 or self._image is None:
            return 0, 0, 0, 0
        sx = self._image.width() / r.width()
        sy = self._image.height() / r.height()

        # Why subtract `r.left()` and `r.top()`` first?
        # Because `_pixmap_rect` is offset from the widget's top-left by the letterbox margins.
        # If you don't subtract the offset before scaling,
        # every coordinate would be wrong by a margin-sized amount.
        x1 = int((rect.left() - r.left()) * sx)
        y1 = int((rect.top() - r.top()) * sy)
        x2 = int((rect.right() - r.left()) * sx)
        y2 = int((rect.bottom() - r.top()) * sy)
        iw, ih = self._image.width(), self._image.height()

        # The signal `bbox_drawn` fires with these image-space coordinates.
        # `AnnotationHandler._on_bbox_drawn` receives them and calls `add_manual_frame_item`.
        return max(0, x1), max(0, y1), min(iw, x2), min(ih, y2)

    # 7. Static methods
    @staticmethod
    def _handle_points(rect: QRect) -> list[QPoint]:
        """
        Computes all 8 positions from the rect's corners and midpoints:
        """
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        return [
            QPoint(x1, y1), QPoint(mx, y1), QPoint(x2, y1),  # TopLeft, Top, TopRight
            QPoint(x1, my), QPoint(x2, my),                  # Left, Middle, Right
            QPoint(x1, y2), QPoint(mx, y2), QPoint(x2, y2),  # BottomLeft, Bottom, BottomRight
        ]

# --- Internal Helpers ---

class _DragMode(Enum):
    """Enum for the different drag modes.

    Types of drag modes:

    - ``NONE``: No drag in progress (rect may still be present)
    - ``DRAW``: Creating a new rect from scratch.
    - ``MOVE``: Dragging the whole rect.

    - ``TOP_LEFT``: Top-left corner.
    - ``TOP_RIGHT``: Top-right corner.
    - ``BOT_LEFT``: Bottom-left corner.
    - ``BOT_RIGHT``: Bottom-right corner.

    - ``TOP``: Top-edge midpoint.
    - ``BOTTOM``: Bottom-edge midpoint.
    - ``LEFT``: Left-edge midpoint.
    - ``RIGHT``: Right-edge midpoint.
    """

    NONE = auto()  # no drag in progress (bounding box may still be visible)
    DRAW = auto()  # creating a new rect from scratch
    MOVE = auto()  # dragging the whole rect
    # Handles — corners
    TOP_LEFT = auto()   # top-left corner
    TOP_RIGHT = auto()  # top-right corner
    BOT_LEFT = auto()   # bottom-left corner
    BOT_RIGHT = auto()  # bottom-right corner
    # Handles — edge midpoints
    TOP = auto()    # top-edge midpoint
    BOTTOM = auto() # bottom-edge midpoint
    LEFT = auto()   # left-edge midpoint
    RIGHT = auto()  # right-edge midpoint


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
    """All mutable states for the in-progress bbox, in widget-space."""
    rect: QRect = field(default_factory=QRect)  # always normalised.
    drag_mode: _DragMode = _DragMode.NONE  # current drag mode, defaults to NONE (no drag in progress).
    drag_origin: QPoint = field(default_factory=QPoint) # start point of drag operation.
    rect_at_drag_start: QRect = field(default_factory=QRect) # rect at drag start, used for handle-based resizing.

    @property
    def has_valid_rect(self) -> bool:
        return not self.rect.isNull()