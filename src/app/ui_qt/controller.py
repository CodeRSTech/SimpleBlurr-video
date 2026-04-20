from __future__ import annotations

"""
Qt controller for the video editor rewrite.

This module connects the Qt window layer to the application service layer.
`EditorController` owns the UI orchestration logic that should not live directly
inside widgets.

Main responsibilities
---------------------
- connect window signals to application-service calls
- render frames into the preview widget
- update navigation and status UI
- manage playback timer behavior
- manage async model loading
- coordinate manual annotation actions
- handle keyboard nudging for selected manual boxes

Keyboard nudge behavior
-----------------------
A small event filter is installed on the frame-data table so arrow keys can move
selected Manual review items on the current frame.

The movement acceleration is intentionally simple:
- first repeats move by 1 px
- then 2 px
- then 4 px
- then 8 px

This currently applies only to Manual items in review B state. Detection items
are not mutated directly because raw A state must remain resettable.
"""

import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, QThread, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.application.editor_svc import EditorAppService
from app.shared.frame_overlay import draw_frame_overlays
from app.shared.image_utils import bgr_frame_to_qimage
from app.shared.logging_cfg import get_logger
from app.ui_qt.main_win import MainWindow
from app.ui_qt.annotation_dlg import ManualAnnotationDialog
from app.ui_qt.model_loader import ModelLoadWorker

logger = get_logger("UI->EditorController")


class _FrameTableKeyFilter(QObject):
    """
    Lightweight Qt event filter for frame-table key presses.

    This helper exists because `installEventFilter()` requires a QObject, while
    the controller itself is intentionally kept as a plain Python class.
    """

    def __init__(self, controller: "EditorController") -> None:
        super().__init__()
        self._controller = controller

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Forward relevant key presses to the controller."""
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            return self._controller.handle_frame_table_key_press(event)
        return False


class EditorController:
    """
    Main Qt application controller.

    This class wires UI events to use-case operations in `EditorAppService` and
    pushes updated state back into the window.
    """

    def __init__(
            self,
            app: QApplication,
            window: MainWindow,
            app_service: EditorAppService,
    ) -> None:
        logger.info("Initializing EditorController")
        self._app = app
        self._window = window
        self._app_service = app_service
        self._playback_timer = QTimer()
        self._playback_timer.setSingleShot(False)
        self._model_load_thread: QThread | None = None
        self._model_load_worker: ModelLoadWorker | None = None
        self._last_move_key: int | None = None
        self._last_move_ts: float = 0.0
        self._move_repeat_count: int = 0
        self._frame_table_key_filter: _FrameTableKeyFilter | None = None

        self._connect_signals()
        self._install_keyboard_move_filter()
        self._initialize_detection_models()

    # --- Public API ---

    def handle_frame_table_key_press(self, event: QKeyEvent) -> bool:
        """
        Handle arrow-key movement for selected frame items.

        Only plain arrow keys are handled.
        Only Manual items are moved by the application service.
        """
        if event.modifiers() != Qt.KeyboardModifier.NoModifier:
            return False

        key = event.key()
        if key not in (
                Qt.Key.Key_Left,
                Qt.Key.Key_Right,
                Qt.Key.Key_Up,
                Qt.Key.Key_Down,
        ):
            return False

        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return True

        item_keys = self._window.get_selected_frame_item_keys()
        if not item_keys:
            return True

        delta = self._get_move_delta_for_keypress(key)
        delta_x = 0
        delta_y = 0

        if key == Qt.Key.Key_Left:
            delta_x = -delta
        elif key == Qt.Key.Key_Right:
            delta_x = delta
        elif key == Qt.Key.Key_Up:
            delta_y = -delta
        elif key == Qt.Key.Key_Down:
            delta_y = delta

        try:
            moved_count = self._app_service.move_manual_frame_items(
                session_id,
                item_keys,
                delta_x,
                delta_y,
            )
            if moved_count > 0:
                self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Move Failed", str(exc))
            logger.opt(exception=exc).error("Failed to move selected manual frame item(s)")

        return True

    # --- Internal Initialization ---

    def _connect_signals(self) -> None:
        """
        Connect all window signals and lifecycle hooks.

        This method is the main signal wiring map for the Qt application.
        """
        logger.debug("Connecting signals for EditorController")
        self._playback_timer.timeout.connect(self._on_playback_tick)

        self._window.open_videos_requested.connect(self._on_open_videos)
        self._window.session_selected.connect(self._on_session_selected)
        self._window.detection_model_changed.connect(self._on_detection_model_changed)
        self._window.detect_current_frame_requested.connect(self._on_detect_current_frame_requested)
        self._window.start_background_detection_requested.connect(self._on_start_background_detection_requested)
        self._window.add_manual_frame_item_requested.connect(self._on_add_manual_frame_item_requested)
        self._window.edit_selected_frame_item_requested.connect(self._on_edit_selected_frame_item_requested)
        self._window.delete_selected_frame_item_requested.connect(self._on_delete_selected_frame_item_requested)
        self._window.duplicate_selected_frame_item_requested.connect(self._on_duplicate_selected_frame_item_requested)
        self._window.reset_current_frame_review_requested.connect(self._on_reset_current_frame_review_requested)
        self._window.reset_all_review_requested.connect(self._on_reset_all_review_requested)
        self._window.seek_requested.connect(self._on_seek_requested)
        self._window.play_requested.connect(self._on_play_requested)
        self._window.pause_requested.connect(self._on_pause_requested)
        self._window.next_frame_requested.connect(self._on_next_frame_requested)
        self._window.previous_frame_requested.connect(self._on_previous_frame_requested)
        self._app.aboutToQuit.connect(self._on_about_to_quit)

    def _initialize_detection_models(self) -> None:
        """Populate the model selector with available detection backends."""
        self._window.set_detection_model_items(
            self._app_service.get_available_detection_models()
        )
        self._window.set_selected_detection_model("None")

    def _install_keyboard_move_filter(self) -> None:
        """Install the arrow-key handler on the frame item table."""
        table = self._window.get_frame_data_table()
        self._frame_table_key_filter = _FrameTableKeyFilter(self)
        table.installEventFilter(self._frame_table_key_filter)

    # --- UI Refresh Helpers ---

    def _get_move_delta_for_keypress(self, key: int) -> int:
        """
        Convert repeated key presses into a simple acceleration curve.

        The repeat counter resets when:
        - enough time passes between presses, or
        - the key direction changes.
        """
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

    def _render_frame(self, session_id: str, frame) -> None:
        """
        Render a frame into the preview and rebuild the frame-data table.

        Rendering pulls the current presentation model from the application
        service, overlays boxes onto the frame image, then updates the window.
        """
        logger.trace("Rendering frame")
        presentation = self._app_service.get_frame_presentation(session_id)
        frame_with_overlays = draw_frame_overlays(frame, presentation.frame_data_items)
        image = bgr_frame_to_qimage(frame_with_overlays)

        self._window.preview_widget.set_image(image)
        self._window.set_frame_data_items(presentation.frame_data_items)

    def _show_saved_session_frame(self, session_id: str) -> None:
        """
        Re-render the currently indexed frame for a session.

        This is commonly used after edits that change overlay/table state without
        changing the current frame index.
        """
        logger.debug("Showing saved session frame: session_id={}", session_id)
        session = self._app_service.set_active_session(session_id)
        frame = self._app_service.load_frame(session_id, session.playback.current_frame_index)
        self._render_frame(session_id, frame)
        self._window.set_status_text(self._app_service.get_active_status_text())
        self._update_navigation_ui(session_id)
        self._update_detection_ui(session_id)

    def _show_session_frame(self, session_id: str, frame_loader: Callable[[str], object]) -> None:
        """Load, render, and fully refresh UI state for a frame operation."""
        frame = frame_loader(session_id)
        self._render_frame(session_id, frame)
        self._window.set_status_text(self._app_service.get_active_status_text())
        self._update_navigation_ui(session_id)
        self._update_detection_ui(session_id)

    def _stop_playback(self) -> None:
        """Stop the playback timer and clear playing state across sessions."""
        logger.trace("Stopping playback")
        self._playback_timer.stop()
        self._app_service.stop_all_playback()

        active_session = self._app_service.get_active_session()
        if active_session is not None:
            self._window.set_status_text(self._app_service.get_active_status_text())
            self._update_navigation_ui(active_session.session_id)

    def _update_detection_ui(self, session_id: str) -> None:
        """Refresh the selected model shown in the UI."""
        model_name = self._app_service.get_selected_detection_model_name(session_id)
        self._window.set_selected_detection_model(model_name)

    def _update_navigation_ui(self, session_id: str) -> None:
        """Refresh seek slider and frame label for the active session."""
        frame_count = self._app_service.get_session_frame_count(session_id)
        current_index = self._app_service.get_session_current_frame_index(session_id)

        self._window.set_seek_range(max(frame_count - 1, 0))
        self._window.set_seek_value(current_index)
        self._window.set_frame_label_text(self._app_service.get_session_frame_label(session_id))

    # --- Asynchronous Model Loading ---

    def _cleanup_model_load(self) -> None:
        """Dispose model-load worker objects after the thread finishes."""
        self._window.set_detection_loading_state(False)

        if self._model_load_worker is not None:
            self._model_load_worker.deleteLater()
            self._model_load_worker = None

        if self._model_load_thread is not None:
            self._model_load_thread.deleteLater()
            self._model_load_thread = None

    def _start_model_load(self, session_id: str, model_name: str) -> None:
        """
        Start asynchronous model loading on a worker thread.

        This keeps heavyweight model initialization off the main UI thread.
        """
        if self._model_load_thread is not None and self._model_load_thread.isRunning():
            self._window.show_error("Model Change Failed", "A model is already loading.")
            return

        self._window.set_detection_loading_state(True)
        self._window.set_status_text(f"Loading model: {model_name}")

        self._model_load_thread = QThread()
        self._model_load_worker = ModelLoadWorker(self._app_service, session_id, model_name)
        self._model_load_worker.moveToThread(self._model_load_thread)

        self._model_load_thread.started.connect(self._model_load_worker.run)
        self._model_load_worker.finished.connect(self._on_model_load_finished)
        self._model_load_worker.failed.connect(self._on_model_load_failed)
        self._model_load_worker.finished.connect(self._model_load_thread.quit)
        self._model_load_worker.failed.connect(self._model_load_thread.quit)
        self._model_load_thread.finished.connect(self._cleanup_model_load)

        self._model_load_thread.start()

    # --- Signal Handlers: Lifecycle ---

    def _on_about_to_quit(self) -> None:
        """Stop timers/workers and close session resources during app shutdown."""
        logger.debug("About to quit: stopping playback and closing app")
        self._playback_timer.stop()
        self._app_service.close()

        if self._model_load_thread is not None and self._model_load_thread.isRunning():
            self._model_load_thread.quit()
            self._model_load_thread.wait()

    # --- Signal Handlers: Session & Model ---

    def _on_detection_model_changed(self, model_name: str) -> None:
        """Start async model switching for the selected session."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        logger.info("Detection model changed: session_id={}, model={}", session_id, model_name)
        self._start_model_load(session_id, model_name)

    def _on_model_load_failed(self, session_id: str, model_name: str, error_message: str) -> None:
        """Handle async model loading failure."""
        logger.error(
            "Background model load failed: session_id={}, model={}, error={}",
            session_id,
            model_name,
            error_message,
        )
        self._window.show_error("Model Change Failed", error_message)

        active_session = self._app_service.get_active_session()
        if active_session is not None:
            self._window.set_status_text(self._app_service.get_active_status_text())
            self._update_detection_ui(active_session.session_id)

    def _on_model_load_finished(self, session_id: str, model_name: str) -> None:
        """Handle successful async model loading."""
        logger.info(
            "Background model load finished: session_id={}, model={}",
            session_id,
            model_name,
        )
        self._window.set_status_text(self._app_service.get_active_status_text())
        self._window.set_frame_data_items([])
        self._show_saved_session_frame(session_id)

    def _on_open_videos(self, paths: list[str]) -> None:
        """Open selected videos and refresh the session list."""
        try:
            logger.debug("Opening {} video(s)", len(paths))
            self._stop_playback()
            self._app_service.open_videos(paths)
            items = self._app_service.get_session_list_items()
            self._window.set_session_items(items)

            active_session = self._app_service.get_active_session()
            if active_session is not None:
                logger.debug("Selecting active session after open: {}", active_session.session_id)
                self._window.select_session(active_session.session_id)
        except Exception as exc:
            self._window.show_error("Open Video(s) Failed", str(exc))
            logger.opt(exception=exc).error("Failed to open videos")

    def _on_session_selected(self, session_id: str) -> None:
        """Switch active session and display its current frame."""
        logger.info("Session selected: {}", session_id)
        try:
            self._stop_playback()
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Session Load Failed", str(exc))
            logger.opt(exception=exc).error("Failed to load session")

    # --- Signal Handlers: Detection Tasks ---

    def _on_detect_current_frame_requested(self) -> None:
        """Run detection only for the current frame and refresh the UI."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        logger.info("Detect current frame requested: session_id={}", session_id)
        try:
            self._stop_playback()
            self._app_service.set_active_session(session_id)
            self._app_service.detect_current_frame(session_id)
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Detection Failed", str(exc))
            logger.opt(exception=exc).error("Failed to detect current frame")

    def _on_start_background_detection_requested(self) -> None:
        """Start background detection for the selected session."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        logger.info("Start background detection requested: session_id={}", session_id)
        try:
            self._app_service.set_active_session(session_id)
            self._app_service.start_background_detection(session_id)
            self._window.set_status_text(self._app_service.get_active_status_text())
        except Exception as exc:
            self._window.show_error("Background Detection Failed", str(exc))
            logger.opt(exception=exc).error("Failed to start background detection")

    # --- Signal Handlers: Manual Annotations ---

    def _on_add_manual_frame_item_requested(self) -> None:
        """Show the add-annotation dialog and create a Manual item."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        dialog = ManualAnnotationDialog(self._window)
        if dialog.exec() == ManualAnnotationDialog.DialogCode.Accepted:
            label, bbox_xyxy = dialog.get_annotation_data()

            if not label:
                self._window.show_error("Add Manual Annotation Failed", "Label cannot be empty.")
                return

            x1, y1, x2, y2 = bbox_xyxy
            if x2 <= x1 or y2 <= y1:
                self._window.show_error("Add Manual Annotation Failed", "BBox must satisfy x2 > x1 and y2 > y1.")
                return

            try:
                self._app_service.add_manual_frame_item(session_id, label, bbox_xyxy)
                self._show_saved_session_frame(session_id)
            except Exception as exc:
                self._window.show_error("Add Manual Annotation Failed", str(exc))
                logger.opt(exception=exc).error("Failed to add manual frame item")

    def _on_delete_selected_frame_item_requested(self) -> None:
        """Delete selected review items from the current frame."""
        session_id = self._window.get_selected_session_id()
        item_keys = self._window.get_selected_frame_item_keys()
        if session_id is None or not item_keys:
            return

        logger.info(
            "Delete selected frame items requested: session_id={}, count={}",
            session_id,
            len(item_keys),
        )
        try:
            self._app_service.delete_frame_items(session_id, item_keys)
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Delete Failed", str(exc))
            logger.opt(exception=exc).error("Failed to delete frame item(s)")

    def _on_duplicate_selected_frame_item_requested(self) -> None:
        """Duplicate selected items into the next frame as Manual items."""
        session_id = self._window.get_selected_session_id()
        item_keys = self._window.get_selected_frame_item_keys()
        if session_id is None or not item_keys:
            return

        logger.info(
            "Duplicate selected frame items requested: session_id={}, count={}",
            session_id,
            len(item_keys),
        )
        try:
            self._app_service.duplicate_frame_items_to_next_frame(session_id, item_keys)
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Duplicate Failed", str(exc))
            logger.opt(exception=exc).error("Failed to duplicate frame item(s)")

    def _on_edit_selected_frame_item_requested(self) -> None:
        """Edit one selected Manual item via the annotation dialog."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        item_keys = self._window.get_selected_frame_item_keys()
        if len(item_keys) != 1:
            self._window.show_error("Edit Failed", "Select exactly one item to edit.")
            return

        item = self._app_service.get_review_frame_item(session_id, item_keys[0])
        if item is None:
            self._window.show_error("Edit Failed", "Selected item was not found.")
            return

        dialog = ManualAnnotationDialog(
            self._window,
            title="Edit Manual Annotation",
            initial_label=item.label,
            initial_bbox_xyxy=item.bbox_xyxy,
        )
        if dialog.exec() != ManualAnnotationDialog.DialogCode.Accepted:
            return

        label, bbox_xyxy = dialog.get_annotation_data()

        if not label:
            self._window.show_error("Edit Failed", "Label cannot be empty.")
            return

        x1, y1, x2, y2 = bbox_xyxy
        if x2 <= x1 or y2 <= y1:
            self._window.show_error("Edit Failed", "BBox must satisfy x2 > x1 and y2 > y1.")
            return

        try:
            self._app_service.update_manual_frame_item(session_id, item.item_key, label, bbox_xyxy)
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Edit Failed", str(exc))
            logger.opt(exception=exc).error("Failed to edit manual frame item")

    def _on_reset_all_review_requested(self) -> None:
        """Clear all review state so it rebuilds lazily from raw detection state."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        try:
            self._app_service.reset_all_review_frames(session_id)
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Reset All Failed", str(exc))
            logger.opt(exception=exc).error("Failed to reset all review state")

    def _on_reset_current_frame_review_requested(self) -> None:
        """Reset the current frame's review state from raw detection state."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        try:
            frame_index = self._app_service.get_session_current_frame_index(session_id)
            self._app_service.reset_review_frame(session_id, frame_index)
            self._show_saved_session_frame(session_id)
        except Exception as exc:
            self._window.show_error("Reset Frame Failed", str(exc))
            logger.opt(exception=exc).error("Failed to reset current frame review state")

    # --- Signal Handlers: Playback & Navigation ---

    def _on_next_frame_requested(self) -> None:
        """Advance one frame."""
        logger.trace("Next frame requested")
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        try:
            self._stop_playback()
            self._app_service.set_active_session(session_id)
            self._show_session_frame(session_id, self._app_service.load_next_frame)
        except Exception as exc:
            self._window.show_error("Next Frame Failed", str(exc))
            logger.opt(exception=exc).error("Failed to load next frame")

    def _on_pause_requested(self) -> None:
        """Pause playback."""
        logger.trace("Pause requested")
        self._stop_playback()

    def _on_play_requested(self) -> None:
        """Start timed playback for the selected session."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            self._window.show_error("Play Failed", "No session selected.")
            logger.debug("Play requested with no selected session")
            return

        try:
            self._stop_playback()
            self._app_service.set_active_session(session_id)
            self._app_service.set_session_playing(session_id, True)
            interval_ms = self._app_service.get_session_frame_interval_ms(session_id)
            self._playback_timer.start(interval_ms)
            self._window.set_status_text(self._app_service.get_active_status_text())
            self._update_navigation_ui(session_id)
        except Exception as exc:
            self._window.show_error("Play Failed", str(exc))
            logger.opt(exception=exc).error("Failed to start playback")

    def _on_playback_tick(self) -> None:
        """
        Advance playback on each timer tick.

        Playback stops automatically when the last frame is reached or when an
        exception occurs.
        """
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            logger.debug("Playback tick with no selected session")
            self._stop_playback()
            return

        try:
            self._app_service.set_active_session(session_id)

            if self._app_service.is_at_last_frame(session_id):
                logger.debug("Playback reached last frame: session_id={}", session_id)
                self._stop_playback()
                return

            self._show_session_frame(session_id, self._app_service.load_next_frame)
        except Exception:
            self._stop_playback()
            logger.opt(exception=True).exception("Playback tick failed")

    def _on_previous_frame_requested(self) -> None:
        """Go back one frame."""
        logger.trace("Previous frame requested")
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            logger.debug("Previous frame requested with no selected session")
            return

        try:
            self._stop_playback()
            self._app_service.set_active_session(session_id)
            self._show_session_frame(session_id, self._app_service.load_previous_frame)
        except Exception as exc:
            self._window.show_error("Previous Frame Failed", str(exc))
            logger.opt(exception=exc).error("Failed to load previous frame")

    def _on_seek_requested(self, frame_index: int) -> None:
        """Seek to an arbitrary frame selected by the user."""
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        logger.debug("Seek requested: session_id={}, frame_index={}", session_id, frame_index)
        try:
            self._stop_playback()
            self._app_service.set_active_session(session_id)
            self._show_session_frame(
                session_id,
                lambda selected_session_id: self._app_service.load_frame(selected_session_id, frame_index),
            )
        except Exception as exc:
            self._window.show_error("Seek Failed", str(exc))
            logger.opt(exception=exc).error("Failed to seek frame")