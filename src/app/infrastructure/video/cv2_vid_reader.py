from __future__ import annotations

import cv2
import numpy as np

from app.domain.vid_data import VideoMetadata
from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->Video")


class OpenCvVideoReader:
    def __init__(self, path: str) -> None:
        logger.debug("Initializing OpenCVVideoReader for: {}", path)
        self._path = path
        self._capture = cv2.VideoCapture(path)

        if not self._capture.isOpened():
            raise ValueError(f"Unable to open video file: {path}")

    @property
    def path(self) -> str:
        logger.trace("Getting path from: {}", self._path)
        return self._path

    @property
    def frame_count(self) -> int:
        logger.trace("Getting frame count from: {}", self._path)
        return int(self._capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    @property
    def fps(self) -> float:
        logger.trace("Getting FPS from: {}", self._path)
        return float(self._capture.get(cv2.CAP_PROP_FPS) or 0.0)

    @property
    def width(self) -> int:
        logger.trace("Getting width from: {}", self._path)
        return int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)

    @property
    def height(self) -> int:
        logger.trace("Getting height from: {}", self._path)
        return int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    def close(self) -> None:
        logger.debug("Closing OpenCVVideoReader for: {}", self._path)
        if self._capture is not None:
            self._capture.release()

    def read_metadata(self) -> VideoMetadata:
        logger.debug("Reading metadata for: {}", self._path)
        frame_count = self.frame_count
        fps = self.fps
        width = self.width
        height = self.height

        if fps <= 1e-6:
            fps = 30.0

        return VideoMetadata(
            path=self._path,
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
        )

    def read_frame(self, frame_index: int) -> np.ndarray:
        logger.trace("Reading frame {} from: {}", frame_index, self._path)

        frame_index = max(0, int(frame_index))
        self._capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)

        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise ValueError(f"Unable to read frame {frame_index} from: {self._path}")

        return frame

    def read_next_frame(self) -> tuple[int, np.ndarray]:
        logger.trace("Reading next frame from: {}", self._path)
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise ValueError(f"Unable to read next frame from: {self._path}")

        actual_index = int(self._capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        return actual_index, frame

    def __repr__(self) -> str:
        return f"OpenCVVideoReader(path={self._path}: {self.frame_count} frames, {self.fps} fps)"
