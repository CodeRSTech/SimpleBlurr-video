from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from app.application.editor_svc import EditorAppService
from app.shared.logging_cfg import get_logger

logger = get_logger("UI->ModelLoadWorker")


class ModelLoadWorker(QObject):
    finished = Signal(str, str)
    failed = Signal(str, str, str)

    def __init__(
        self,
        app_service: EditorAppService,
        session_id: str,
        model_name: str,
    ) -> None:
        super().__init__()
        self._app_service = app_service
        self._session_id = session_id
        self._model_name = model_name

    def run(self) -> None:
        try:
            logger.info(
                "Background model load started: session_id={}, model={}",
                self._session_id,
                self._model_name,
            )
            self._app_service.set_detection_model(self._session_id, self._model_name)
            self.finished.emit(self._session_id, self._model_name)
        except Exception as exc:
            logger.opt(exception=exc).error(
                "Background model load failed: session_id={}, model={}",
                self._session_id,
                self._model_name,
            )
            self.failed.emit(self._session_id, self._model_name, str(exc))
