from dataclasses import dataclass, field


@dataclass(slots=True)
class SessionListItemViewModel:
    session_id: str
    title: str
    subtitle: str


@dataclass(slots=True)
class FrameDataItemViewModel:
    item_id: str
    source: str
    label: str
    confidence_text: str
    bbox_text: str
    color_hex: str
    item_key: str


@dataclass(slots=True)
class FramePresentationViewModel:
    frame_data_items: list[FrameDataItemViewModel] = field(default_factory=list)


@dataclass(slots=True)
class DetectionModelItemViewModel:
    model_id: str
    display_name: str


@dataclass(slots=True)
class FrameItemViewModel:
    item_id: str
    source: str
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    color_hex: str
    confidence: float | None = None
    item_key: str = ""


@dataclass(slots=True)
class SessionSettingsViewModel:
    """
    Snapshot of ProcessingSettings shaped for direct widget restoration.

    Built by EditorFacade.get_session_settings() on every session switch.
    The UI reads this once and sets all right-panel widgets from it without
    knowing anything about the domain model.

    chosen_labels is pre-joined as a comma-separated string so the UI can
    assign it directly to a QLineEdit without any further processing.
    """
    # --- Detection ---
    detection_model_name: str
    min_detection_confidence: float
    chosen_labels: str              # comma-separated, e.g. "person, cat, dog"

    # --- Tracking ---
    tracking_strategy: str
    tracking_source: str
    min_iou: float
    min_tracker_confidence: float
    confidence_decay: float

    # --- Preview / Render ---
    draw_boxes: bool
    blur_enabled: bool
    blur_strength: float
