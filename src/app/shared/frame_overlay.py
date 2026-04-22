from __future__ import annotations

import cv2
import numpy as np

from app.domain.presentation import FrameDataItemViewModel


def draw_frame_overlays(
        frame: np.ndarray,
        items: list[FrameDataItemViewModel],
) -> np.ndarray:
    if not items:
        return frame

    result = frame.copy()

    for item in items:
        bbox_text = item.bbox_text.strip()
        try:
            start_text, end_text = bbox_text.split("-")
            x1_text, y1_text = start_text.strip("()").split(",")
            x2_text, y2_text = end_text.strip("()").split(",")
            x1 = int(x1_text)
            y1 = int(y1_text)
            x2 = int(x2_text)
            y2 = int(y2_text)
        except Exception:
            continue

        color = _hex_to_bgr(item.color_hex)

        cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
        label = f"{item.item_id}:{item.label} {item.confidence_text}"
        cv2.putText(
            result,
            label,
            (x1, max(15, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
            cv2.LINE_AA,
        )

    return result


def _hex_to_bgr(color_hex: str) -> tuple[int, int, int]:
    value = color_hex.lstrip("#")
    if len(value) != 6:
        return 0, 255, 0

    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError:
        return 0, 255, 0

    return b, g, r
