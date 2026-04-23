from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.application.coordinator import AppCoordinator
from app.shared import draw_frame_overlays, bgr_frame_to_qimage, get_logger
from app.ui.qt.main_win import MainWindow
from app.ui.handlers import (
    AnnotationHandler,
    DetectionHandler,
    ExportHandler,
    PlaybackHandler,
    SessionHandler,
    TrackingHandler)
from app.ui.qt.model_loader import ModelLoadWorker
from PySide6.QtCore import QThread

from app.ui.qt.table_key_filter import FrameTableKeyFilter

logger = get_logger("UI->EditorController")


class EditorController:
    """
    Slimmed Qt application controller.
    Wires UI signals to Handlers. Owns the playback timer and the central frame renderer.
    """

    def __init__(
            self,
            app: QApplication,
            window: MainWindow,
            app_coordinator: AppCoordinator,) -> None:
        self._app = app
        self._window = window
        self._app_coordinator = app_coordinator
        self._playback_timer = QTimer()
        self._playback_timer.setSingleShot(False)

        # Async model loader state
        self.__model_load_thread: QThread | None = None
        self.__model_load_worker: ModelLoadWorker | None = None

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

    @property
    def _model_load_thread(self) -> QThread:
        if self.__model_load_thread is None:
            raise ValueError("Model load thread is not initialized")
        return self.__model_load_thread

    @_model_load_thread.setter
    def _model_load_thread(self, thread: QThread | None) -> None:
        self.__model_load_thread = thread

    @property
    def _model_load_worker(self) -> ModelLoadWorker:
        if self.__model_load_worker is None:
            raise ValueError("Model load worker is not initialized")
        return self.__model_load_worker

    @_model_load_worker.setter
    def _model_load_worker(self, worker: ModelLoadWorker | None) -> None:
        self.__model_load_worker = worker

    def _connect_signals(self) -> None:
        """
        Connects all necessary signals and slots for the UI components.
        """

        # Local references to the UI components and handlers to shorten code
        # ==================================================================
        app = self._app
        window = self._window

        player = self._playback_handler
        exporter = self._export_handler
        detector = self._detection_handler
        tracker = self._tracking_handler
        annotator = self._annotation_handler
        session = self._session_handler

        play_timer = self._playback_timer

        about_to_quit_fx = self._on_about_to_quit
        stop_play_fx = self._stop_playback
        render_fx = self._render_saved_frame
        model_load_fx = self._start_model_load

        # Connect signals to slots
        # ========================

        # App Lifecycle
        app.aboutToQuit.connect(about_to_quit_fx)
        play_timer.timeout.connect(lambda: player.on_playback_tick(stop_play_fx))

        # Session
        window.open_videos_requested.connect(lambda paths: session.on_open_videos(paths, render_fx))
        window.session_selected.connect(lambda sid: session.on_session_selected(sid, stop_play_fx, render_fx))

        # Detection
        window.model_changed.connect(lambda model: detector.on_model_changed(model, model_load_fx))
        window.detect_current_frame_requested.connect(lambda: detector.on_detect_current_frame(render_fx))
        window.start_background_detection_requested.connect(detector.on_start_background_detection)
        window.min_confidence_changed.connect(lambda val: detector.on_min_confidence_changed(val, render_fx))
        window.chosen_labels_changed.connect(lambda val: detector.on_chosen_labels_changed(val, render_fx))

        # Tracking
        window.start_tracking_requested.connect(lambda s, src: tracker.on_start_tracking(render_fx))
        window.tracking_strategy_changed.connect(tracker.on_strategy_changed)
        window.tracking_source_changed.connect(tracker.on_source_changed)
        window.min_iou_changed.connect(tracker.on_min_iou_changed)
        window.min_tracker_confidence_changed.connect(tracker.on_min_tracker_confidence_changed)
        window.confidence_decay_changed.connect(tracker.on_confidence_decay_changed)

        # Frame Data Annotation (Row 1)
        window.add_manual_frame_item_requested.connect(lambda: annotator.on_add_manual(render_fx))
        window.edit_selected_frame_item_requested.connect(lambda: annotator.on_edit_selected(render_fx))
        window.delete_selected_frame_item_requested.connect(lambda: annotator.on_delete_selected(render_fx))
        window.duplicate_selected_frame_item_requested.connect(lambda: annotator.on_duplicate_to_next(render_fx))

        # Frame Data Annotation (Row 2)
        window.duplicate_to_prev_frame_requested.connect(lambda: annotator.on_duplicate_to_prev(render_fx))
        window.reset_current_frame_review_requested.connect(lambda: annotator.on_reset_frame(render_fx))
        window.reset_all_review_requested.connect(lambda: annotator.on_reset_all(render_fx))
        window.reset_tracker_frame_requested.connect(lambda: annotator.on_reset_tracker_frame(render_fx))
        window.reset_all_trackers_requested.connect(lambda: annotator.on_reset_all_trackers(render_fx))
        window.delete_next_occurrences_requested.connect(lambda: annotator.on_delete_next_occurrences(render_fx))
        window.delete_prev_occurrences_requested.connect(lambda: annotator.on_delete_prev_occurrences(render_fx))

        # Playback
        window.play_requested.connect(lambda: player.on_play(play_timer.start))
        window.pause_requested.connect(lambda: player.on_pause(stop_play_fx))
        window.next_frame_requested.connect(lambda: player.on_next_frame(stop_play_fx))
        window.previous_frame_requested.connect(lambda: player.on_previous_frame(stop_play_fx))
        window.seek_requested.connect(lambda idx: player.on_seek(idx, stop_play_fx))

        # Export & Preview/Render
        window.export_requested.connect(exporter.on_export)
        window.export_all_requested.connect(exporter.on_export_all)
        window.draw_boxes_changed.connect(lambda val: exporter.on_draw_boxes_changed(val, render_fx))
        window.blur_toggled.connect(lambda val: exporter.on_blur_toggled(val, render_fx))
        window.blur_strength_changed.connect(lambda val: exporter.on_blur_strength_changed(val, render_fx))

    def _render_saved_frame(self, session_id: str) -> None:
        # Local references to the UI components and handlers to shorten code
        window = self._window
        app_coordinator = self._app_coordinator

        # Get index, frame and frame count
        idx = app_coordinator.get_session_current_frame_index(session_id)
        frame = app_coordinator.load_frame(session_id, idx)
        frame_count = app_coordinator.get_session_frame_count(session_id)

        # Render frame
        self._render_frame(session_id, frame)

        # Set UI state
        window.set_status_text(self._app_coordinator.get_active_status_text())
        window.set_seek_range(max(frame_count - 1, 0))
        window.set_seek_value(idx)
        window.set_frame_label_text(self._app_coordinator.get_session_frame_label(session_id))

    def _render_frame(self, session_id: str, frame) -> None:
        # Local references to the UI components and handlers to shorten code
        window = self._window
        app_coordinator = self._app_coordinator

        # Tab index is 0 for frame data, 1 for final frame data
        tab_idx = window.get_active_tab_index()

        detections_data = app_coordinator.get_detections_presentation(session_id)
        trackers_data = app_coordinator.get_trackers_presentation(session_id)

        display_data = detections_data if tab_idx == 0 else trackers_data

        items_to_draw = []
        if app_coordinator.draw_boxes_enabled(session_id):
            items_to_draw = display_data.frame_data_items

        frame_out = draw_frame_overlays(frame, items_to_draw)
        window.preview_widget.set_image(bgr_frame_to_qimage(frame_out))
        window.set_frame_data_items(detections_data.frame_data_items)
        window.set_tracker_data_items(trackers_data.frame_data_items)

    def _stop_playback(self) -> None:
        self._playback_timer.stop()
        self._app_coordinator.stop_all_playback()
        active = self._app_coordinator.get_active_session()
        if active:
            self._window.set_status_text(self._app_coordinator.get_active_status_text())

    def _start_model_load(self, session_id: str, model_name: str) -> None:
        try:
            if self._model_load_thread.isRunning():
                self._window.show_error("Model Change Failed", "A model is already loading.")
                return
        except ValueError:
            logger.opt(exception=True).debug("Model load thread not initialized.  ")

        self._model_load_thread = QThread()
        self._model_load_worker = ModelLoadWorker(self._app_coordinator, session_id, model_name)

        # Create local references to the UI components and worker to shorten code
        window = self._window
        model_load_thread = self._model_load_thread
        model_load_worker = self._model_load_worker

        window.set_detection_loading_state(True)
        window.set_status_text(f"Loading model: {model_name}")

        model_load_worker.moveToThread(model_load_thread)

        model_load_thread.started.connect(model_load_worker.run)
        model_load_worker.finished.connect(lambda sid, m: self._on_model_load_finished(sid, m))
        model_load_worker.failed.connect(lambda sid, m, err: self._on_model_load_failed(sid, m, err))
        model_load_worker.finished.connect(model_load_thread.quit)
        model_load_worker.failed.connect(model_load_thread.quit)
        model_load_thread.finished.connect(self._cleanup_model_load)

        model_load_thread.start()

    def _on_model_load_finished(self, session_id: str, model_name: str) -> None:
        logger.debug(f"Model load finished for session {session_id} with model {model_name}")
        self._window.set_status_text(self._app_coordinator.get_active_status_text())
        self._window.set_frame_data_items([])
        self._render_saved_frame(session_id)

    def _on_model_load_failed(self, session_id: str, model_name: str, err: str) -> None:
        logger.error(f"Model load failed for session {session_id} with model {model_name}: {err}")
        self._window.show_error("Model Load Failed", err)
        active = self._app_coordinator.get_active_session()
        if active:
            self._window.set_status_text(self._app_coordinator.get_active_status_text())

    def _cleanup_model_load(self) -> None:
        self._window.set_detection_loading_state(False)
        try:
            self._model_load_worker.deleteLater()
            self._model_load_worker = None
        except ValueError:
            logger.opt(exception=True).debug("Model load worker was not initialized.")
        try:
            self._model_load_thread.deleteLater()
            self._model_load_thread = None
        except ValueError:
            logger.opt(exception=True).debug("Model load thread was not initialized.")

    def _on_about_to_quit(self) -> None:
        self._stop_playback()
        self._app_coordinator.close()
        try:
            if self._model_load_thread.isRunning():
                self._model_load_thread.quit()
                self._model_load_thread.wait()
        except ValueError:
            logger.opt(exception=True).debug("Model load thread was never initialized, Quitting anyway.")