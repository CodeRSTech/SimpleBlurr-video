from __future__ import annotations

from app.application.coordinator import AppCoordinator
from app.shared.logging_cfg import get_logger

logger = get_logger("UI->DetectionHandler")


class DetectionHandler:
    def __init__(self, window, app_coordinator: AppCoordinator) -> None:
        self._window = window
        self._app_coordinator = app_coordinator

    def on_model_changed(self, model_name: str, start_model_load_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        logger.info("Model changed: session={}, model={}", session_id, model_name)
        start_model_load_fn(session_id, model_name)

    def on_detect_current_frame(self, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._app_coordinator.set_active_session(session_id)
            self._app_coordinator.detect_current_frame(session_id)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Detection Failed", str(exc))
            logger.opt(exception=exc).error("Failed to detect current frame")

    def on_start_background_detection(self) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._app_coordinator.set_active_session(session_id)
            self._app_coordinator.start_background_detection(session_id)
            self._window.set_status_text(self._app_coordinator.get_active_status_text())
        except Exception as exc:
            self._window.show_error("Background Detection Failed", str(exc))
            logger.opt(exception=exc).error("Failed to start background detection")

    def on_min_confidence_changed(self, value: float, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        self._app_coordinator.update_session_settings(session_id, min_detection_confidence=value)
        self._app_coordinator.apply_filters_to_layer_b(session_id)
        render_fn(session_id)

    def on_chosen_labels_changed(self, raw: str, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return

        labels = [lbl.strip() for lbl in raw.split(",") if lbl.strip()]
        self._app_coordinator.update_session_settings(session_id, chosen_labels=labels)
        self._app_coordinator.apply_filters_to_layer_b(session_id)
        render_fn(session_id)

        active = self._app_coordinator.get_active_session()
        if active and active.tracked_frame_items_by_frame_index:
            self._window.set_tracking_config_warning_visible(True)