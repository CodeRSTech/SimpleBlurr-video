from __future__ import annotations

import re
from PySide6.QtCore import QTimer, QThread
from PySide6.QtWidgets import QApplication

from app.application.coordinator import AppCoordinator
from app.shared import draw_frame_overlays, bgr_frame_to_qimage, get_logger
from app.ui.qt import MainWindow
from app.ui.handlers import (
    AnnotationHandler,
    DetectionHandler,
    ExportHandler,
    PlaybackHandler,
    SessionHandler,
    TrackingHandler)
from app.ui.qt.model_loader import ModelLoadWorker
from app.ui.qt.table_key_filter import FrameTableKeyFilter

logger = get_logger("UI->EditorController")

from functools import wraps


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


class EditorController:
    """
    Slimmed Qt application controller.
    Wires UI signals to Handlers. Owns the playback timer and the central frame renderer.
    """

    def __init__(
            self,
            app: QApplication,
            window: MainWindow,
            app_coordinator: AppCoordinator, ) -> None:
        self._app = app
        self._window = window
        self._app_coordinator = app_coordinator
        self._playback_timer = QTimer()
        self._playback_timer.setSingleShot(False)

        # Async model loader state
        self._model_load_thread: QThread | None = None
        self._model_load_worker: ModelLoadWorker | None = None

        # Instantiate Handlers
        self._session_handler = SessionHandler(window, app_coordinator)
        self._detection_handler = DetectionHandler(window, app_coordinator)
        self._tracking_handler = TrackingHandler(window, app_coordinator)
        self._annotation_handler = AnnotationHandler(window, app_coordinator)
        self._playback_handler = PlaybackHandler(window, app_coordinator, self._render_saved_frame)
        self._export_handler = ExportHandler(window, app_coordinator)

        self._frame_table_key_filter = FrameTableKeyFilter(self._annotation_handler, self._render_saved_frame)
        self._window.get_frame_data_table().installEventFilter(self._frame_table_key_filter)
        self._window.frame_tracker_data_table.installEventFilter(self._frame_table_key_filter)

        self._connect_signals()

        # Init model combobox
        self._window.set_detection_model_items(self._app_coordinator.get_available_detection_models())
        self._window.set_selected_detection_model("None")

    def _connect_signals(self) -> None:
        """
        Connects all necessary signals and slots for the UI components.
        """
        logger.info("Connecting UI Controller signals...")
        window = self._window

        # Connect signals to slots
        # ========================
        # App Lifecycle
        self._app.aboutToQuit.connect(self._on_about_to_quit)
        self.__connect_preview_container_signals(window)
        # Session
        self.__connect_signals_to_session_handler(window)
        # Detection
        self.__connect_signals_to_detection_handler(window)
        # Tracking
        self.__connect_signals_to_tracker_handler(window)
        # Annotation
        self.__connect_signals_to_annotation_handler(window)
        # Playback
        self.__connect_signals_to_playback_handler(window)
        # Export & Preview/Render
        self.__connect_signals_to_export_handler(window)

        # Connect the new Click-to-Edit signal
        self._window.preview_container.bbox_edited.connect(self._on_preview_bbox_edited)

        logger.info("UI Controller signals connected.")

    def _render_saved_frame(self, session_id: str) -> None:
        # Local references to the UI components and handlers to shorten code
        window = self._window
        app_coordinator = self._app_coordinator

        # Get index, frame and frame count
        idx, frame = app_coordinator.get_current_frame(session_id)
        frame_count = app_coordinator.get_session_frame_count(session_id)

        # Render frame
        self._render_frame(session_id, frame)

        # Set UI state
        window.set_status_text(self._app_coordinator.get_active_status_text())
        window.set_seek_range(max(frame_count - 1, 0))
        window.set_seek_value(idx)
        window.set_frame_label_text(self._app_coordinator.get_session_frame_label(session_id))

    def _render_frame(self, session_id: str, frame) -> None:
        window = self._window
        app_coordinator = self._app_coordinator
        tab_idx = window.get_active_tab_index()

        detections_data = app_coordinator.get_detections_presentation(session_id)
        trackers_data = app_coordinator.get_trackers_presentation(session_id)

        display_data = detections_data if tab_idx == 0 else trackers_data

        items_to_draw = []
        if app_coordinator.draw_boxes_enabled(session_id):
            items_to_draw = display_data.frame_data_items

        # Pass active boxes to the new container
        active_bboxes = {}
        for item in display_data.frame_data_items:
            match = re.match(r"\((-?\d+),(-?\d+)\)-\((-?\d+),(-?\d+)\)", item.bbox_text)
            if match:
                active_bboxes[item.item_key] = tuple(map(int, match.groups()))

        self._window.preview_container.set_active_bboxes(active_bboxes)

        frame_out = draw_frame_overlays(frame, items_to_draw)
        self._window.preview_container.set_image(bgr_frame_to_qimage(frame_out))
        self._window.set_frame_data_items(detections_data.frame_data_items)
        self._window.set_tracker_data_items(trackers_data.frame_data_items)

    # FIXME: Marked for removal.
    """    
    def _on_preview_bbox_edited(self, item_key: str, x1: int, y1: int, x2: int, y2: int) -> None:
        session_id = self._window.get_selected_session_id()
        if not session_id:
            return

        tab_idx = self._window.get_active_tab_index()

        # Protect backend state: Direct Layer D edits are locked by architectural contract
        if tab_idx == 1:
            self._window.show_error("Edit Info", "Editing Layer D directly is limited. Edit Layer B and re-track.")
            self._window.preview_container.cancel_edit()
            self._render_saved_frame(session_id)
            return

        item = self._app_coordinator.get_review_frame_item(session_id, item_key)
        if item:
            try:
                self._app_coordinator.update_manual_frame_item(
                    session_id, item_key, item.label, (x1, y1, x2, y2)
                )
                self._render_saved_frame(session_id)
            except Exception as exc:
                logger.error("Failed to update bbox: {}", exc)
                self._window.show_error("Edit Failed", str(exc))
    """

    def _stop_playback(self) -> None:
        self._playback_timer.stop()
        self._app_coordinator.stop_all_playback()
        active = self._app_coordinator.get_active_session()
        if active:
            self._window.set_status_text(self._app_coordinator.get_active_status_text())

    def _start_model_load(self, session_id: str, model_name: str, keep_manual: bool = True) -> None:
        try:
            if self._model_load_thread.isRunning():
                self._window.show_error("Model Change Failed", "A model is already loading.")
                return
        except AttributeError:
            logger.debug("Model load thread not initialized. Creating new thread...")

        self._model_load_thread = QThread()
        self._model_load_worker = ModelLoadWorker(self._app_coordinator, session_id, model_name)

        # Create local references to the UI components and worker to shorten code
        window = self._window
        model_load_thread = self._model_load_thread
        model_load_worker = self._model_load_worker

        window.set_detection_loading_state(True)
        window.set_status_text(f"Loading model: {model_name}")

        model_load_worker.moveToThread(model_load_thread)

        self.__connect_model_worker_and_thread(model_load_thread, model_load_worker)

        model_load_thread.start()

    def _on_model_load_finished(self, session_id: str, model_name: str) -> None:
        logger.debug("Model load finished for session {} with model {}", session_id, model_name)
        self._window.set_status_text(self._app_coordinator.get_active_status_text())
        self._window.set_frame_data_items([])
        self._render_saved_frame(session_id)

    def _on_model_load_failed(self, session_id: str, model_name: str, err: str) -> None:
        logger.error("Model load failed for session {} with model {}: {}", session_id, model_name, err)
        self._window.show_error("Model Load Failed", err)
        active = self._app_coordinator.get_active_session()
        if active:
            self._window.set_status_text(self._app_coordinator.get_active_status_text())

    def _cleanup_model_load(self) -> None:
        self._window.set_detection_loading_state(False)
        if self._model_load_worker is not None:
            self._model_load_worker.deleteLater()
            self._model_load_worker = None
        if self._model_load_thread is not None:
            self._model_load_thread.deleteLater()
            self._model_load_thread = None

    def _on_about_to_quit(self) -> None:
        self._stop_playback()
        self._app_coordinator.close()
        try:
            if self._model_load_thread.isRunning():
                self._model_load_thread.quit()
                self._model_load_thread.wait()
        except AttributeError:
            logger.debug("Model load thread was never initialized, Quitting anyway.")

    # --- Container Handlers ---

    @logit
    def _on_preview_bbox_drawn(self, x1, y1, x2, y2):
        logger.debug("Preview bbox drawn: ({}, {}), ({}, {})", x1, y1, x2, y2)
        sid = self._window.get_selected_session_id()
        if sid:
            logger.debug("Session {}: Calling Annotation Handler to handle drawn bbox...", sid)
            self._annotation_handler.handle_new_drawn_box(sid, x1, y1, x2, y2, self._render_saved_frame)

    @logit
    def _on_preview_bbox_edited(self, item_key, x1, y1, x2, y2):
        logger.debug("Preview bbox edited ({}, {}, {}, {})", x1, y1, x2, y2)
        sid = self._window.get_selected_session_id()
        if sid:
            logger.debug("Session {}: Calling Annotation Handler to handle edited bbox...", sid)
            self._annotation_handler.handle_existing_box_edit(sid, item_key, self._render_saved_frame,
                                                              (x1, y1, x2, y2))

    @logit
    def _on_preview_bbox_deleted(self, item_key):
        logger.debug("Preview box deleted: {})", item_key)
        sid = self._window.get_selected_session_id()
        if sid:
            tab = self._window.get_active_tab_index()
            logger.debug("Deleting the box from the active tab {}", tab)

            if tab == 1:
                self._app_coordinator.delete_final_frame_items(sid, [item_key])
            else:
                self._app_coordinator.delete_frame_items(sid, [item_key])
            self._render_saved_frame(sid)

    @logit
    def _on_preview_context_action(self, action: str, item_key: str):
        logger.debug("Preview box context action: {}, {}", action, item_key)
        sid = self._window.get_selected_session_id()
        if not sid: return

        # Route the context menu actions directly to the existing backend logic!
        if action == "duplicate_next":
            if self._window.get_active_tab_index() == 1:
                self._app_coordinator.duplicate_final_frame_items_to_next_frame(sid, [item_key])
            else:
                self._app_coordinator.duplicate_frame_items_to_next_frame(sid, [item_key])
        elif action == "duplicate_prev":
            if self._window.get_active_tab_index() == 1:
                self._app_coordinator.duplicate_final_frame_items_to_prev_frame(sid, [item_key])
            else:
                self._app_coordinator.duplicate_frame_items_to_prev_frame(sid, [item_key])
        elif action == "delete_next":
            # Extract underlying item_id from item_key (e.g. "track:123" -> "123")
            item_id = self._app_coordinator.get_final_frame_item(sid, item_key).item_id
            self._app_coordinator.delete_next_occurrences(sid, item_id)
        elif action == "delete_prev":
            item_id = self._app_coordinator.get_final_frame_item(sid, item_key).item_id
            self._app_coordinator.delete_prev_occurrences(sid, item_id)

        self._render_saved_frame(sid)

    def on_open_videos_requested(self, paths):
        logger.debug(f"Opening videos: {paths}")
        self._session_handler.on_open_videos(paths)

    def on_session_selected(self, sid):
        logger.debug(f"Session selected: {sid}")
        self._session_handler.on_session_selected(sid, self._stop_playback, self._render_saved_frame)

    def on_model_changed(self, model):
        logger.debug(f"Model changed: {model}")
        self._detection_handler.on_model_changed(model, self._start_model_load)

    def on_detect_current_frame_requested(self):
        logger.debug("Detect current frame requested")
        self._detection_handler.on_detect_current_frame(self._render_saved_frame)

    def on_min_confidence_changed(self, val):
        logger.debug(f"Min confidence changed: {val}")
        self._detection_handler.on_min_confidence_changed(val, self._render_saved_frame)

    def on_chosen_labels_changed(self, val):
        logger.debug(f"Chosen labels changed: {val}")
        self._detection_handler.on_chosen_labels_changed(val, self._render_saved_frame)

    def on_start_tracking_requested(self, s, src):
        logger.debug(f"Start tracking requested: {s} {src}")
        self._tracking_handler.on_start_tracking(s, src, self._render_saved_frame)

    # ------------------------

    def on_add_manual_frame_item_requested(self):
        logger.debug("Add manual frame item requested")
        self._annotation_handler.on_add_manual(self._render_saved_frame)

    def on_edit_selected_frame_item_requested(self):
        logger.debug("Edit selected frame item requested")
        self._annotation_handler.on_edit_selected(self._render_saved_frame)

    def on_delete_selected_frame_item_requested(self):
        logger.debug("Delete selected frame item requested")
        self._annotation_handler.on_delete_selected(self._render_saved_frame)

    def on_duplicate_selected_frame_item_requested(self):
        logger.debug("Duplicate selected frame item requested")
        self._annotation_handler.on_duplicate_to_next(self._render_saved_frame)

    # Frame Data Annotation (Row 2)
    def on_duplicate_to_prev_frame_requested(self):
        logger.debug("Duplicate to prev frame requested")
        self._annotation_handler.on_duplicate_to_prev(self._render_saved_frame)

    def on_reset_current_frame_review_requested(self):
        logger.debug("Reset current frame review requested")
        self._annotation_handler.on_reset_frame(self._render_saved_frame)

    def on_reset_all_review_requested(self):
        logger.debug("Reset all review requested")
        self._annotation_handler.on_reset_all(self._render_saved_frame)

    def on_reset_tracker_frame_requested(self):
        logger.debug("Reset tracker frame requested")
        self._annotation_handler.on_reset_tracker_frame(self._render_saved_frame)

    def on_reset_all_trackers_requested(self):
        logger.debug("Reset all trackers requested")
        self._annotation_handler.on_reset_all_trackers(self._render_saved_frame)

    def on_delete_next_occurrences_requested(self):
        logger.debug("Delete next occurrences requested")
        self._annotation_handler.on_delete_next_occurrences(self._render_saved_frame)

    def on_delete_prev_occurrences_requested(self):
        logger.debug("Delete prev occurrences requested")
        self._annotation_handler.on_delete_prev_occurrences(self._render_saved_frame)

    # --------------------------------------------------------------------------------

    def on_play_requested(self):
        logger.trace("Play requested")
        self._playback_handler.on_play(self._playback_timer.start)

    def on_pause_requested(self):
        logger.trace("Pause requested")
        self._playback_handler.on_pause(self._stop_playback)

    def on_next_frame_requested(self):
        logger.trace("Next frame requested")
        self._playback_handler.on_next_frame(self._stop_playback)

    def on_previous_frame_requested(self):
        logger.trace("Previous frame requested")
        self._playback_handler.on_previous_frame(self._stop_playback)

    def on_seek_requested(self, idx):
        logger.trace(f"Seek requested: {idx}")
        self._playback_handler.on_seek(idx, self._stop_playback)

    def on_timeout(self):
        logger.trace("Playback timer timeout")
        self._playback_handler.on_playback_tick(self._stop_playback)

    # EXPORT HANDLER BINDINGS
    # --------------------------------------------------------------------------------
    def on_draw_boxes_changed(self, val):
        logger.debug(f"Draw boxes changed: {val}")
        self._export_handler.on_draw_boxes_changed(val, self._render_saved_frame)

    def on_blur_toggled(self, val):
        logger.debug(f"Blur toggled: {val}")
        self._export_handler.on_blur_toggled(val, self._render_saved_frame)

    def on_blur_strength_changed(self, val):
        logger.debug(f"Blur strength changed: {val}")
        self._export_handler.on_blur_strength_changed(val, self._render_saved_frame)

    def __connect_preview_container_signals(self, window: MainWindow):
        window.tool_mode_changed.connect(window.preview_container.set_tool_mode)

        container = window.preview_container
        container.bbox_drawn.connect(self._on_preview_bbox_drawn)
        container.bbox_edited.connect(self._on_preview_bbox_edited)
        container.bbox_deleted.connect(self._on_preview_bbox_deleted)
        container.context_action_triggered.connect(self._on_preview_context_action)

    def __connect_signals_to_session_handler(self, window: MainWindow):
        logger.debug("Connecting signals to session handler.")
        window.open_videos_requested.connect(self.on_open_videos_requested)
        window.session_selected.connect(self.on_session_selected)

    def __connect_signals_to_detection_handler(self, window: MainWindow):
        logger.debug("Connecting signals to detection handler.")
        detector = self._detection_handler
        window.model_changed.connect(self.on_model_changed)
        window.detect_current_frame_requested.connect(self.on_detect_current_frame_requested)
        window.start_background_detection_requested.connect(detector.on_start_background_detection)
        window.min_confidence_changed.connect(self.on_min_confidence_changed)
        window.chosen_labels_changed.connect(self.on_chosen_labels_changed)

    def __connect_signals_to_tracker_handler(self, window: MainWindow):
        logger.debug("Connecting signals to tracker handler.")
        tracker = self._tracking_handler
        window.start_tracking_requested.connect(self.on_start_tracking_requested)
        window.tracking_strategy_changed.connect(tracker.on_strategy_changed)
        window.tracking_source_changed.connect(tracker.on_source_changed)
        window.min_iou_changed.connect(tracker.on_min_iou_changed)
        window.min_tracker_confidence_changed.connect(tracker.on_min_tracker_confidence_changed)
        window.confidence_decay_changed.connect(tracker.on_confidence_decay_changed)

    def __connect_signals_to_annotation_handler(self, window: MainWindow):
        logger.debug("Connecting signals to annotation handler.")
        window.add_manual_frame_item_requested.connect(self.on_add_manual_frame_item_requested)
        window.edit_selected_frame_item_requested.connect(self.on_edit_selected_frame_item_requested)
        window.delete_selected_frame_item_requested.connect(self.on_delete_selected_frame_item_requested)
        window.duplicate_selected_frame_item_requested.connect(self.on_duplicate_selected_frame_item_requested)

        # Frame Data Annotation (Row 2)
        window.duplicate_to_prev_frame_requested.connect(self.on_duplicate_to_prev_frame_requested)

        window.reset_current_frame_review_requested.connect(self.on_reset_current_frame_review_requested)
        window.reset_all_review_requested.connect(self.on_reset_all_review_requested)

        window.reset_tracker_frame_requested.connect(self.on_reset_tracker_frame_requested)

        window.reset_all_trackers_requested.connect(self.on_reset_all_trackers_requested)

        window.delete_next_occurrences_requested.connect(self.on_delete_next_occurrences_requested)
        window.delete_prev_occurrences_requested.connect(self.on_delete_prev_occurrences_requested)

    def __connect_signals_to_playback_handler(self, window: MainWindow):
        logger.debug("Connecting signals to playback handler.")
        window.play_requested.connect(self.on_play_requested)
        window.pause_requested.connect(self.on_pause_requested)
        window.next_frame_requested.connect(self.on_next_frame_requested)
        window.previous_frame_requested.connect(self.on_previous_frame_requested)
        window.seek_requested.connect(self.on_seek_requested)
        self._playback_timer.timeout.connect(self.on_timeout)

    def __connect_signals_to_export_handler(self, window: MainWindow):
        logger.debug("Connecting signals to export handler.")
        exporter = self._export_handler
        window.export_requested.connect(exporter.on_export)
        window.export_all_requested.connect(exporter.on_export_all)
        window.draw_boxes_changed.connect(self.on_draw_boxes_changed)
        window.blur_toggled.connect(self.on_blur_toggled)
        window.blur_strength_changed.connect(self.on_blur_strength_changed)

    def __connect_model_worker_and_thread(self, model_load_thread: QThread, model_load_worker: ModelLoadWorker):
        logger.debug("Connecting model worker and thread.")

        model_load_thread.started.connect(model_load_worker.run)
        model_load_thread.finished.connect(self._cleanup_model_load)

        model_load_worker.finished.connect(self._on_model_load_finished)
        model_load_worker.finished.connect(model_load_thread.quit)

        model_load_worker.failed.connect(self._on_model_load_failed)
        model_load_worker.failed.connect(model_load_thread.quit)