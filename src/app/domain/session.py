from __future__ import annotations

from dataclasses import dataclass, field

from .playback_state import PlaybackState
from .processing_settings import ProcessingSettings
from .vid_data import VideoMetadata

from app.infrastructure.video.frame_parser import FrameParser
from app.infrastructure.video.detect_worker import DetectionWorker
from app.infrastructure.video.cv2_vid_reader import OpenCvVideoReader

from app.presentation.view_models import ReviewFrameItemViewModel
from app.shared.logging_cfg import get_logger

logger = get_logger("Domain->Session")


@dataclass(slots=True)
class Session:
    session_id: str
    metadata: VideoMetadata
    reader: OpenCvVideoReader
    _parser: FrameParser | None = None
    _detection_worker: DetectionWorker | None = None
    raw_frame_items_by_frame_index: dict[int, list[ReviewFrameItemViewModel]] = field(default_factory=dict)
    review_frame_items_by_frame_index: dict[int, list[ReviewFrameItemViewModel]] = field(default_factory=dict)
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

    def has_parser(self) -> bool:
        return self._parser is not None
