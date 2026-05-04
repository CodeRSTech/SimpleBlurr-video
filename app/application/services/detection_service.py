from __future__ import annotations

import copy

from app.application.session_manager import SessionManager
from app.domain.processing_settings import ProcessingSettings
from app.domain.session import Session
from app.infrastructure.detection.detect_models import get_available_detection_model_names
from app.infrastructure.detection.detect_worker import DetectionWorker
from app.infrastructure.detection.frame_parser import FrameParser
from app.domain.data.detection import DetectionResult
from app.domain.views import DetectionModelsViewModel, FrameBoxViewModel
from app.shared.logging_cfg import get_logger

logger = get_logger("Application->DetectionService")


class DetectionService:
    """
    All detection-related operations.
    Responsibilities
    ----------------
    - Model switching (invalidates all layers).
    - Single-frame and background detection.
    - Detection-cache sync from worker.
    - Label and confidence filtering applied to Layer B live.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def get_selected_detection_model_name(self, session_id: str) -> str:
        return self._sm.get_session(session_id).settings.detection_model_name

    @staticmethod
    def get_available_detection_models() -> list[DetectionModelsViewModel]:
        return [
            DetectionModelsViewModel(model_id=n, display_name=n)
            for n in get_available_detection_model_names()
        ]

    def set_detection_model(self, session_id: str, model_name: str, keep_manual: bool = False) -> None:
        session = self._sm.get_session(session_id)
        session.settings.detection_model_name = model_name
        logger.info("Setting detection model '{}' for session '{}' (keep_manual={})",
                    model_name, session_id, keep_manual)

        if session.has_detection_worker():
            logger.warning("Stopping existing detection worker for session '{}'", session_id)
            session.detection_worker.stop()
            session.detection_worker = None

        if model_name == "None":
            session.parser = None
            self._clear_all_layers(session, keep_manual)
            logger.info("Detection disabled for session {}. Layers cleared.", session_id)
            return

        if not session.has_parser():
            session.parser = FrameParser(model_name)
        else:
            session.parser.set_model(model_name)

        self._clear_all_layers(session, keep_manual)
        logger.info("Detection model set for session {}. Layers cleared.", session_id)

    def detect_current_frame(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        model_name = session.settings.detection_model_name

        if model_name == "None":
            session.raw_frame_boxs_by_frame_index.pop(frame_index, None)
            session.review_frame_boxs_by_frame_index.pop(frame_index, None)
            logger.info("Detect current frame skipped: model is None")
            return

        if not session.has_parser():
            session.parser = FrameParser(model_name)

        frame = session.reader.read_frame(frame_index)
        raw_detections = session.parser.detect(frame)
        raw_items = self._map_detections_to_review_items(raw_detections)
        filtered = [i for i in raw_items if self._passes_filter(i, session.settings)]

        session.raw_frame_boxs_by_frame_index[frame_index] = filtered

        # Copy onto Layer B
        session.review_frame_boxs_by_frame_index[frame_index] = copy.deepcopy(filtered)
        logger.info(
            "Detected {} item(s) (after filter) for session {} frame {}",
            len(filtered), session_id, frame_index,
        )

    def start_background_detection(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        model_name = session.settings.detection_model_name

        if model_name == "None":
            raise ValueError("Select a detection model before starting background detection.")

        if not session.has_parser():
            session.parser = FrameParser(model_name)

        if session.has_detection_worker() and session.detection_worker.is_running():
            logger.info("Background detection already running for {}", session_id)
            return

        self._clear_all_layers(session)
        session.detection_worker = DetectionWorker(session.metadata.path, session.parser)
        session.detection_worker.start()
        logger.info("Background detection started for {}.", session_id)

    def sync_detection_cache(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        if not session.has_detection_worker():
            return

        worker_cache = session.detection_worker.get_all_detections()
        for frame_index, raw_detections in worker_cache.items():
            if frame_index in session.raw_frame_boxs_by_frame_index:
                continue

            raw_items = self._map_detections_to_review_items(raw_detections)
            filtered = [i for i in raw_items if self._passes_filter(i, session.settings)]

            # 1. Save to Layer A
            session.raw_frame_boxs_by_frame_index[frame_index] = filtered

            # 2. NEW: Immediately seed Layer B so tracking has data
            session.review_frame_boxs_by_frame_index[frame_index] = copy.deepcopy(filtered)

    def apply_filters_to_layer_b(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        settings = session.settings
        changed_frames = 0

        # We must iterate over Layer A so we can "bring back" boxes if the threshold is lowered
        for frame_index, raw_items in session.raw_frame_boxs_by_frame_index.items():
            current_layer_b = session.review_frame_boxs_by_frame_index.get(frame_index, [])

            # Preserve any manual annotations the user added
            manual_items = [i for i in current_layer_b if i.source != "Detection"]

            # Re-filter the pristine detections from Layer A
            filtered_detections = [i for i in raw_items if self._passes_filter(i, settings)]

            # Combine them
            new_layer_b = manual_items + copy.deepcopy(filtered_detections)

            if len(new_layer_b) != len(current_layer_b):
                session.review_frame_boxs_by_frame_index[frame_index] = new_layer_b
                changed_frames += 1

        logger.info(
            "Applied filters to Layer B for session {}: {} frame(s) changed",
            session_id, changed_frames,
        )

    @staticmethod
    def _passes_filter(item: FrameBoxViewModel, settings: ProcessingSettings) -> bool:
        """
        Determines if a detection item passes the filter criteria based on confidence and label settings.
        """
        conf = item.confidence
        conf_threshold = settings.min_detection_confidence
        labels_choice = settings.chosen_labels

        if conf and conf < conf_threshold:
            return False

        if labels_choice and item.label not in labels_choice:
            return False

        return True

    @staticmethod
    def _map_detections_to_review_items(detections: list[DetectionResult], ) -> list[FrameBoxViewModel]:
        return [ d.to_frame_box_view_model() for d in detections ]

    @staticmethod
    def _clear_all_layers(session: Session, keep_manual: bool = False) -> None:
        """
        Clears the detection and tracking layers.
        If keep_manual is True, preserves items in Layer B and D where source == "Manual".
        """
        # Layer A (Raw detections) and Layer C (Raw tracks) are ALWAYS wiped
        # because they are strictly machine-generated.
        session.raw_frame_boxs_by_frame_index.clear()
        session.tracked_frame_boxs_by_frame_index.clear()

        if keep_manual:
            # Filter Layer B (Review)
            for frame_idx, items in list(session.review_frame_boxs_by_frame_index.items()):
                manual_items = [i for i in items if i.source == "Manual"]
                if manual_items:
                    session.review_frame_boxs_by_frame_index[frame_idx] = manual_items
                else:
                    del session.review_frame_boxs_by_frame_index[frame_idx]

            # Filter Layer D (Final Timeline)
            for frame_idx, items in list(session.final_frame_boxs_by_frame_index.items()):
                manual_items = [i for i in items if i.source == "Manual"]
                if manual_items:
                    session.final_frame_boxs_by_frame_index[frame_idx] = manual_items
                else:
                    del session.final_frame_boxs_by_frame_index[frame_idx]
        else:
            session.review_frame_boxs_by_frame_index.clear()
            session.final_frame_boxs_by_frame_index.clear()