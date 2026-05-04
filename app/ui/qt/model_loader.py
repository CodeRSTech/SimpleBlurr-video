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

    def __init__(self, app_coordinator: AppCoordinator, session_id: str, model_name: str, keep_manual: bool = True,
                 parent=None) -> None:
        logger.info("Initializing ModelLoadWorker (QThread based) with model: {} (Keep manual annotations = {}",
                    model_name, keep_manual)
        super().__init__(parent)
        self._app_coordinator = app_coordinator
        self._session_id = session_id
        self._model_name = model_name
        self._keep_manual = keep_manual

    def run(self) -> None:
        try:
            logger.info("Starting ModelLoadWorker QThread for session {} with model: {}",
                        self._session_id, self._model_name)
            self._app_coordinator.set_detection_model(self._session_id, self._model_name, self._keep_manual)
            self.finished.emit(self._session_id, self._model_name)
        except Exception as exc:
            logger.opt(exception=True).error("ModelLoadWorker->run() failed !")
            self.failed.emit(self._session_id, self._model_name, str(exc))

    def __repr__(self):
        return f"ModelLoadWorker(session_id={self._session_id}, model_name={self._model_name})"