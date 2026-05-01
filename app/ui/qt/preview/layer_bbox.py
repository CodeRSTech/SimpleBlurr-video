# app/ui/qt/preview/layer_bbox.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import Qt, Signal, QRect, QPoint, QSize
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QCursor, QPaintEvent,
    QMouseEvent, QContextMenuEvent
)
from PySide6.QtWidgets import QWidget, QMenu

from app.ui.state.preview_state import ToolMode

# --- Constants ---
_BOX_COLOR = QColor(255, 80, 80)
_CENTER_COLOR = QColor(255, 255, 255, 180)
_HANDLE_BORDER = QColor(200, 40, 40)
_HANDLE_COLOR = QColor(255, 255, 255)
_HANDLE_DRAW_R = 5
_HANDLE_RADIUS = 6
_MIN_BBOX_PX = 4


class AnnotationOverlayWidget(QWidget):
    """
    SRP: Handles interactive drawing, hit-testing, tool modes, and the context menu.
    Sits completely transparently over the video display.
    """

    # --- Signals ---
    bbox_drawn = Signal(int, int, int, int)  # x1, y1, x2, y2
    bbox_edited = Signal(str, int, int, int, int)  # item_key, x1, y1, x2, y2
    bbox_deleted = Signal(str)  # item_key
    context_action_triggered = Signal(str, str)  # action_name, item_key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        # Keeps background transparent so the video shows through
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._pixmap_rect: QRect = QRect()
        self._image_size: QSize | None = None
        self._state = _BBoxState()

        self._tool_mode: ToolMode = ToolMode.EDIT
        self._active_bboxes: dict[str, tuple[int, int, int, int]] = {}
        self._editing_bbox_id: str | None = None
        self._tracker_actions_enabled: bool = False

    # --- Public API for Coordinator ---

    def set_pixmap_rect(self, rect: QRect) -> None:
        """Called by the Coordinator when the underlying video resizes."""
        self._pixmap_rect = rect
        self.update()

    def set_image_size(self, size: QSize) -> None:
        """Called by the Coordinator to supply raw video dimensions for coordinate math."""
        self._image_size = size

    def set_active_bboxes(self, bboxes: dict[str, tuple[int, int, int, int]]) -> None:
        self._active_bboxes = bboxes
        if self._editing_bbox_id and self._editing_bbox_id not in bboxes:
            self.cancel_edit()
        self.update()

    def set_tool_mode(self, mode: ToolMode) -> None:
        self._tool_mode = mode
        self.cancel_edit()

        if mode == ToolMode.ADD:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def set_tracker_actions_enabled(self, enabled: bool) -> None:
        """Enables tracker-specific context menu options like 'Delete Next Occurrences'."""
        self._tracker_actions_enabled = enabled

    def cancel_edit(self) -> None:
        self._editing_bbox_id = None
        self._state = _BBoxState()
        if self._tool_mode != ToolMode.ADD:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.update()

    # --- Mouse Event Handlers ---

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        pos = event.position().toPoint()
        state = self._state

        # MODE: ADD
        if self._tool_mode == ToolMode.ADD:
            clamped = self._clamp(pos)
            state.rect = QRect(clamped, clamped)
            state.drag_mode = _DragMode.DRAW
            state.drag_origin = clamped
            self.update()
            return

        # MODE: DELETE
        if self._tool_mode == ToolMode.DELETE:
            hit_id, _ = self._get_bbox_at_pos(pos)
            if hit_id:
                self.bbox_deleted.emit(hit_id)
            return

        # MODE: EDIT
        if self._tool_mode == ToolMode.EDIT:
            # 1. Interact with currently active rect handles/move
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

            # 2. Try to grab a new box
            hit_id, hit_rect = self._get_bbox_at_pos(pos)
            if hit_id and hit_rect:
                self._editing_bbox_id = hit_id
                state.rect = hit_rect
                state.drag_mode = _DragMode.MOVE if hit_rect.contains(pos) else _DragMode.NONE
                state.drag_origin = pos
                state.rect_at_drag_start = QRect(state.rect)
                self.update()
                return

            # 3. Clicked empty space
            self.cancel_edit()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position().toPoint()
        state = self._state

        if state.drag_mode == _DragMode.NONE:
            if self._tool_mode == ToolMode.EDIT and state.has_valid_rect:
                hit = self._hit_test_handle(pos)
                if hit != _DragMode.NONE:
                    self.setCursor(QCursor(_CORNER_CURSOR[hit]))
                elif state.rect.contains(pos):
                    self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
                else:
                    self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            return

        clamped = self._clamp(pos)

        if state.drag_mode == _DragMode.DRAW:
            state.rect = QRect(state.drag_origin, clamped).normalized()
        elif state.drag_mode == _DragMode.MOVE:
            delta = pos - state.drag_origin
            moved = state.rect_at_drag_start.translated(delta)
            state.rect = self._clamp_rect(moved)
        else:
            state.rect = self._apply_handle_drag(
                state.rect_at_drag_start, state.drag_mode, pos - state.drag_origin
            )
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        state = self._state

        if state.drag_mode == _DragMode.DRAW:
            if state.rect.width() < _MIN_BBOX_PX or state.rect.height() < _MIN_BBOX_PX:
                self.cancel_edit()
            else:
                x1, y1, x2, y2 = self._widget_rect_to_image_space(state.rect)
                self.cancel_edit()
                self.bbox_drawn.emit(x1, y1, x2, y2)  # Instantly confirms!
            return

        if self._editing_bbox_id is not None and state.drag_mode != _DragMode.NONE:
            x1, y1, x2, y2 = self._widget_rect_to_image_space(state.rect)
            self.bbox_edited.emit(self._editing_bbox_id, x1, y1, x2, y2)

        state.drag_mode = _DragMode.NONE

    # --- Context Menu ---

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        """Constructs and routes right-click actions dynamically."""
        if self._tool_mode != ToolMode.EDIT:
            return

        hit_id, _ = self._get_bbox_at_pos(event.pos())
        if not hit_id:
            return

        menu = QMenu(self)
        action_dup_next = menu.addAction("Duplicate to Next Frame")
        action_dup_prev = menu.addAction("Duplicate to Previous Frame")
        menu.addSeparator()
        action_copy = menu.addAction("Copy")

        action_del_next = None
        action_del_prev = None
        if self._tracker_actions_enabled:
            menu.addSeparator()
            action_del_next = menu.addAction("Delete Next Occurrences")
            action_del_prev = menu.addAction("Delete Previous Occurrences")

        chosen = menu.exec(event.globalPos())

        # Route logic via string keys to the Controller
        if chosen == action_dup_next:
            self.context_action_triggered.emit("duplicate_next", hit_id)
        elif chosen == action_dup_prev:
            self.context_action_triggered.emit("duplicate_prev", hit_id)
        elif chosen == action_copy:
            self.context_action_triggered.emit("copy", hit_id)
        elif chosen == action_del_next:
            self.context_action_triggered.emit("delete_next", hit_id)
        elif chosen == action_del_prev:
            self.context_action_triggered.emit("delete_prev", hit_id)

    # --- Rendering ---

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._state.has_valid_rect:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self._state.rect
        painter.setPen(QPen(_BOX_COLOR, 2, Qt.PenStyle.SolidLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # Center dot
        cx, cy = rect.center().x(), rect.center().y()
        painter.setPen(QPen(_BOX_COLOR, 1))
        painter.setBrush(QBrush(_CENTER_COLOR))
        r = _HANDLE_DRAW_R + 2
        painter.drawEllipse(QPoint(cx, cy), r, r)

        # Handles
        for pt in self._handle_points(rect):
            painter.setPen(QPen(_HANDLE_BORDER, 1))
            painter.setBrush(QBrush(_HANDLE_COLOR))
            painter.drawEllipse(pt, _HANDLE_DRAW_R, _HANDLE_DRAW_R)

        painter.end()

    # --- Geometry & Hit Test Helpers ---

    def _get_bbox_at_pos(self, pos: QPoint) -> tuple[str | None, QRect | None]:
        """Finds the closest bbox hit by the given point."""
        closest_id = None
        closest_rect = None
        min_dist = float('inf')

        for bbox_id, (x1, y1, x2, y2) in self._active_bboxes.items():
            rect = self._image_rect_to_widget_space(x1, y1, x2, y2)
            if rect.isNull():
                continue

            if rect.contains(pos):
                return bbox_id, rect  # Direct hit

            cx, cy = rect.center().x(), rect.center().y()
            dist = (pos.x() - cx) ** 2 + (pos.y() - cy) ** 2
            if dist < min_dist:
                min_dist = dist
                closest_id = bbox_id
                closest_rect = rect

        if min_dist < 2500:  # ~50px snap radius
            return closest_id, closest_rect
        return None, None

    def _image_rect_to_widget_space(self, x1: int, y1: int, x2: int, y2: int) -> QRect:
        r = self._pixmap_rect
        if r.width() == 0 or self._image_size is None:
            return QRect()
        sx = r.width() / self._image_size.width()
        sy = r.height() / self._image_size.height()
        return QRect(
            QPoint(int((x1 * sx) + r.left()), int((y1 * sy) + r.top())),
            QPoint(int((x2 * sx) + r.left()), int((y2 * sy) + r.top()))
        ).normalized()

    def _widget_rect_to_image_space(self, rect: QRect) -> tuple[int, int, int, int]:
        r = self._pixmap_rect
        if r.width() == 0 or self._image_size is None:
            return 0, 0, 0, 0
        sx = self._image_size.width() / r.width()
        sy = self._image_size.height() / r.height()
        return (
            max(0, int((rect.left() - r.left()) * sx)),
            max(0, int((rect.top() - r.top()) * sy)),
            min(self._image_size.width(), int((rect.right() - r.left()) * sx)),
            min(self._image_size.height(), int((rect.bottom() - r.top()) * sy))
        )

    def _apply_handle_drag(self, base: QRect, mode: _DragMode, delta: QPoint) -> QRect:
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
        r = self._pixmap_rect
        return QPoint(
            max(r.left(), min(point.x(), r.right())),
            max(r.top(), min(point.y(), r.bottom())),
        )

    def _clamp_rect(self, rect: QRect) -> QRect:
        pr = self._pixmap_rect
        r = rect.normalized()
        dx = dy = 0
        if r.left() < pr.left():   dx = pr.left() - r.left()
        if r.right() > pr.right():  dx = pr.right() - r.right()
        if r.top() < pr.top():    dy = pr.top() - r.top()
        if r.bottom() > pr.bottom(): dy = pr.bottom() - r.bottom()
        return r.translated(dx, dy)

    def _hit_test_handle(self, pos: QPoint) -> _DragMode:
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

    @staticmethod
    def _handle_points(rect: QRect) -> list[QPoint]:
        x1, y1, x2, y2 = rect.left(), rect.top(), rect.right(), rect.bottom()
        mx, my = (x1 + x2) // 2, (y1 + y2) // 2
        return [
            QPoint(x1, y1), QPoint(mx, y1), QPoint(x2, y1),
            QPoint(x1, my), QPoint(x2, my),
            QPoint(x1, y2), QPoint(mx, y2), QPoint(x2, y2),
        ]


# --- Internal Helpers ---

class _DragMode(Enum):
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
    rect: QRect = field(default_factory=QRect)
    drag_mode: _DragMode = _DragMode.NONE
    drag_origin: QPoint = field(default_factory=QPoint)
    rect_at_drag_start: QRect = field(default_factory=QRect)

    @property
    def has_valid_rect(self) -> bool:
        return not self.rect.isNull()