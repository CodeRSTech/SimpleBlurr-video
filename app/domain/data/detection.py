from __future__ import annotations

from dataclasses import dataclass

from app.domain.views.view_models import FrameItemViewModel
from app.shared.logging_cfg import get_logger

logger = get_logger("Domain->Detection")

@dataclass(slots=True)
class DetectionResult:
    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    label: str
    item_id: str
    color_hex: str = "#808080"

    def to_frame_item_view_model(self):
        return FrameItemViewModel(
            item_id=self.item_id,
            source="Detection",
            label=self.label,
            bbox_xyxy=self.bbox_xyxy,
            color_hex=self.color_hex,
            confidence=self.confidence,
        )

    def __post_init__(self):
        logger.trace("Created detection result {}", self)

    def __repr__(self):
        return f"DetectionResult(bbox_xyxy={self.bbox_xyxy}, confidence={self.confidence:.2f}, label={self.label}, item_id={self.item_id})"


