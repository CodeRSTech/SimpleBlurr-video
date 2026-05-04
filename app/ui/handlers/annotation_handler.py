from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from app.application.coordinator import Coordinator
from app.shared.logging_cfg import get_logger
from app.ui.qt import MainWindow
from app.ui.qt.dialogue_boxes import EditAnnotationDialog, LabelDialog

logger = get_logger("UI->AnnotationHandler")

class AnnotationHandler:
    """
    Handles annotation-related operations for a specific session and user interface window.

    This class is responsible for managing annotations in the application, including adding,
    editing, duplicating, deleting, resetting frames or trackers, and handling user interactions
    such as key events for nudging bounding boxes. The class also interacts with the application
    coordinator and UI components for executing these operations.

    Attributes:
        _window: The main application window instance.
        _coordinator (Coordinator): The application coordinator that manages the logical
            state and data manipulation of sessions and annotations.
    """
    def __init__(self, window: MainWindow, coordinator: Coordinator) -> None:
        self._window = window
        self._coordinator = coordinator
        self._last_move_key: int | None = None
        self._last_move_ts: float = 0.0
        self._move_repeat_count: int = 0
        self._pending_render_fn = None  # set while waiting for a bbox draw

    def __repr__(self):
        return f"{self.__class__.__name__}, window={self._window}, coordinator={self._coordinator}"

    def handle_new_drawn_box(self, session_id: str, x1: int, y1: int, x2: int, y2: int, render_fn) -> None:
        dialog = LabelDialog(self._window)
        if dialog.exec() == LabelDialog.DialogCode.Accepted and dialog.get_label():
            label = dialog.get_label()
            try:
                self._coordinator.add_manual_frame_box(session_id, label, (x1, y1, x2, y2))
                self._window.set_status_text("Annotation added.")
                render_fn(session_id)
            except Exception as exc:
                self._window.show_error("Add Failed", str(exc))

        # Switch back to EDIT mode automatically for a smooth UX
        self._window.set_tool_mode_edit()

    def handle_existing_box_edit(self, session_id: str, item_key: str, render_fn, new_coords=None) -> None:
        """Handles both visual drags (new_coords) and table 'Edit' clicks (dialog)."""
        tab = self._window.get_active_tab_index()
        item = (self._coordinator.get_final_frame_box(session_id, item_key) if tab == 1
                else self._coordinator.get_review_frame_box(session_id, item_key))
        if item is None: return

        label, bbox_xyxy = item.label, item.bbox_xyxy

        if new_coords:
            bbox_xyxy = new_coords  # It was visually dragged
        else:
            # It was clicked via "Edit Selected" button, show dialog
            dialog = EditAnnotationDialog(self._window, initial_label=label, initial_bbox_xyxy=bbox_xyxy)
            if dialog.exec() != EditAnnotationDialog.DialogCode.Accepted: return
            label, bbox_xyxy = dialog.get_annotation_data()

        try:
            if tab == 1:
                self._coordinator.update_final_frame_box(session_id, item.key, label, bbox_xyxy)
            else:
                self._coordinator.update_manual_frame_box(session_id, item.key, label, bbox_xyxy)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Edit Failed", str(exc))

    # FIXME: Marked for removal
    def on_add_manual(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        # Phase 1: prompt for label, then enable drawing
        dialog = LabelDialog(self._window)
        if dialog.exec() != LabelDialog.DialogCode.Accepted:
            return

        label = dialog.get_label()
        if not label:
            self._window.show_error("Add Failed", "Label cannot be empty.")
            return

        # Phase 2: activate drawing mode on the preview widget
        self._pending_render_fn = render_fn
        preview = self._window.preview_container
        preview.set_drawing_enabled(True)
        # Connect one-shot: fires when user finishes drawing
        preview.bbox_drawn.connect(
            lambda x1, y1, x2, y2: self._on_bbox_drawn(session_id, label, x1, y1, x2, y2)
        )
        self._window.set_status_text("Draw a bounding box on the preview. Click and drag.")

    # UPDATE: Direct editing logic without Layer D restrictions
    
    def on_edit_selected(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if not session_id: return
        keys = self._window.get_selected_frame_box_keys()
        if len(keys) != 1: return

        self.handle_existing_box_edit(session_id, keys[0], render_fn)

    
    def on_delete_selected(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_box_keys()
        if session_id is None or not keys:
            return

        tab = self._window.get_active_tab_index()
        try:
            if tab == 1:
                self._coordinator.delete_final_frame_boxs(session_id, keys)
            else:
                self._coordinator.delete_frame_boxs(session_id, keys)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Delete Failed", str(exc))

    def on_duplicate_to_next(self, render_fn) -> None:
        self._duplicate(render_fn, direction=1)

    def on_duplicate_to_prev(self, render_fn) -> None:
        self._duplicate(render_fn, direction=-1)

    def on_reset_frame(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            idx = self._coordinator.get_session_current_frame_index(session_id)
            self._coordinator.reset_review_frame(session_id, idx)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset Failed", str(exc))

    def on_reset_all(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._coordinator.reset_all_review_frames(session_id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset All Failed", str(exc))

    def on_reset_tracker_frame(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            idx = self._coordinator.get_session_current_frame_index(session_id)
            self._coordinator.reset_final_frame(session_id, idx)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset Tracker Frame Failed", str(exc))

    def on_reset_all_trackers(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._coordinator.reset_all_final_frames(session_id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset All Trackers Failed", str(exc))

    def on_delete_next_occurrences(self, render_fn) -> None:
        self._delete_occurrences(render_fn, direction=1)

    def on_delete_prev_occurrences(self, render_fn) -> None:
        self._delete_occurrences(render_fn, direction=-1)

    def handle_nudge_key(self, event: QKeyEvent, render_fn) -> bool:
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False

        key = event.key()
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            return False

        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_box_keys()
        if not session_id or not keys:
            return True

        delta = self._get_nudge_delta(key)
        dx, dy = 0, 0
        if key == Qt.Key.Key_Left:
            dx = -delta
        elif key == Qt.Key.Key_Right:
            dx = delta
        elif key == Qt.Key.Key_Up:
            dy = -delta
        elif key == Qt.Key.Key_Down:
            dy = delta

        tab = self._window.get_active_tab_index()
        try:
            if tab == 1:
                moved = self._coordinator.move_final_frame_boxs(session_id, keys, dx, dy)
            else:
                moved = self._coordinator.move_manual_frame_boxs(session_id, keys, dx, dy)
            if moved > 0:
                render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Move Failed", str(exc))

        return True

    def _delete_occurrences(self, render_fn, direction: int) -> None:
        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_box_keys()
        if session_id is None or not keys:
            return

        tab = self._window.get_active_tab_index()
        if tab != 1:
            self._window.show_error("Operation Invalid", "This action is only available in the Tracking tab.")
            return

        try:
            # item_key format is "track:track-uid" or "manual:manual-id", we need the raw item_id
            for key in keys:
                item = self._coordinator.get_final_frame_box(session_id, key)
                if item:
                    if direction == 1:
                        self._coordinator.delete_next_occurrences(session_id, item.id)
                    else:
                        self._coordinator.delete_prev_occurrences(session_id, item.id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Delete Occurrences Failed", str(exc))

    def _duplicate(self, render_fn, direction: int) -> None:
        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_box_keys()
        if session_id is None or not keys:
            return

        tab = self._window.get_active_tab_index()
        try:
            if tab == 1:
                if direction == 1:
                    self._coordinator.duplicate_final_frame_boxs_to_next_frame(session_id, keys)
                else:
                    self._coordinator.duplicate_final_frame_boxs_to_prev_frame(session_id, keys)
            else:
                if direction == 1:
                    self._coordinator.duplicate_frame_boxs_to_next_frame(session_id, keys)
                else:
                    self._coordinator.duplicate_frame_boxs_to_prev_frame(session_id, keys)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Duplicate Failed", str(exc))

    def _get_nudge_delta(self, key: int) -> int:
        now = time.monotonic()
        if key != self._last_move_key or (now - self._last_move_ts) > 0.35:
            self._move_repeat_count = 0

        self._move_repeat_count += 1
        self._last_move_key = key
        self._last_move_ts = now

        if self._move_repeat_count <= 4:
            return 1
        if self._move_repeat_count <= 8:
            return 2
        if self._move_repeat_count <= 12:
            return 4
        return 8

    def _on_bbox_drawn(self, session_id: str, label: str, x1: int, y1: int, x2: int, y2: int) -> None:
        preview = self._window.preview_container
        # Disconnect immediately — one-shot behaviour
        try:
            preview.bbox_drawn.disconnect()
        except RuntimeError:
            pass

        render_fn = self._pending_render_fn
        self._pending_render_fn = None

        bbox_xyxy = (x1, y1, x2, y2)
        try:
            self._coordinator.add_manual_frame_box(session_id, label, bbox_xyxy)
            if render_fn:
                render_fn(session_id)
            self._window.set_status_text("Annotation added.")
        except Exception as exc:
            self._window.show_error("Add Failed", str(exc))