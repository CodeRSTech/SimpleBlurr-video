from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.state.playback_state import PlaybackState
from .processing_settings import ProcessingSettings
from app.domain.data.vid_data import VideoMetadata

from app.infrastructure.detection.frame_parser import FrameParser
from app.infrastructure.detection.detect_worker import DetectionWorker
from app.infrastructure.video.vid_reader import VideoReader
from app.infrastructure.tracking.track_worker import TrackingWorker

from app.domain.typing import FrameItemsByIndex
from app.shared.logging_cfg import get_logger

logger = get_logger("Domain->Session")


@dataclass(slots=True)
class Session:
    session_id: str
    metadata: VideoMetadata
    reader: VideoReader
    _parser: FrameParser | None = None
    _detection_worker: DetectionWorker | None = None
    _tracking_worker: TrackingWorker | None = None

    # Layer A: Immutable Raw Detections (written only by DetectionWorker)
    raw_frame_boxes_by_frame_index: FrameItemsByIndex = field(default_factory=dict)
    # Layer B: Editable pre-tracking review (lazily seeded from A, user-editable)
    review_frame_boxes_by_frame_index: FrameItemsByIndex = field(default_factory=dict)
    # Layer C: Tracker-derived tracks (written only by TrackingWorker, not user-editable)
    tracked_frame_boxes_by_frame_index: FrameItemsByIndex = field(default_factory=dict)
    # Layer D: Final editable timeline (auto-seeded from C after tracking, user-editable)
    final_frame_boxes_by_frame_index: FrameItemsByIndex = field(default_factory=dict)

    next_annotation_id: int = 1
    playback: PlaybackState = field(default_factory=PlaybackState)
    settings: ProcessingSettings = field(default_factory=ProcessingSettings)

    def __post_init__(self) -> None:
        logger.info("Created session {}", self.session_id)

    @property
    def parser(self) -> FrameParser:
        if self._parser is None:
            raise ValueError("Parser is not initialized")
        return self._parser

    @parser.setter
    def parser(self, parser: FrameParser | None) -> None:
        self._parser = parser

    def has_parser(self) -> bool:
        return self._parser is not None

    @property
    def detection_worker(self) -> DetectionWorker:
        if self._detection_worker is None:
            raise ValueError("Detection worker is not initialized")
        return self._detection_worker

    @detection_worker.setter
    def detection_worker(self, worker: DetectionWorker | None) -> None:
        self._detection_worker = worker

    def has_detection_worker(self) -> bool:
        return self._detection_worker is not None

    @property
    def tracking_worker(self) -> TrackingWorker:
        if self._tracking_worker is None:
            raise ValueError("Tracking worker is not initialized")
        return self._tracking_worker

    @tracking_worker.setter
    def tracking_worker(self, worker: TrackingWorker | None) -> None:
        self._tracking_worker = worker

    def has_tracking_worker(self) -> bool:
        return self._tracking_worker is not None
