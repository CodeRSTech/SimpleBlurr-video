from dataclasses import dataclass


@dataclass(slots=True)
class ProcessingSettings:
    preview_height: int = 480
    detection_model_name: str = "None"
