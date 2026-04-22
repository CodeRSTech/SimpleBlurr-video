from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FrameAnnotation:
    annotation_id: str
    frame_index: int
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    color_hex: str = "#00ff00"
    confidence: float | None = None
