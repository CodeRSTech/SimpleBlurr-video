from __future__ import annotations

from PySide6.QtCore import QThread, QMutex, QMutexLocker, Signal

from app.infrastructure.video.frame_parser import DetectionResult, FrameParser
from app.infrastructure.video.cv2_vid_reader import OpenCvVideoReader
from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->Video")


class DetectionWorker(QThread):
    # Added signals to match Qt paradigms while keeping your original methods intact
    progress_updated = Signal(int, int)  # current_frame, total_frames
    finished_processing = Signal()
    error_occurred = Signal(str)

    def __init__(self, video_path: str, parser: FrameParser, parent=None) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._parser = parser
        self._detections_by_frame_index: dict[int, list[DetectionResult]] = {}

        # Replaced threading.Lock() with QMutex()
        self._mutex = QMutex()

        self._stop_requested = False
        self._is_running = False
        self._is_complete = False

        logger.info("Initialized detection worker for video: {}", video_path)

    def start(self, priority: QThread.Priority = QThread.Priority.InheritPriority) -> None:
        logger.info("Starting detection worker for {}", self._video_path)

        # Check both our custom flag and the native QThread state
        if self._is_running or self.isRunning():
            logger.info("Detection worker is already running for {}", self._video_path)
            return

        self._stop_requested = False
        self._is_complete = False
        self._is_running = True

        # Call the native QThread start to invoke run() in the background
        super().start(priority)
        logger.info("Detection worker started for {}", self._video_path)

    def stop(self) -> None:
        self._stop_requested = True
        logger.info("Detection worker stop requested for {}", self._video_path)

    def is_running(self) -> bool:
        logger.trace("Detection worker is_running() called")
        return self._is_running

    def is_complete(self) -> bool:
        logger.trace("Detection worker is_complete() called")
        return self._is_complete

    def get_detections(self, frame_index: int) -> list[DetectionResult] | None:
        logger.trace("Detection worker get_detections() called for frame {}", frame_index)
        with QMutexLocker(self._mutex):
            detections = self._detections_by_frame_index.get(frame_index)
            if detections is None:
                return None
            return list(detections)

    def get_all_detections(self) -> dict[int, list[DetectionResult]]:
        logger.trace("Detection worker get_all_detections() called")
        with QMutexLocker(self._mutex):
            return {
                frame_index: list(detections)
                for frame_index, detections in self._detections_by_frame_index.items()
            }

    def run(self) -> None:
        # Replaced _run() with run() which QThread natively executes
        logger.trace("Detection worker thread running for {}", self._video_path)
        reader = OpenCvVideoReader(self._video_path)

        try:
            frame_count = reader.frame_count
            logger.info(
                "Detection worker processing {} frame(s) for {}",
                frame_count,
                self._video_path,
            )

            for frame_index in range(frame_count):
                if self._stop_requested:
                    logger.info("Detection worker stopped early for {}", self._video_path)
                    return

                frame = reader.read_frame(frame_index)
                detections = self._parser.detect(frame)

                with QMutexLocker(self._mutex):
                    self._detections_by_frame_index[frame_index] = detections

                # Emit progress for UI synchronization if needed
                self.progress_updated.emit(frame_index + 1, frame_count)

            self._is_complete = True
            logger.info("Detection worker completed for {}", self._video_path)

        except Exception as e:
            logger.opt(exception=True).exception(
                "Detection worker failed for {}",
                self._video_path,
            )
            self.error_occurred.emit(str(e))

        finally:
            logger.trace("Detection worker thread stopped running for {}", self._video_path)
            self._is_running = False
            reader.close()
            self.finished_processing.emit()

    def __repr__(self) -> str:
        return "<DetectionWorker {}, thread running = {}>".format(self._video_path, self._is_running)
