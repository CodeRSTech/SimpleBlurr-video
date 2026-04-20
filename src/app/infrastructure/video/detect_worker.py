from __future__ import annotations
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from app.infrastructure.video.frame_parser import DetectionResult, FrameParser
from app.infrastructure.video.cv2_vid_reader import OpenCvVideoReader
from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->Video")


# 1. Inherit from QThread
class DetectionWorker(QThread):
    # 2. Define Signals (must be class attributes) to communicate with the GUI
    progress_updated = Signal(int, int)  # Sends: current_frame, total_frames
    finished_processing = Signal()  # Sends notification when done
    error_occurred = Signal(str)  # Sends error messages

    def __init__(self, video_path: str, parser: FrameParser, parent=None) -> None:
        super().__init__(parent)
        self._video_path = video_path
        self._parser = parser
        self._detections_by_frame_index: dict[int, list[DetectionResult]] = {}

        # 3. Use QMutex instead of threading.Lock for Qt consistency
        self._mutex = QMutex()
        self._stop_requested = False
        self._is_complete = False

        logger.info("Initialized QThread detection worker for video: {}", video_path)

    def stop(self) -> None:
        self._stop_requested = True
        logger.info("Detection worker stop requested for {}", self._video_path)

    def is_complete(self) -> bool:
        return self._is_complete

    def get_detections(self, frame_index: int) -> list[DetectionResult] | None:
        # Use QMutexLocker for auto-locking/unlocking scope
        with QMutexLocker(self._mutex):
            detections = self._detections_by_frame_index.get(frame_index)
            if detections is None:
                return None
            return list(detections)

    def get_all_detections(self) -> dict[int, list[DetectionResult]]:
        with QMutexLocker(self._mutex):
            return {
                frame_index: list(detections)
                for frame_index, detections in self._detections_by_frame_index.items()
            }

    # 4. Override the built-in run() method instead of creating a custom _run()
    def run(self) -> None:
        logger.trace("Detection worker QThread running for {}", self._video_path)

        # Kept this exactly as you had it: perfectly isolated to the thread
        reader = OpenCvVideoReader(self._video_path)

        try:
            frame_count = reader.frame_count
            logger.info("Detection worker processing {} frame(s)", frame_count)

            for frame_index in range(frame_count):
                if self._stop_requested:
                    logger.info("Detection worker stopped early")
                    break

                frame = reader.read_frame(frame_index)
                detections = self._parser.detect(frame)

                with QMutexLocker(self._mutex):
                    self._detections_by_frame_index[frame_index] = detections

                # 5. Emit progress to the GUI safely
                self.progress_updated.emit(frame_index + 1, frame_count)

            self._is_complete = True
            logger.info("Detection worker completed for {}", self._video_path)

        except Exception as e:
            logger.opt(exception=True).exception("Detection worker failed")
            self.error_occurred.emit(str(e))

        finally:
            logger.trace("Detection worker QThread stopped running")
            reader.close()
            # 6. Tell the GUI we are completely finished
            self.finished_processing.emit()