from __future__ import annotations

import copy
from collections.abc import Iterable

from app.application.session_manager import SessionManager
from app.domain.session import Session
from app.infrastructure.tracking.track_worker import TrackingWorker
from app.domain.views import (
    FrameDataItemViewModel,
    FramePresentationViewModel,
    FrameItemViewModel,
)
from app.shared.logging_cfg import get_logger

logger = get_logger("Application->TrackingService")


class TrackingService:
    """
    Tracking lifecycle and all Layer C / Layer D operations.
    Layer C is immutable (written only by TrackingWorker).
    Layer D is the editable post-tracking working layer, auto-seeded from C.
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def start_background_tracking(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        settings = session.settings
        strategy = settings.tracking_strategy
        source_layer = settings.tracking_source

        if session.has_tracking_worker() and session.tracking_worker.isRunning():
            logger.warning("Tracking already in progress for {}", session_id)
            return

        if source_layer == "layer_a":
            source_data = session.raw_frame_items_by_frame_index
        elif source_layer == "layer_b":
            source_data = session.review_frame_items_by_frame_index
        else:
            raise ValueError(f"Unknown tracking source: {source_layer}")

        if not source_data:
            raise ValueError(f"Source layer '{source_layer}' is empty. Run detection first.")

        session.tracked_frame_items_by_frame_index.clear()
        session.final_frame_items_by_frame_index.clear()

        worker = TrackingWorker(
            strategy_name=strategy,
            source_data=source_data,
            settings=settings,
        )
        session.tracking_worker = worker
        session.tracking_worker.start()
        logger.info("Tracking started for session {} (strategy={}, source={})", session_id, strategy, source_layer)

    def sync_tracking_cache(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        if not session.has_tracking_worker():
            return

        tracked_data = session.tracking_worker.get_tracked_data()
        session.tracked_frame_items_by_frame_index = tracked_data
        session.final_frame_items_by_frame_index = copy.deepcopy(tracked_data)
        self._apply_tracker_confidence_filter(session)

        logger.info(
            "Tracking cache synced for session {}. C frames: {}. D seeded.",
            session_id, len(tracked_data),
        )

    def get_final_presentation(self, session_id: str) -> FramePresentationViewModel:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        items = session.final_frame_items_by_frame_index.get(frame_index, [])
        return FramePresentationViewModel(
            frame_data_items=[self._to_view_model(i) for i in items]
        )

    def get_final_frame_item(
        self, session_id: str, item_key: str
    ) -> FrameItemViewModel | None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        items = session.final_frame_items_by_frame_index.get(frame_index, [])
        return next((i for i in items if i.item_key == item_key), None)

    def delete_final_frame_items(self, session_id: str, item_keys: Iterable[str]) -> None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        keys = {k for k in item_keys if k}
        if not keys:
            return
        items = session.final_frame_items_by_frame_index.get(frame_index, [])
        session.final_frame_items_by_frame_index[frame_index] = [
            i for i in items if i.item_key not in keys
        ]
        logger.info("Deleted {} D item(s) from session {} frame {}", len(keys), session_id, frame_index)

    def duplicate_final_frame_items_to_next_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._duplicate_final_items(session_id, item_keys, direction=1)

    def duplicate_final_frame_items_to_prev_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._duplicate_final_items(session_id, item_keys, direction=-1)

    def move_final_frame_items(
        self,
        session_id: str,
        item_keys: Iterable[str],
        delta_x: int,
        delta_y: int,
    ) -> int:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        keys = {k for k in item_keys if k}
        if not keys:
            return 0
        items = session.final_frame_items_by_frame_index.get(frame_index, [])
        moved = 0
        for item in items:
            if item.item_key not in keys:
                continue
            x1, y1, x2, y2 = item.bbox_xyxy
            item.bbox_xyxy = (x1 + delta_x, y1 + delta_y, x2 + delta_x, y2 + delta_y)
            moved += 1
        return moved

    def reset_final_frame(self, session_id: str, frame_index: int) -> None:
        session = self._sm.get_session(session_id)
        if frame_index in session.tracked_frame_items_by_frame_index:
            session.final_frame_items_by_frame_index[frame_index] = copy.deepcopy(
                session.tracked_frame_items_by_frame_index[frame_index]
            )
        else:
            session.final_frame_items_by_frame_index.pop(frame_index, None)
        logger.info("Reset D frame {} for session {}", frame_index, session_id)

    def reset_all_final_frames(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        session.final_frame_items_by_frame_index = copy.deepcopy(
            session.tracked_frame_items_by_frame_index
        )
        self._apply_tracker_confidence_filter(session)
        logger.info("Reset all D frames for session {}", session_id)

    def delete_next_occurrences(self, session_id: str, item_id: str) -> None:
        session = self._sm.get_session(session_id)
        start = session.playback.current_frame_index + 1
        max_frame = max(session.metadata.frame_count - 1, 0)

        for frame_index in range(start, max_frame + 1):
            items = session.final_frame_items_by_frame_index.get(frame_index, [])
            new_items = [i for i in items if i.item_id != item_id]
            if len(new_items) == len(items):
                break  # item isn't found in this frame — stop
            session.final_frame_items_by_frame_index[frame_index] = new_items

        logger.info("Deleted next occurrences of '{}' from session {}", item_id, session_id)

    def delete_prev_occurrences(self, session_id: str, item_id: str) -> None:
        session = self._sm.get_session(session_id)
        start = session.playback.current_frame_index - 1

        for frame_index in range(start, -1, -1):
            items = session.final_frame_items_by_frame_index.get(frame_index, [])
            new_items = [i for i in items if i.item_id != item_id]
            if len(new_items) == len(items):
                break
            session.final_frame_items_by_frame_index[frame_index] = new_items

        logger.info("Deleted previous occurrences of '{}' from session {}", item_id, session_id)

    @staticmethod
    def _apply_tracker_confidence_filter(session: Session) -> None:
        threshold = session.settings.min_tracker_confidence
        for frame_index, items in list(session.final_frame_items_by_frame_index.items()):
            session.final_frame_items_by_frame_index[frame_index] = [
                i for i in items
                if i.confidence is None or i.confidence >= threshold
            ]

    def _duplicate_final_items(
        self, session_id: str, item_keys: Iterable[str], direction: int
    ) -> None:
        session = self._sm.get_session(session_id)
        current = session.playback.current_frame_index
        last = max(session.metadata.frame_count - 1, 0)
        target = current + direction
        if target < 0 or target > last:
            return

        keys = {k for k in item_keys if k}
        if not keys:
            return

        source_items = session.final_frame_items_by_frame_index.get(current, [])
        to_dup = [i for i in source_items if i.item_key in keys]
        if not to_dup:
            return

        target_list = session.final_frame_items_by_frame_index.setdefault(target, [])
        for src in to_dup:
            target_list.append(FrameItemViewModel(
                item_id=f"manual-{session.next_annotation_id}",
                source="Manual",
                label=src.label,
                bbox_xyxy=src.bbox_xyxy,
                color_hex=src.color_hex,
                confidence=src.confidence,
                item_key=f"manual:manual-{session.next_annotation_id}",
            ))
            session.next_annotation_id += 1

        logger.info("Duplicated {} D item(s) to frame {} session {}", len(to_dup), target, session_id)

    @staticmethod
    def _to_view_model(item: FrameItemViewModel) -> FrameDataItemViewModel:
        """
        Convert a ReviewFrameItemViewModel to a FrameDataItemViewModel.
        """
        return FrameDataItemViewModel(
            item_id=item.item_id,
            source=item.source,
            label=item.label,
            confidence_text="" if item.confidence is None else f"{item.confidence:.2f}",
            bbox_text=(
                f"({item.bbox_xyxy[0]},{item.bbox_xyxy[1]})-"
                f"({item.bbox_xyxy[2]},{item.bbox_xyxy[3]})"
            ),
            color_hex=item.color_hex,
            item_key=item.item_key,
        )