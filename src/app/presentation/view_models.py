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
class ReviewFrameItemViewModel:
    item_id: str
    source: str
    label: str
    bbox_xyxy: tuple[int, int, int, int]
    color_hex: str
    confidence: float | None = None
    item_key: str = ""
