from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ProcessingSettings:
    """
    Per-session configuration for detection, tracking, and preview/render.

    Every field here is owned by one session and restored to the UI
    whenever the user switches to that session. No Qt types live here.

    Detection
    ---------
    detection_model_name:
        The currently selected model identifier (e.g. "yolov8n", "None").
    min_detection_confidence:
        Detections below this score are excluded from Layer B both during
        sync and retroactively when the value changes.
    chosen_labels:
        Only detections whose label appears in this list are included in
        Layer B. Comparison is case-insensitive at the service layer.

    Tracking
    --------
    tracking_strategy:
        Key into the TrackingWorker strategy map (e.g. "hungarian", "dummy").
    tracking_source:
        Which layer feeds the tracker ("layer_a" or "layer_b").
    min_iou:
        IoU threshold for the Hungarian strategy. Matches below this value
        are rejected.
    min_tracker_confidence:
        Tracks whose confidence falls below this value are excluded from
        Layer D. Layer C remains immutable.
    confidence_decay:
        Per-frame confidence drop for unmatched (coasting) tracks.

    Preview / Render
    ----------------
    draw_boxes:
        Whether bounding box overlays are drawn on the preview widget.
        Applies to whichever layer the active tab displays.
    blur_enabled:
        Whether bounding box regions are blurred in the preview and in
        exported video.
    blur_strength:
        Gaussian kernel radius used for blurring. Active only when
        blur_enabled is True.
    """

    # --- Detection ---
    detection_model_name: str = "None"
    min_detection_confidence: float = 0.25
    chosen_labels: list[str] = field(default_factory=lambda: ["person", "cat", "dog"])

    # --- Tracking ---
    tracking_strategy: str = "hungarian"
    tracking_source: str = "layer_b"
    min_iou: float = 0.3
    min_tracker_confidence: float = 0.1
    confidence_decay: float = 0.05

    # --- Preview / Render ---
    draw_boxes: bool = True
    blur_enabled: bool = False
    blur_strength: float = 15.0