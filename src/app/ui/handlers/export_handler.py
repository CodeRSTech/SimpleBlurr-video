from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog

from app.application.coordinator import AppCoordinator
from app.infrastructure.export.export_all_worker import ExportAllWorker
from app.infrastructure.export.export_worker import ExportWorker
from app.shared.logging_cfg import get_logger
from app.ui.qt.export_all_dlg import ExportAllDialog

logger = get_logger("UI->ExportHandler")


class ExportHandler:
    def __init__(self, window, app_coordinator: AppCoordinator) -> None:
        self._window = window
        self._app_coordinator = app_coordinator
        self._export_worker: ExportWorker | None = None
        self._export_all_worker: ExportAllWorker | None = None

    def on_draw_boxes_changed(self, enabled: bool, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id:
            self._app_coordinator.update_session_settings(session_id, draw_boxes=enabled)
            render_fn(session_id)

    def on_blur_toggled(self, enabled: bool, render_fn) -> None:
        self._window.set_blur_strength_visible(enabled)
        session_id = self._window.get_selected_session_id()
        if session_id:
            self._app_coordinator.update_session_settings(session_id, blur_enabled=enabled)
            render_fn(session_id)

    def on_blur_strength_changed(self, value: float, render_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id:
            self._app_coordinator.update_session_settings(session_id, blur_strength=value)
            render_fn(session_id)

    def on_export(self) -> None:
        session_id = self._window.get_selected_session_id()
        if not session_id:
            return

        if not self._app_coordinator.session_is_ready_for_export(session_id):
            self._window.show_error("Export Failed", "No tracking results to export. Run detection and tracking first.")
            return

        default_name = f"{os.path.splitext(os.path.basename(session_id))[0]}_exported.mp4"
        output_path, _ = QFileDialog.getSaveFileName(
            self._window, "Export Video", default_name, "Video Files (*.mp4)"
        )

        if not output_path:
            return

        self._window.set_status_text("Exporting video...")
        self._window.export_button.setEnabled(False)

        self._export_worker = ExportWorker(self._app_coordinator._export, session_id, output_path)
        self._export_worker.finished_processing.connect(self._on_export_finished)
        self._export_worker.error_occurred.connect(self._on_export_failed)
        self._export_worker.start()

    def on_export_all(self) -> None:
        session_ids = self._app_coordinator.all_session_ids()
        if not session_ids:
            self._window.show_error("Export All", "No videos are open.")
            return

        dlg = ExportAllDialog(self._window)
        if dlg.exec() != ExportAllDialog.DialogCode.Accepted:
            return

        out_dir, prefix, suffix = dlg.get_export_config()
        self._window.set_status_text(f"Batch exporting {len(session_ids)} video(s)...")
        self._window.export_all_button.setEnabled(False)

        self._export_all_worker = ExportAllWorker(self._app_coordinator, session_ids, out_dir, prefix, suffix)
        self._export_all_worker.session_started.connect(
            lambda sid: self._window.set_status_text(f"Exporting: {os.path.basename(sid)}...")
        )
        self._export_all_worker.session_failed.connect(
            lambda sid, err: logger.error("Batch export failed for {}: {}", sid, err)
        )
        self._export_all_worker.finished_processing.connect(self._on_export_all_finished)
        self._export_all_worker.start()

    def _on_export_finished(self) -> None:
        self._window.export_button.setEnabled(True)
        self._window.set_status_text("Export completed.")
        if self._export_worker:
            self._export_worker.deleteLater()
            self._export_worker = None

    def _on_export_failed(self, error: str) -> None:
        self._window.export_button.setEnabled(True)
        self._window.show_error("Export Failed", error)
        if self._export_worker:
            self._export_worker.deleteLater()
            self._export_worker = None

    def _on_export_all_finished(self) -> None:
        self._window.export_all_button.setEnabled(True)
        self._window.set_status_text("Batch export completed.")
        if self._export_all_worker:
            self._export_all_worker.deleteLater()
            self._export_all_worker = None