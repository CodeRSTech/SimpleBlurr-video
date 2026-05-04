from __future__ import annotations

from app.application.coordinator import AppCoordinator
from app.shared.logging_cfg import get_logger

logger = get_logger("UI->TrackingHandler")


class TrackingHandler:
    def __init__(self, window, app_coordinator: AppCoordinator) -> None:
        self._window = window
        self._app_coordinator = app_coordinator

    def on_start_tracking(self, strategy: str, source: str, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        window = self._window
        app_coordinator = self._app_coordinator

        # --- NEW SAFETY CHECK ---
        active_session = app_coordinator.get_active_session()
        if active_session and active_session.has_detection_worker() and active_session.detection_worker.is_running():
            window.show_error("Action Not Allowed", "Please wait for detection to finish before starting tracking.")
            return
        # ------------------------

        try:
            window.set_tracking_loading_state(True)
            window.set_tracking_config_warning_visible(False)
            app_coordinator.set_active_session(session_id)
            app_coordinator.start_background_tracking(session_id, strategy, source)

            active = app_coordinator.get_active_session()
            if active and active.has_tracking_worker():
                active.tracking_worker.finished_processing.connect(
                    lambda: self._on_tracking_finished(session_id, render_fn)
                )
                active.tracking_worker.error_occurred.connect(self._on_tracking_failed)
        except Exception as exc:
            window.set_tracking_loading_state(False)
            window.show_error("Tracking Failed", str(exc))
            logger.opt(exception=exc).error("Failed to start tracking")

    def on_strategy_changed(self, strategy: str) -> None:
        self._window.set_iou_widgets_visible(strategy == "hungarian")
        self._update_and_warn("tracking_strategy", strategy)

    def on_source_changed(self, source: str) -> None:
        self._update_and_warn("tracking_source", source)

    def on_min_iou_changed(self, value: float) -> None:
        self._update_and_warn("min_iou", value)

    def on_min_tracker_confidence_changed(self, value: float) -> None:
        self._update_and_warn("min_tracker_confidence", value)

    def on_confidence_decay_changed(self, value: float) -> None:
        self._update_and_warn("confidence_decay", value)

    def _update_and_warn(self, key: str, value) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        self._app_coordinator.update_session_settings(session_id, **{key: value})
        active = self._app_coordinator.get_active_session()
        if active and active.tracked_frame_boxs_by_frame_index:
            self._window.set_tracking_config_warning_visible(True)

    def _on_tracking_finished(self, session_id: str, render_fn) -> None:
        logger.info("Tracking finished for session {}", session_id)
        self._app_coordinator.sync_tracking_cache(session_id)
        self._window.set_tracking_loading_state(False)
        render_fn(session_id)

    def _on_tracking_failed(self, error: str) -> None:
        self._window.set_tracking_loading_state(False)
        self._window.show_error("Tracking Error", error)