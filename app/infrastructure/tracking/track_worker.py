from __future__ import annotations

import copy
from typing import Protocol

from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from app.infrastructure.tracking.hungarian_tracker import (
    HungarianIoUTracker,
    TrackInput,
    TrackState,
)
from app.domain.views.view_models import BoundingBoxViewModel
from app.domain.processing_settings import ProcessingSettings
from app.shared.logging_cfg import get_logger
from app.domain.typing import FrameItemsByIndex

logger = get_logger("Infrastructure->Tracking")

_TRACK_PALETTE: list[str] = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#42d4f4",
    "#f032e6", "#bfef45", "#fabed4", "#469990", "#dcbeff",
    "#9a6324", "#fffac8", "#800000", "#aaffc3", "#000075",
    "#a9a9a9", "#ffffff", "#ffe119", "#911eb4", "#ffd8b1",
]


def uid_to_color(uid: int) -> str:
    return _TRACK_PALETTE[(uid - 1) % len(_TRACK_PALETTE)]


class TrackerStrategy(Protocol):
    def track(
        self,
        source_data: FrameItemsByIndex,
    ) -> FrameItemsByIndex: ...


class DummyTracker:
    @staticmethod
    def track(source_data: FrameItemsByIndex) -> FrameItemsByIndex:
        tracked: FrameItemsByIndex = {}
        for frame_idx, items in source_data.items():
            tracked[frame_idx] = []
            for item in items:
                new_item = copy.deepcopy(item)
                new_item.source = "Track (Dummy)"
                new_item.color_hex = "#ff00ff"
                new_item.key = f"track:{new_item.id}"
                tracked[frame_idx].append(new_item)
        return tracked


class HungarianStrategy:
    def __init__(
        self,
        iou_threshold: float = 0.3,
        confidence_decay: float = 0.05,
        min_confidence: float = 0.1,
    ) -> None:
        self._engine = HungarianIoUTracker(
            iou_threshold=iou_threshold,
            confidence_decay=confidence_decay,
            min_confidence=min_confidence,
        )

    def track(
        self,
        source_data: FrameItemsByIndex,
    ) -> FrameItemsByIndex:
        self._engine.reset()
        tracked: FrameItemsByIndex = {}

        for frame_idx in sorted(source_data.keys()):
            detections = [
                TrackInput(
                    bbox_xyxy=item.bbox_xyxy,
                    confidence=item.confidence if item.confidence is not None else 1.0,
                    label=item.label,
                )
                for item in source_data[frame_idx]
            ]
            
            active: list[TrackState] = self._engine.update(detections)
            
            tracked[frame_idx] = [
                BoundingBoxViewModel(
                    id=f"track-{t.uid}",
                    source="Track (Hungarian)",
                    label=t.label,
                    bbox_xyxy=t.bbox_xyxy,
                    color_hex=uid_to_color(t.uid),
                    confidence=round(t.confidence, 4),
                    key=f"track:{t.uid}",
                )
                for t in active
            ]

        return tracked


_STRATEGY_MAP: dict[str, type] = {
    "dummy": DummyTracker,
    "hungarian": HungarianStrategy,
}


class TrackingWorker(QThread):
    progress_updated = Signal(int, int)
    finished_processing = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        strategy_name: str,
        source_data: FrameItemsByIndex,
        settings: ProcessingSettings,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._strategy_name = strategy_name
        self._source_data = copy.deepcopy(source_data)
        self._tracked_data: FrameItemsByIndex = {}
        self._mutex = QMutex()
        self._stop_requested = False
        self._is_complete = False

        strategy_cls = _STRATEGY_MAP.get(strategy_name, DummyTracker)
        
        # Pass tracker params only to strategies that accept them
        if strategy_cls is HungarianStrategy:
            self._tracker: TrackerStrategy = HungarianStrategy(
                iou_threshold=settings.min_iou,
                confidence_decay=settings.confidence_decay,
                min_confidence=settings.min_tracker_confidence
            )
        else:
            self._tracker = strategy_cls()

        logger.info(
            "TrackingWorker initialized: strategy='{}', frames={}",
            strategy_name, len(source_data),
        )

    def stop(self) -> None:
        self._stop_requested = True

    def is_complete(self) -> bool:
        return self._is_complete

    def get_tracked_data(self) -> FrameItemsByIndex:
        with QMutexLocker(self._mutex):
            return copy.deepcopy(self._tracked_data)

    def run(self) -> None:
        try:
            result = self._tracker.track(self._source_data)
            if self._stop_requested:
                return
            with QMutexLocker(self._mutex):
                self._tracked_data = result
            self.progress_updated.emit(len(result), len(result))
            self._is_complete = True
            logger.info("TrackingWorker completed. Tracked frames: {}", len(result))
        except Exception as exc:
            logger.opt(exception=True).exception("TrackingWorker failed")
            self.error_occurred.emit(str(exc))
        finally:
            self.finished_processing.emit()