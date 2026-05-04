from dataclasses import dataclass, field

# DATA PANEL SPECIFIC VIEW MODELS


@dataclass(slots=True)
class BoundingBoxViewModel:
    """Represents a view model for a bounding box.

    This class is used for managing and storing attributes related to a bounding box
    such as its `unique identifier`, `source`, `label`, `bounding box coordinates`, `color`, and
    `confidence level`. The class is also optimized for performance using the `slots`
    mechanism in Python.

    Attributes:
        id (str): A unique identifier for the bounding box.
        source (str): The source from which the bounding box originates.
        label (str): The label associated with the bounding box.
        bbox_xyxy (tuple[int, int, int, int]): The bounding box coordinates of the
            bounding box in the format (`x_min`, `y_min`, `x_max`, `y_max`).
        color_hex (str): The color of the bounding box represented in hexadecimal
            format (e.g., "`#FFFFFF`").
        confidence (float | None): The confidence score of the bounding box. Optional.
        key (str): An additional identifier or key for the bounding box. Defaults to
            an empty string.
        bbox_txt (str): The bounding box coordinates formatted as a string.
        confidence_txt (str): The confidence score formatted as a string.
    """

    id: str
    source: str
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    color_hex: str
    confidence: float | None = None
    key: str = ""

    @property
    def confidence_txt(self):
        return f"{self.confidence:.2f}" if self.confidence is not None else "N/A"

    @property
    def bbox_txt(self):
        return f"({self.bbox_xyxy[0]}, {self.bbox_xyxy[1]}), ({self.bbox_xyxy[2]}, {self.bbox_xyxy[3]})"


@dataclass(slots=True)
class FrameBoxesViewModel:
    """
    A table of Bounding Box and Metadata (``BoundingBoxViewModel``) for a single frame.

    Example table:

    ===  ============  ========  ==============  ======================  =========  =====
    ID#  source        label     conf txt        bbox txt                color_hex  key
    ===  ============  ========  ==============  ======================  =========  =====
    0    Detections    Person    0.96            (123,443), (222, 600)   #d3ad3d    key_1
    1    Detections    Bicycle   0.88            (10, 20), (50, 80)      #ff0000    key_2
    2    Manual_Entry  Car       0.99            (100, 100), (300, 300)  #00ff00    key_3
    ===  ============  ========  ==============  ======================  =========  =====

    Attributes:
        frame_data_boxes (list[BoundingBoxViewModel]): A list of ``BoundingBoxViewModel`` objects.
    """

    frame_data_boxes: list[BoundingBoxViewModel] = field(default_factory=list)


# SESSION LIST SPECIFIC VIEW MODELS


@dataclass(slots=True)
class SessionFileListViewModel:
    """
    View model for the list of sessions.
    """

    session_id: str
    title: str
    subtitle: str


@dataclass(slots=True)
class SessionSettingsViewModel:
    """
    Snapshot of ``ProcessingSettings`` shaped for direct widget restoration while
    switching sessions.

    Built by ``Coordinator.get_session_settings()`` on every session switch.
    The UI reads this once and sets all right-panel widgets from it without
    knowing anything about the domain model.

    ``chosen_labels`` is pre-joined as a comma-separated string so the UI can
    assign it directly to a ``QLineEdit`` without any further processing.

    Attributes:
        detection_model_name (str): Name of the detection model to be used.
        min_detection_confidence (float): Minimum confidence threshold for detection.
        chosen_labels (str): Comma-separated list of labels to be selected for detection,
            e.g., `"person, cat, dog"`.
        tracking_strategy (str): Strategy to be used for tracking objects.
        tracking_source (str): Source of input data for tracking purposes.
        min_iou (float): Minimum `Intersection-over-Union (IoU)` threshold for tracking.
        min_tracker_confidence (float): Minimum confidence threshold for the tracker.
        confidence_decay (float): Rate of decay for tracker's confidence over time.
        draw_boxes (bool): Whether to draw bounding boxes in the preview or render output.
        blur_enabled (bool): Whether to enable blurring visual effects in the preview
            or render.
        blur_strength (float): Strength of the blur effect when `blur_enabled` is true.
    """

    # --- Detection ---
    detection_model_name: str
    min_detection_confidence: float
    chosen_labels: str  # comma-separated, e.g. "person, cat, dog"

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


# RIGHT PANEL SPECIFIC VIEW MODELS


@dataclass(slots=True)
class DetectionModelSelectionViewModel:
    """
    Used by
    ``Coordinator.get_available_detection_models()`` -> ``DetectionService.get_available_detection_models()``
    to populate the detection boxes table.

    Attributes:
        model_id (str): Unique identifier for the detection model.
        display_name (str): Human-readable name for the detection model.
    """

    model_id: str
    display_name: str
