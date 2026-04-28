from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.application.services.export_service import ExportService
from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->ExportWorker")


class ExportWorker(QThread):
    """
    Background worker for single-session export.
    Calls ExportService.export_session() on a worker thread so the UI
    stays responsive during video rendering.
    """

    progress_updated = Signal(int, int)   # (current_frame, total_frames)
    finished_processing = Signal()
    error_occurred = Signal(str)

    def __init__(
        self,
        export_service: ExportService,
        session_id: str,
        output_path: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._export_service = export_service
        self._session_id = session_id
        self._output_path = output_path

    def run(self) -> None:
        logger.info("ExportWorker started: session={}, output={}", self._session_id, self._output_path)
        try:
            self._export_service.export_session(
                self._session_id,
                self._output_path,
                progress_callback=lambda cur, tot: self.progress_updated.emit(cur, tot),
            )
        except Exception as exc:
            logger.opt(exception=True).exception("ExportWorker failed")
            self.error_occurred.emit(str(exc))
        finally:
            self.finished_processing.emit()