from __future__ import annotations

import copy
from collections.abc import Iterable

from app.application.session_manager import SessionManager
from app.domain.session import Session
from app.domain.views import (
    FrameDataBoxViewModel,
    FrameBoxesViewModel,
    FrameBoxViewModel,
)
from app.shared.logging_cfg import get_logger

logger = get_logger("Application->AnnotationService")


class AnnotationService:
    """
    All Layer B (reviewed detections) CRUD operations.
    Pure user-edit layer — no detection or tracking logic lives here.

    # TODO: Add support for Layer D
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def get_frame_presentation(self, session_id: str) -> FrameBoxesViewModel:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        items = session.review_frame_boxs_by_frame_index.get(frame_index, [])
        return FrameBoxesViewModel(
            frame_data_boxes=[self._to_view_model(i) for i in items]
        )

    def get_review_frame_box(
        self, session_id: str, item_key: str
    ) -> FrameBoxViewModel | None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        items = session.review_frame_boxs_by_frame_index.get(frame_index, [])
        return next((i for i in items if i.key == item_key), None)

    def add_manual_frame_box(
        self,
        session_id: str,
        label: str,
        bbox_xyxy: tuple[int, int, int, int],
        color_hex: str = "#00ff00",
    ) -> None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index

        item = FrameBoxViewModel(
            id=f"manual-{session.next_annotation_id}",
            source="Manual",
            label=label,
            bbox_xyxy=bbox_xyxy,
            color_hex=color_hex,
            confidence=None,
            key=f"manual:manual-{session.next_annotation_id}",
        )
        session.next_annotation_id += 1
        session.review_frame_boxs_by_frame_index.setdefault(frame_index, []).append(item)
        logger.info("Added manual item {} to session {} frame {}", item.id, session_id, frame_index)

    def update_manual_frame_box(
        self,
        session_id: str,
        item_key: str,
        label: str,
        bbox_xyxy: tuple[int, int, int, int],
    ) -> None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        item = self.get_review_frame_box(session_id, item_key)
        if item is None:
            raise ValueError(f"Unknown frame item: {item_key}")
        item.label = label
        item.bbox_xyxy = bbox_xyxy
        logger.info("Updated item {} in session {} frame {}", item_key, session_id, frame_index)

    def delete_frame_boxs(self, session_id: str, item_keys: Iterable[str]) -> None:
        session = self._sm.get_session(session_id)
        frame_index = session.playback.current_frame_index
        keys = {k for k in item_keys if k}
        if not keys:
            return
        items = session.review_frame_boxs_by_frame_index.get(frame_index, [])
        session.review_frame_boxs_by_frame_index[frame_index] = [
            i for i in items if i.key not in keys
        ]
        logger.info("Deleted {} item(s) from session {} frame {}", len(keys), session_id, frame_index)

    def duplicate_frame_boxs_to_next_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._duplicate_items(session_id, item_keys, direction=1)

    def duplicate_frame_boxs_to_prev_frame(
        self, session_id: str, item_keys: Iterable[str]
    ) -> None:
        self._duplicate_items(session_id, item_keys, direction=-1)

    def move_manual_frame_boxs(
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
        items = session.review_frame_boxs_by_frame_index.get(frame_index, [])
        moved = 0
        for item in items:
            if item.key not in keys or item.source != "Manual":
                continue
            x1, y1, x2, y2 = item.bbox_xyxy
            item.bbox_xyxy = (x1 + delta_x, y1 + delta_y, x2 + delta_x, y2 + delta_y)
            moved += 1
        return moved

    def reset_review_frame(self, session_id: str, frame_index: int) -> None:
        session = self._sm.get_session(session_id)
        if frame_index in session.raw_frame_boxs_by_frame_index:
            session.review_frame_boxs_by_frame_index[frame_index] = copy.deepcopy(
                session.raw_frame_boxs_by_frame_index[frame_index]
            )
        else:
            session.review_frame_boxs_by_frame_index.pop(frame_index, None)
        logger.info("Reset review frame {} for session {}", frame_index, session_id)

    def reset_all_review_frames(self, session_id: str) -> None:
        session = self._sm.get_session(session_id)
        session.review_frame_boxs_by_frame_index.clear()
        logger.info("Reset all review frames for session {}", session_id)

    def _duplicate_items(
        self,
        session_id: str,
        item_keys: Iterable[str],
        direction: int,  # +1 = next, -1 = prev
    ) -> None:
        session = self._sm.get_session(session_id)
        current = session.playback.current_frame_index
        max_frame = max(session.metadata.frame_count - 1, 0)

        if direction == 1:
            target = min(current + 1, max_frame)
        else:
            target = max(current - 1, 0)

        if target == current:
            return

        keys = {k for k in item_keys if k}
        if not keys:
            return

        source_items = session.review_frame_boxs_by_frame_index.get(current, [])
        to_duplicate = [i for i in source_items if i.key in keys]
        if not to_duplicate:
            return

        target_items = session.review_frame_boxs_by_frame_index.setdefault(target, [])
        for src in to_duplicate:
            new_item = FrameBoxViewModel(
                id=f"manual-{session.next_annotation_id}",
                source="Manual",
                label=src.label,
                bbox_xyxy=src.bbox_xyxy,
                color_hex=src.color_hex,
                confidence=src.confidence,
                key=f"manual:manual-{session.next_annotation_id}",
            )
            session.next_annotation_id += 1
            target_items.append(new_item)

        logger.info(
            "Duplicated {} item(s) from frame {} to frame {} for session {}",
            len(to_duplicate), current, target, session_id,
        )

    @staticmethod
    def _seed_review_frame_from_raw(session: Session, frame_index: int) -> None:
        if frame_index in session.review_frame_boxs_by_frame_index:
            return
        raw = session.raw_frame_boxs_by_frame_index.get(frame_index)
        if raw is None:
            return
        session.review_frame_boxs_by_frame_index[frame_index] = copy.deepcopy(raw)

    @staticmethod
    def _to_view_model(item: FrameBoxViewModel) -> FrameDataBoxViewModel:
        return FrameDataBoxViewModel(
            id=item.id,
            source=item.source,
            label=item.label,
            confidence_txt="" if item.confidence is None else f"{item.confidence:.2f}",
            bbox_txt=(
                f"({item.bbox_xyxy[0]},{item.bbox_xyxy[1]})-"
                f"({item.bbox_xyxy[2]},{item.bbox_xyxy[3]})"
            ),
            color_hex=item.color_hex,
            key=item.key,
        )