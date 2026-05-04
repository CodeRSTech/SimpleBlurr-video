from __future__ import annotations

import csv
import json
import os

import cv2
import numpy as np

from app.application.session_manager import SessionManager
from app.domain.session import Session
from app.shared.logging_cfg import get_logger

logger = get_logger("Application->ExportService")


class ExportService:
    """
    Export Layer D annotations as a blurred video and JSON/CSV sidecar files.
    Single-session export is designed to be called from a background worker
    thread (ExportWorker).
    """

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def session_is_ready_for_export(self, session_id: str) -> bool:
        session = self._sm.get_session(session_id)
        return bool(session.final_frame_boxs_by_frame_index)

    def export_session(
        self,
        session_id: str,
        output_path: str,
        progress_callback=None,
    ) -> None:
        session = self._sm.get_session(session_id)
        self.render_blurred_video(session, output_path, progress_callback)
        base = os.path.splitext(output_path)[0]
        self.export_annotations_json(session, base + ".json")
        self.export_annotations_csv(session, base + ".csv")
        logger.info("Export complete for session {}: {}", session_id, output_path)

    def render_blurred_video(
        self,
        session: Session,
        output_path: str,
        progress_callback=None,
    ) -> None:
        m = session.metadata
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, m.fps, (m.width, m.height))

        if not writer.isOpened():
            raise RuntimeError(f"Could not open VideoWriter for: {output_path}")

        try:
            for frame_index in range(m.frame_count):
                frame = session.reader.read_frame(frame_index)
                if frame is None:
                    logger.warning("Null frame at index {} — skipping", frame_index)
                    continue

                items = session.final_frame_boxs_by_frame_index.get(frame_index, [])
                if session.settings.blur_enabled:
                    for item in items:
                        frame = self._blur_region(
                            frame,
                            item.bbox_xyxy,
                            session.settings.blur_strength,
                        )

                writer.write(frame)

                if progress_callback is not None:
                    progress_callback(frame_index + 1, m.frame_count)

        finally:
            writer.release()

        logger.info("Blurred video written to {}", output_path)

    def export_annotations_json(self, session: Session, output_path: str) -> None:
        data: dict = {
            "session_id": session.session_id,
            "metadata": {
                "width": session.metadata.width,
                "height": session.metadata.height,
                "fps": session.metadata.fps,
                "frame_count": session.metadata.frame_count,
            },
            "frames": {},
        }

        for frame_index, items in sorted(session.final_frame_boxs_by_frame_index.items()):
            data["frames"][str(frame_index)] = [
                {
                    "item_id": i.id,
                    "source": i.source,
                    "label": i.label,
                    "bbox_xyxy": list(i.bbox_xyxy),
                    "confidence": i.confidence,
                    "color_hex": i.color_hex,
                }
                for i in items
            ]

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        logger.info("JSON annotations written to {}", output_path)

    def export_annotations_csv(self, session: Session, output_path: str) -> None:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["frame_index", "item_id", "source", "label",
                 "x1", "y1", "x2", "y2", "confidence", "color_hex"]
            )
            for frame_index, items in sorted(session.final_frame_boxs_by_frame_index.items()):
                for i in items:
                    x1, y1, x2, y2 = i.bbox_xyxy
                    writer.writerow([
                        frame_index, i.id, i.source, i.label,
                        x1, y1, x2, y2,
                        "" if i.confidence is None else f"{i.confidence:.4f}",
                        i.color_hex,
                    ])

        logger.info("CSV annotations written to {}", output_path)

    @staticmethod
    def _blur_region(
        frame: np.ndarray,
        bbox_xyxy: tuple[int, int, int, int],
        strength: float,
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox_xyxy
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        if x2 <= x1 or y2 <= y1:
            return frame

        ksize = max(3, int(strength) | 1)  # must be odd and >= 3
        roi = frame[y1:y2, x1:x2]
        blurred = cv2.GaussianBlur(roi, (ksize, ksize), 0)
        frame[y1:y2, x1:x2] = blurred
        return frame