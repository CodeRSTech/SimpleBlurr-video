from __future__ import annotations

import av
import math
import numpy as np

from app.domain.data.vid_data import VideoMetadata
from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->Video")


class VideoReader:
    def __init__(self, path: str) -> None:
        logger.debug("Initializing AvVideoReader for: {}", path)
        self._path = path
        self._current_index = 0
        self._frame_iter = None

        try:
            self._container = av.open(path)
            self._stream = self._container.streams.video[0]
            # Enable FFmpeg's internal multi-threading for faster decoding
            self._stream.thread_type = "AUTO"
        except Exception as e:
            raise ValueError(f"Unable to open video file: {path}. Error: {e}")

    @property
    def path(self) -> str:
        return self._path

    @property
    def frame_count(self) -> int:
        # Fallback to 0 if the container header is missing frame count metadata
        return self._stream.frames or 0

    @property
    def fps(self) -> float:
        return float(self._stream.average_rate)

    @property
    def width(self) -> int:
        return self._stream.codec_context.width

    @property
    def height(self) -> int:
        return self._stream.codec_context.height

    def close(self) -> None:
        logger.debug("Closing AvVideoReader for: {}", self._path)
        if self._container is not None:
            self._container.close()
            self._container = None
            self._frame_iter = None

    def read_metadata(self) -> VideoMetadata:
        logger.debug("Reading metadata for: {}", self._path)
        fps = self.fps
        if fps <= 1e-6:
            fps = 30.0

        return VideoMetadata(
            path=self._path,
            width=self.width,
            height=self.height,
            fps=fps,
            frame_count=self.frame_count,
        )

    def read_frame(self, frame_index: int) -> np.ndarray:
        """Frame-accurate random access (used for timeline scrubbing)."""
        logger.trace("Reading frame {} from: {}", frame_index, self._path)
        frame_index = max(0, int(frame_index))

        # 1. Calculate the target timestamp in the stream's time_base
        target_sec = frame_index / self.fps
        target_pts = int(target_sec / self._stream.time_base)

        # 2. Seek to the nearest keyframe BEFORE the target timestamp
        self._container.seek(target_pts, stream=self._stream)

        # 3. Reset the sequential iterator because the playhead has moved
        self._frame_iter = self._container.decode(self._stream)

        # 4. Decode forward until we hit the exact frame
        for frame in self._frame_iter:
            # Calculate the current frame index based on its presentation timestamp (PTS)
            # This is much safer than relying on frame.index for VFR video
            current_idx = math.floor(frame.time * self.fps)

            if current_idx >= frame_index:
                self._current_index = current_idx + 1
                # Return in BGR format to maintain strict OpenCV compatibility
                return frame.to_ndarray(format='bgr24')

        raise ValueError(f"Unable to read frame {frame_index} from: {self._path}")

    def read_next_frame(self) -> tuple[int, np.ndarray]:
        """Fast sequential reading (used for normal video playback)."""
        logger.trace("Reading next frame from: {}", self._path)

        if self._frame_iter is None:
            self._frame_iter = self._container.decode(self._stream)

        try:
            frame = next(self._frame_iter)
            actual_index = math.floor(frame.time * self.fps)
            self._current_index = actual_index + 1

            return actual_index, frame.to_ndarray(format='bgr24')

        except StopIteration:
            raise ValueError(f"End of stream reached or unable to read next frame from: {self._path}")

    def __repr__(self) -> str:
        return f"AvVideoReader(path={self._path}: {self.frame_count} frames, {self.fps} fps)"