from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.infrastructure.video.detect_models import load_detection_model
from app.shared.logging_cfg import get_logger

logger = get_logger("Infrastructure->Video->FrameParser")


@dataclass(slots=True)
class DetectionResult:
    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    label: str
    item_id: str
    color_hex: str = "#808080"

    def __post_init__(self):
        logger.trace("Created detection result {}", self)


class FrameParser:
    def __init__(self, model_name: str) -> None:
        logger.info("Initializing FrameParser with model {}", model_name)
        self._model_name = model_name
        self._model = self._load_model(model_name)

    @property
    def model_name(self) -> str:
        logger.trace("Returning current model name")
        return self._model_name

    def set_model(self, model_name: str) -> None:
        logger.trace("Setting detection model to {}", model_name)
        self._model_name = model_name
        self._model = self._load_model(model_name)
        logger.info("Switched detection model to {}", model_name)

    def detect(self, frame: np.ndarray) -> list[DetectionResult]:
        logger.trace("Detecting items in frame")
        raw_detections = self._model.detect(frame, None)
        results: list[DetectionResult] = []

        for index, detection in enumerate(raw_detections, start=1):
            try:
                bbox_xyxy = detection["bbox_xyxy"]
                results.append(
                    DetectionResult(
                        bbox_xyxy=(
                            int(bbox_xyxy[0]),
                            int(bbox_xyxy[1]),
                            int(bbox_xyxy[2]),
                            int(bbox_xyxy[3]),
                        ),
                        confidence=float(detection["confidence"]),
                        label=str(detection["label"]),
                        item_id=str(index),
                        color_hex=str(detection.get("color_hex", "#808080")),
                    )
                )
            except Exception:
                logger.opt(exception=True).warning("Failed to map detection result")
                continue

        logger.trace(
            "Detected {} item(s) with {}",
            len(results),
            self._model_name,
        )
        return results

    def _load_model(self, model_name: str):
        logger.info("Loading detection model {}", model_name)
        return load_detection_model(model_name)