from __future__ import annotations

from dataclasses import dataclass

from matplotlib.pyplot import box

from app.domain.views.view_models import FrameBoxViewModel
from app.shared.logging_cfg import get_logger

logger = get_logger("Domain->Detection")

@dataclass(slots=True)
class DetectionResult:
    """
    Represents the result of an object detection process.

    This class encapsulates the properties of a detected object, including its bounding
    box, confidence score, associated label, unique identifier, and an optional color
    representation. The purpose of this class is to store detection-related information 
    in a structured format, providing methods to convert it for use in other contexts.

    Attributes:
        bbox_xyxy (tuple[int, int, int, int]): The coordinates of the bounding box in 
            (x_min, y_min, x_max, y_max) format.
        confidence (float): The confidence score of the detection, typically expressed 
            as a value between 0 and 1.
        label (str): The label or class name associated with the detected object.
        item_id (str): A unique identifier for the detected item.
        color_hex (str): The hexadecimal color code representing the detection, defaulting to "#808080".
    """
    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    label: str
    item_id: str
    color_hex: str = "#808080"

    def to_frame_box_view_model(self):
        return FrameBoxViewModel(
            id=self.item_id,
            source="Detection",
            label=self.label,
            bbox_xyxy=self.bbox_xyxy,
            color_hex=self.color_hex,
            confidence=self.confidence,
            key=f"det:{self.item_id}"  # <-- Allows Detection Boxes to Be Selected, Edited, Deleted, or Duplicated
        )

    def __post_init__(self):
        logger.trace("Created detection result {}", self)

    def __repr__(self):
        return f"DetectionResult(bbox_xyxy={self.bbox_xyxy}, confidence={self.confidence:.2f}, label={self.label}, item_id={self.item_id})"


