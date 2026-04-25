from __future__ import annotations

import os

from PySide6.QtCore import QThread, Signal

from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->ExportAllWorker")


class ExportAllWorker(QThread):
    """
    Orchestrates detect → track → export for every session sequentially.
    """

    session_started = Signal(str)          # session_id
    session_finished = Signal(str)         # session_id
    session_failed = Signal(str, str)      # session_id, error_message
    progress_updated = Signal(int, int)    # (sessions_done, total_sessions)
    finished_processing = Signal()

    def __init__(
        self,
        app_coordinator,            # EditorFacade — no circular import
        session_ids: list[str],
        output_dir: str,
        prefix: str,
        suffix: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._app_coordinator = app_coordinator
        self._session_ids = session_ids
        self._output_dir = output_dir
        self._prefix = prefix
        self._suffix = suffix
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        total = len(self._session_ids)
        logger.info("ExportAllWorker started: {} session(s)", total)

        for idx, session_id in enumerate(self._session_ids):
            if self._stop_requested:
                logger.info("ExportAllWorker stopped by request")
                break

            self.session_started.emit(session_id)
            try:
                self._process_session(session_id)
                self.session_finished.emit(session_id)
            except Exception as exc:
                logger.opt(exception=True).exception(
                    "ExportAllWorker failed for session {}", session_id
                )
                self.session_failed.emit(session_id, str(exc))

            self.progress_updated.emit(idx + 1, total)

        self.finished_processing.emit()
        logger.info("ExportAllWorker finished")

    def _process_session(self, session_id: str) -> None:
        app_coordinator = self._app_coordinator
        active = app_coordinator._sm.get_session(session_id)

        # Detection
        if not active.raw_frame_items_by_frame_index:
            logger.info("ExportAll: running detection for {}", session_id)
            try:
                app_coordinator.start_background_detection(session_id)
            except ValueError:
                logger.opt(exception=True).error("Failed to start background detection")
                return
            if active.has_detection_worker():
                active.detection_worker.wait()
            app_coordinator.sync_detection_cache(session_id)

        # Tracking
        if not active.tracked_frame_items_by_frame_index:
            logger.info("ExportAll: running tracking for {}", session_id)
            app_coordinator.start_background_tracking(session_id)
            if active.has_tracking_worker():
                active.tracking_worker.wait()
            app_coordinator.sync_tracking_cache(session_id)

        # Export
        if not app_coordinator.session_is_ready_for_export(session_id):
            raise RuntimeError(f"Session {session_id} has no Layer D data to export.")

        basename = os.path.splitext(os.path.basename(session_id))[0]
        filename = f"{self._prefix}{basename}{self._suffix}.mp4"
        output_path = os.path.join(self._output_dir, filename)

        logger.info("ExportAll: exporting {} → {}", session_id, output_path)
        app_coordinator.export_session(session_id, output_path)