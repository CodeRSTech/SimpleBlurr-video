from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.application.coordinator import AppCoordinator
from app.shared.logging_cfg import get_logger

logger = get_logger("UI->ModelLoader")


class ModelLoadWorker(QThread):
    """
    Background worker to load a detection model without freezing the UI.
    """
    finished = Signal(str, str)        # session_id, model_name
    failed = Signal(str, str, str)     # session_id, model_name, error_message

    def __init__(
        self,
        facade: AppCoordinator,
        session_id: str,
        model_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._facade = facade
        self._session_id = session_id
        self._model_name = model_name

    def run(self) -> None:
        logger.info("ModelLoadWorker started: session={}, model={}", self._session_id, self._model_name)
        try:
            self._facade.set_detection_model(self._session_id, self._model_name)
            self.finished.emit(self._session_id, self._model_name)
        except Exception as exc:
            logger.opt(exception=True).error("ModelLoadWorker failed")
            self.failed.emit(self._session_id, self._model_name, str(exc))