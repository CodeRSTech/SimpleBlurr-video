from __future__ import annotations

from collections.abc import Iterable

from app.application.services.annotation_service import AnnotationService
from app.application.services.detection_service import DetectionService
from app.application.services.export_service import ExportService
from app.application.session_manager import SessionManager
from app.application.services.tracking_service import TrackingService
from app.domain.session import Session
from app.domain.presentation import (
    DetectionModelItemViewModel,
    FramePresentationViewModel,
    FrameItemViewModel,
    SessionListItemViewModel,
    SessionSettingsViewModel,
)
from app.shared.logging_cfg import get_logger

logger = get_logger("Application->EditorFacade")


class AppCoordinator:
    """
    Thin delegation layer — the only application-layer class the UI imports.
    Owns all four services and the SessionManager.
    Contains zero business logic; every call is forwarded to the correct service.
    """

    def __init__(self) -> None:
        self._sm = SessionManager()
        self._detection = DetectionService(self._sm)
        self._annotation = AnnotationService(self._sm)
        self._tracking = TrackingService(self._sm)
        self._export = ExportService(self._sm)
        logger.debug("EditorFacade initialized")

    def draw_boxes_enabled(self, session_id: str) -> bool:
        return self._sm.get_session(session_id).settings.draw_boxes

    def open_videos(self, paths: Iterable[str]) -> list[str]:
        return self._sm.open_videos(paths)

    def get_active_session(self) -> Session | None:
        return self._sm.get_active_session()

    def set_active_session(self, session_id: str) -> Session:
        return self._sm.set_active_session(session_id)

    def get_session_list_items(self) -> list[SessionListItemViewModel]:
        return self._sm.get_session_list_items()

    def get_active_status_text(self) -> str:
        return self._sm.get_active_status_text()

    def stop_all_playback(self) -> None:
        self._sm.stop_all_playback()

    def close(self) -> None:
        self._sm.close_all()

    def load_frame(self, session_id: str, frame_index: int):
        session = self._sm.get_session(session_id)
        max_idx = max(session.metadata.frame_count - 1, 0)
        safe = max(0, min(frame_index, max_idx))
        frame = session.reader.read_frame(safe)
        session.playback.current_frame_index = safe
        return frame

    def load_next_frame(self, session_id: str):
        session = self._sm.get_session(session_id)
        next_idx = min(
            session.playback.current_frame_index + 1,
            max(session.metadata.frame_count - 1, 0),
        )
        return self.load_frame(session_id, next_idx)

    def load_previous_frame(self, session_id: str):
        session = self._sm.get_session(session_id)
        prev_idx = max(session.playback.current_frame_index - 1, 0)
        return self.load_frame(session_id, prev_idx)

    def load_first_frame(self, session_id: str):
        return self.load_frame(session_id, 0)

    def get_session_frame_count(self, session_id: str) -> int:
        return self._sm.get_session(session_id).metadata.frame_count

    def get_session_current_frame_index(self, session_id: str) -> int:
        return self._sm.get_session(session_id).playback.current_frame_index

    def get_session_frame_interval_ms(self, session_id: str) -> int:
        session = self._sm.get_session(session_id)
        fps = session.metadata.fps if session.metadata.fps > 1e-6 else 30.0
        return max(1, int(round(1000.0 / fps)))

    def get_session_frame_label(self, session_id: str) -> str:
        session = self._sm.get_session(session_id)
        idx = session.playback.current_frame_index
        return f"Frame {idx + 1}/{session.metadata.frame_count}"

    def is_at_last_frame(self, session_id: str) -> bool:
        session = self._sm.get_session(session_id)
        if session.metadata.frame_count <= 0:
            return True
        return session.playback.current_frame_index >= session.metadata.frame_count - 1

    def is_session_playing(self, session_id: str) -> bool:
        return self._sm.get_session(session_id).playback.is_playing

    def set_session_playing(self, session_id: str, is_playing: bool) -> Session:
        session = self._sm.get_session(session_id)
        session.playback.is_playing = is_playing
        return session

    def get_session_settings(self, session_id: str) -> SessionSettingsViewModel:
        s = self._sm.get_session(session_id).settings
        return SessionSettingsViewModel(
            detection_model_name=s.detection_model_name,
            min_detection_confidence=s.min_detection_confidence,
            chosen_labels=", ".join(s.chosen_labels),
            tracking_strategy=s.tracking_strategy,
            tracking_source=s.tracking_source,
            min_iou=s.min_iou,
            min_tracker_confidence=s.min_tracker_confidence,
            confidence_decay=s.confidence_decay,
            draw_boxes=s.draw_boxes,
            blur_enabled=s.blur_enabled,
            blur_strength=s.blur_strength,
        )

    def update_session_settings(self, session_id: str, **kwargs) -> None:
        session = self._sm.get_session(session_id)
        settings = session.settings
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
                logger.debug("Session {} setting '{}' = {}", session_id, key, value)
            else:
                logger.warning("Unknown setting key '{}' ignored", key)

    def get_selected_detection_model_name(self, session_id: str) -> str:
        return self._detection.get_selected_detection_model_name(session_id)

    def get_available_detection_models(self) -> list[DetectionModelItemViewModel]:
        return self._detection.get_available_detection_models()

    def set_detection_model(self, session_id: str, model_name: str) -> None:
        self._detection.set_detection_model(session_id, model_name)

    def detect_current_frame(self, session_id: str) -> None:
        self._detection.detect_current_frame(session_id)

    def start_background_detection(self, session_id: str) -> None:
        try:
            self._detection.start_background_detection(session_id)
        except ValueError:
            logger.opt(exception=True).error("Failed to start background detection")

    def sync_detection_cache(self, session_id: str) -> None:
        self._detection.sync_detection_cache(session_id)

    def apply_filters_to_layer_b(self, session_id: str) -> None:
        self._detection.apply_filters_to_layer_b(session_id)

    def get_detections_presentation(self, session_id: str) -> FramePresentationViewModel:
        session = self._sm.get_session(session_id)
        if session.has_detection_worker():
            self._detection.sync_detection_cache(session_id)
        return self._annotation.get_frame_presentation(session_id)

    def get_review_frame_item(
        self, session_id: str, item_key: str
    ) -> FrameItemViewModel | None:
        return self._annotation.get_review_frame_item(session_id, item_key)

    def add_manual_frame_item(
        self, session_id: str, label: str, bbox_xyxy: tuple[int, int, int, int], color_hex: str = "#00ff00"
    ) -> None:
        self._annotation.add_manual_frame_item(session_id, label, bbox_xyxy, color_hex)

    def update_manual_frame_item(
        self, session_id: str, item_key: str, label: str, bbox_xyxy: tuple[int, int, int, int]
    ) -> None:
        self._annotation.update_manual_frame_item(session_id, item_key, label, bbox_xyxy)

    def delete_frame_items(self, session_id: str, item_keys: Iterable[str]) -> None:
        self._annotation.delete_frame_items(session_id, item_keys)

    def duplicate_frame_items_to_next_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._annotation.duplicate_frame_items_to_next_frame(session_id, item_keys)

    def duplicate_frame_items_to_prev_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._annotation.duplicate_frame_items_to_prev_frame(session_id, item_keys)

    def move_manual_frame_items(
        self, session_id: str, item_keys: Iterable[str], dx: int, dy: int
    ) -> int:
        return self._annotation.move_manual_frame_items(session_id, item_keys, dx, dy)

    def reset_review_frame(self, session_id: str, frame_index: int) -> None:
        self._annotation.reset_review_frame(session_id, frame_index)

    def reset_all_review_frames(self, session_id: str) -> None:
        self._annotation.reset_all_review_frames(session_id)

    def start_background_tracking(self, session_id: str) -> None:
        self._detection.sync_detection_cache(session_id)

        try:
            self._tracking.start_background_tracking(session_id)
        except ValueError:
            logger.opt(exception=True).error("Failed to start background tracking")

    def sync_tracking_cache(self, session_id: str) -> None:
        self._tracking.sync_tracking_cache(session_id)

    def get_trackers_presentation(self, session_id: str) -> FramePresentationViewModel:
        return self._tracking.get_final_presentation(session_id)

    def get_final_frame_item(
        self, session_id: str, item_key: str
    ) -> FrameItemViewModel | None:
        return self._tracking.get_final_frame_item(session_id, item_key)

    def delete_final_frame_items(self, session_id: str, item_keys: Iterable[str]) -> None:
        self._tracking.delete_final_frame_items(session_id, item_keys)

    def duplicate_final_frame_items_to_next_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._tracking.duplicate_final_frame_items_to_next_frame(session_id, item_keys)

    def duplicate_final_frame_items_to_prev_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._tracking.duplicate_final_frame_items_to_prev_frame(session_id, item_keys)

    def move_final_frame_items(
        self, session_id: str, item_keys: Iterable[str], dx: int, dy: int
    ) -> int:
        return self._tracking.move_final_frame_items(session_id, item_keys, dx, dy)

    def reset_final_frame(self, session_id: str, frame_index: int) -> None:
        self._tracking.reset_final_frame(session_id, frame_index)

    def reset_all_final_frames(self, session_id: str) -> None:
        self._tracking.reset_all_final_frames(session_id)

    def delete_next_occurrences(self, session_id: str, item_id: str) -> None:
        self._tracking.delete_next_occurrences(session_id, item_id)

    def delete_prev_occurrences(self, session_id: str, item_id: str) -> None:
        self._tracking.delete_prev_occurrences(session_id, item_id)

    def session_is_ready_for_export(self, session_id: str) -> bool:
        return self._export.session_is_ready_for_export(session_id)

    def export_session(
        self, session_id: str, output_path: str, progress_callback=None
    ) -> None:
        self._export.export_session(session_id, output_path, progress_callback)

    def all_session_ids(self) -> list[str]:
        return self._sm.session_ids()