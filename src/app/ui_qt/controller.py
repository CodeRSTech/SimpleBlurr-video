from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from app.application.coordinator import AppCoordinator
from app.shared.frame_overlay import draw_frame_overlays
from app.shared.image_utils import bgr_frame_to_qimage
from app.shared.logging_cfg import get_logger
from app.ui_qt.main_win import MainWindow
from app.ui_qt.handlers.annotation_handler import AnnotationHandler
from app.ui_qt.handlers.detection_handler import DetectionHandler
from app.ui_qt.handlers.export_handler import ExportHandler
from app.ui_qt.handlers.playback_handler import PlaybackHandler
from app.ui_qt.handlers.session_handler import SessionHandler
from app.ui_qt.handlers.tracking_handler import TrackingHandler
from app.ui_qt.model_loader import ModelLoadWorker
from PySide6.QtCore import QThread

logger = get_logger("UI->EditorController")


class _FrameTableKeyFilter(QObject):
    def __init__(self, annotation_handler: AnnotationHandler, render_fn) -> None:
        super().__init__()
        self._handler = annotation_handler
        self._render_fn = render_fn

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            return self._handler.handle_nudge_key(event, self._render_fn)
        return False


class EditorController:
    """
    Slimmed Qt application controller.
    Wires UI signals to Handlers. Owns the playback timer and the central frame renderer.
    """

    def __init__(
            self,
            app: QApplication,
            window: MainWindow,
            facade: AppCoordinator,
    ) -> None:
        self._app = app
        self._window = window
        self._facade = facade
        self._playback_timer = QTimer()
        self._playback_timer.setSingleShot(False)

        # Async model loader state
        self._model_load_thread: QThread | None = None
        self._model_load_worker: ModelLoadWorker | None = None

        # Instantiate Handlers
        self._session_handler = SessionHandler(window, facade)
        self._detection_handler = DetectionHandler(window, facade)
        self._tracking_handler = TrackingHandler(window, facade)
        self._annotation_handler = AnnotationHandler(window, facade)
        self._playback_handler = PlaybackHandler(window, facade, self._render_saved_frame)
        self._export_handler = ExportHandler(window, facade)

        self._frame_table_key_filter = _FrameTableKeyFilter(self._annotation_handler, self._render_saved_frame)
        self._window.get_frame_data_table().installEventFilter(self._frame_table_key_filter)
        self._window.frame_tracker_data_table.installEventFilter(self._frame_table_key_filter)

        self._connect_signals()

        # Init model combobox
        self._window.set_detection_model_items(self._facade.get_available_detection_models())
        self._window.set_selected_detection_model("None")

    def _connect_signals(self) -> None:
        # App Lifecycle
        self._app.aboutToQuit.connect(self._on_about_to_quit)
        self._playback_timer.timeout.connect(lambda: self._playback_handler.on_playback_tick(self._stop_playback))

        # Session
        self._window.open_videos_requested.connect(
            lambda paths: self._session_handler.on_open_videos(paths, self._render_saved_frame)
        )
        self._window.session_selected.connect(
            lambda sid: self._session_handler.on_session_selected(sid, self._stop_playback, self._render_saved_frame)
        )

        # Detection
        self._window.detection_model_changed.connect(
            lambda model: self._detection_handler.on_detection_model_changed(model, self._start_model_load)
        )
        self._window.detect_current_frame_requested.connect(
            lambda: self._detection_handler.on_detect_current_frame(self._render_saved_frame)
        )
        self._window.start_background_detection_requested.connect(self._detection_handler.on_start_background_detection)
        self._window.min_confidence_changed.connect(
            lambda val: self._detection_handler.on_min_confidence_changed(val, self._render_saved_frame)
        )
        self._window.chosen_labels_changed.connect(
            lambda val: self._detection_handler.on_chosen_labels_changed(val, self._render_saved_frame)
        )

        # Tracking
        self._window.start_tracking_requested.connect(
            lambda s, src: self._tracking_handler.on_start_tracking(self._render_saved_frame)
        )
        self._window.tracking_strategy_changed.connect(self._tracking_handler.on_strategy_changed)
        self._window.tracking_source_changed.connect(self._tracking_handler.on_source_changed)
        self._window.min_iou_changed.connect(self._tracking_handler.on_min_iou_changed)
        self._window.min_tracker_confidence_changed.connect(self._tracking_handler.on_min_tracker_confidence_changed)
        self._window.confidence_decay_changed.connect(self._tracking_handler.on_confidence_decay_changed)

        # Annotation (Row 1)
        self._window.add_manual_frame_item_requested.connect(
            lambda: self._annotation_handler.on_add_manual(self._render_saved_frame)
        )
        self._window.edit_selected_frame_item_requested.connect(
            lambda: self._annotation_handler.on_edit_selected(self._render_saved_frame)
        )
        self._window.delete_selected_frame_item_requested.connect(
            lambda: self._annotation_handler.on_delete_selected(self._render_saved_frame)
        )
        self._window.duplicate_selected_frame_item_requested.connect(
            lambda: self._annotation_handler.on_duplicate_to_next(self._render_saved_frame)
        )

        # Annotation (Row 2)
        self._window.duplicate_to_prev_frame_requested.connect(
            lambda: self._annotation_handler.on_duplicate_to_prev(self._render_saved_frame)
        )
        self._window.reset_current_frame_review_requested.connect(
            lambda: self._annotation_handler.on_reset_frame(self._render_saved_frame)
        )
        self._window.reset_all_review_requested.connect(
            lambda: self._annotation_handler.on_reset_all(self._render_saved_frame)
        )
        self._window.reset_tracker_frame_requested.connect(
            lambda: self._annotation_handler.on_reset_tracker_frame(self._render_saved_frame)
        )
        self._window.reset_all_trackers_requested.connect(
            lambda: self._annotation_handler.on_reset_all_trackers(self._render_saved_frame)
        )
        self._window.delete_next_occurrences_requested.connect(
            lambda: self._annotation_handler.on_delete_next_occurrences(self._render_saved_frame)
        )
        self._window.delete_prev_occurrences_requested.connect(
            lambda: self._annotation_handler.on_delete_prev_occurrences(self._render_saved_frame)
        )

        # Playback
        self._window.play_requested.connect(
            lambda: self._playback_handler.on_play(self._playback_timer.start)
        )
        self._window.pause_requested.connect(
            lambda: self._playback_handler.on_pause(self._stop_playback)
        )
        self._window.next_frame_requested.connect(
            lambda: self._playback_handler.on_next_frame(self._stop_playback)
        )
        self._window.previous_frame_requested.connect(
            lambda: self._playback_handler.on_previous_frame(self._stop_playback)
        )
        self._window.seek_requested.connect(
            lambda idx: self._playback_handler.on_seek(idx, self._stop_playback)
        )

        # Export & Preview/Render
        self._window.export_requested.connect(self._export_handler.on_export)
        self._window.export_all_requested.connect(self._export_handler.on_export_all)
        self._window.draw_boxes_changed.connect(
            lambda val: self._export_handler.on_draw_boxes_changed(val, self._render_saved_frame)
        )
        self._window.blur_toggled.connect(
            lambda val: self._export_handler.on_blur_toggled(val, self._render_saved_frame)
        )
        self._window.blur_strength_changed.connect(
            lambda val: self._export_handler.on_blur_strength_changed(val, self._render_saved_frame)
        )

    def _render_saved_frame(self, session_id: str) -> None:
        idx = self._facade.get_session_current_frame_index(session_id)
        frame = self._facade.load_frame(session_id, idx)
        self._render_frame(session_id, frame)
        self._window.set_status_text(self._facade.get_active_status_text())

        frame_count = self._facade.get_session_frame_count(session_id)
        self._window.set_seek_range(max(frame_count - 1, 0))
        self._window.set_seek_value(idx)
        self._window.set_frame_label_text(self._facade.get_session_frame_label(session_id))

    def _render_frame(self, session_id: str, frame) -> None:
        tab_idx = self._window.get_active_tab_index()
        pres = self._facade.get_frame_presentation(session_id)
        final_pres = self._facade.get_final_presentation(session_id)

        items_to_draw = []
        if self._facade.get_session_settings(session_id).draw_boxes:
            items_to_draw = pres.frame_data_items if tab_idx == 0 else final_pres.frame_data_items

        frame_out = draw_frame_overlays(frame, items_to_draw)
        self._window.preview_widget.set_image(bgr_frame_to_qimage(frame_out))
        self._window.set_frame_data_items(pres.frame_data_items)
        self._window.set_tracker_data_items(final_pres.frame_data_items)

    def _stop_playback(self) -> None:
        self._playback_timer.stop()
        self._facade.stop_all_playback()
        active = self._facade.get_active_session()
        if active:
            self._window.set_status_text(self._facade.get_active_status_text())

    def _start_model_load(self, session_id: str, model_name: str) -> None:
        if self._model_load_thread and self._model_load_thread.isRunning():
            self._window.show_error("Model Change Failed", "A model is already loading.")
            return

        self._window.set_detection_loading_state(True)
        self._window.set_status_text(f"Loading model: {model_name}")

        self._model_load_thread = QThread()
        # Since _app_service is now facade, we pass facade directly to worker
        self._model_load_worker = ModelLoadWorker(self._facade, session_id, model_name)
        self._model_load_worker.moveToThread(self._model_load_thread)

        self._model_load_thread.started.connect(self._model_load_worker.run)
        self._model_load_worker.finished.connect(
            lambda sid, m: self._on_model_load_finished(sid, m)
        )
        self._model_load_worker.failed.connect(
            lambda sid, m, err: self._on_model_load_failed(sid, m, err)
        )
        self._model_load_worker.finished.connect(self._model_load_thread.quit)
        self._model_load_worker.failed.connect(self._model_load_thread.quit)
        self._model_load_thread.finished.connect(self._cleanup_model_load)

        self._model_load_thread.start()

    def _on_model_load_finished(self, session_id: str, model_name: str) -> None:
        self._window.set_status_text(self._facade.get_active_status_text())
        self._window.set_frame_data_items([])
        self._render_saved_frame(session_id)

    def _on_model_load_failed(self, session_id: str, model_name: str, err: str) -> None:
        self._window.show_error("Model Load Failed", err)
        active = self._facade.get_active_session()
        if active:
            self._window.set_status_text(self._facade.get_active_status_text())

    def _cleanup_model_load(self) -> None:
        self._window.set_detection_loading_state(False)
        if self._model_load_worker:
            self._model_load_worker.deleteLater()
            self._model_load_worker = None
        if self._model_load_thread:
            self._model_load_thread.deleteLater()
            self._model_load_thread = None

    def _on_about_to_quit(self) -> None:
        self._stop_playback()
        self._facade.close()
        if self._model_load_thread and self._model_load_thread.isRunning():
            self._model_load_thread.quit()
            self._model_load_thread.wait()