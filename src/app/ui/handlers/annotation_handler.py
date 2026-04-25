from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from app.application.coordinator import AppCoordinator
from app.shared.logging_cfg import get_logger
from app.ui.qt.annotation_dlg import ManualAnnotationDialog

logger = get_logger("UI->AnnotationHandler")


class AnnotationHandler:
    def __init__(self, window, app_coordinator: AppCoordinator) -> None:
        self._window = window
        self._app_coordinator = app_coordinator
        self._last_move_key: int | None = None
        self._last_move_ts: float = 0.0
        self._move_repeat_count: int = 0

    def on_add_manual(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        dialog = ManualAnnotationDialog(self._window)
        if dialog.exec() != ManualAnnotationDialog.DialogCode.Accepted:
            return

        label, bbox_xyxy = dialog.get_annotation_data()
        if not label:
            self._window.show_error("Add Failed", "Label cannot be empty.")
            return

        x1, y1, x2, y2 = bbox_xyxy
        if x2 <= x1 or y2 <= y1:
            self._window.show_error("Add Failed", "BBox must satisfy x2>x1 and y2>y1.")
            return

        try:
            self._app_coordinator.add_manual_frame_item(session_id, label, bbox_xyxy)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Add Failed", str(exc))

    def on_edit_selected(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        keys = self._window.get_selected_frame_item_keys()
        if len(keys) != 1:
            self._window.show_error("Edit Failed", "Select exactly one item to edit.")
            return

        tab = self._window.get_active_tab_index()
        item = (
            self._app_coordinator.get_final_frame_item(session_id, keys[0])
            if tab == 1
            else self._app_coordinator.get_review_frame_item(session_id, keys[0])
        )

        if item is None:
            self._window.show_error("Edit Failed", "Item not found.")
            return

        dialog = ManualAnnotationDialog(
            self._window, title="Edit Annotation", initial_label=item.label, initial_bbox_xyxy=item.bbox_xyxy
        )
        if dialog.exec() != ManualAnnotationDialog.DialogCode.Accepted:
            return

        label, bbox_xyxy = dialog.get_annotation_data()
        if not label or bbox_xyxy[2] <= bbox_xyxy[0] or bbox_xyxy[3] <= bbox_xyxy[1]:
            self._window.show_error("Edit Failed", "Invalid label or bounding box.")
            return

        try:
            # Layer D edits are implemented as 'move/delete/dup' for now, but if direct edit is needed,
            # we apply it to the respective layer. For now, Layer B is fully editable.
            if tab == 1:
                # To keep it simple, if they edit a track, we handle it as a manual box overwrite
                self._window.show_error("Edit Info", "Editing Layer D directly is limited. Edit Layer B and re-track.")
                return

            self._app_coordinator.update_manual_frame_item(session_id, item.item_key, label, bbox_xyxy)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Edit Failed", str(exc))

    def on_delete_selected(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_item_keys()
        if session_id is None or not keys:
            return

        tab = self._window.get_active_tab_index()
        try:
            if tab == 1:
                self._app_coordinator.delete_final_frame_items(session_id, keys)
            else:
                self._app_coordinator.delete_frame_items(session_id, keys)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Delete Failed", str(exc))

    def on_duplicate_to_next(self, render_fn) -> None:
        self._duplicate(render_fn, direction=1)

    def on_duplicate_to_prev(self, render_fn) -> None:
        self._duplicate(render_fn, direction=-1)

    def _duplicate(self, render_fn, direction: int) -> None:
        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_item_keys()
        if session_id is None or not keys:
            return

        tab = self._window.get_active_tab_index()
        try:
            if tab == 1:
                if direction == 1:
                    self._app_coordinator.duplicate_final_frame_items_to_next_frame(session_id, keys)
                else:
                    self._app_coordinator.duplicate_final_frame_items_to_prev_frame(session_id, keys)
            else:
                if direction == 1:
                    self._app_coordinator.duplicate_frame_items_to_next_frame(session_id, keys)
                else:
                    self._app_coordinator.duplicate_frame_items_to_prev_frame(session_id, keys)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Duplicate Failed", str(exc))

    def on_reset_frame(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            idx = self._app_coordinator.get_session_current_frame_index(session_id)
            self._app_coordinator.reset_review_frame(session_id, idx)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset Failed", str(exc))

    def on_reset_all(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._app_coordinator.reset_all_review_frames(session_id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset All Failed", str(exc))

    def on_reset_tracker_frame(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            idx = self._app_coordinator.get_session_current_frame_index(session_id)
            self._app_coordinator.reset_final_frame(session_id, idx)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset Tracker Frame Failed", str(exc))

    def on_reset_all_trackers(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._app_coordinator.reset_all_final_frames(session_id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Reset All Trackers Failed", str(exc))

    def on_delete_next_occurrences(self, render_fn) -> None:
        self._delete_occurrences(render_fn, direction=1)

    def on_delete_prev_occurrences(self, render_fn) -> None:
        self._delete_occurrences(render_fn, direction=-1)

    def _delete_occurrences(self, render_fn, direction: int) -> None:
        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_item_keys()
        if session_id is None or not keys:
            return

        tab = self._window.get_active_tab_index()
        if tab != 1:
            self._window.show_error("Operation Invalid", "This action is only available in the Tracking tab.")
            return

        try:
            # item_key format is "track:track-uid" or "manual:manual-id", we need the raw item_id
            for key in keys:
                item = self._app_coordinator.get_final_frame_item(session_id, key)
                if item:
                    if direction == 1:
                        self._app_coordinator.delete_next_occurrences(session_id, item.item_id)
                    else:
                        self._app_coordinator.delete_prev_occurrences(session_id, item.item_id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Delete Occurrences Failed", str(exc))

    def handle_nudge_key(self, event: QKeyEvent, render_fn) -> bool:
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False

        key = event.key()
        if key not in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            return False

        session_id = self._window.get_selected_session_id()
        keys = self._window.get_selected_frame_item_keys()
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
                moved = self._app_coordinator.move_final_frame_items(session_id, keys, dx, dy)
            else:
                moved = self._app_coordinator.move_manual_frame_items(session_id, keys, dx, dy)
            if moved > 0:
                render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Move Failed", str(exc))

        return True

    def _get_nudge_delta(self, key: int) -> int:
        now = time.monotonic()
        if key != self._last_move_key or (now - self._last_move_ts) > 0.35:
            self._move_repeat_count = 0

        self._move_repeat_count += 1
        self._last_move_key = key
        self._last_move_ts = now

        if self._move_repeat_count <= 4: return 1
        if self._move_repeat_count <= 8: return 2
        if self._move_repeat_count <= 12: return 4
        return 8