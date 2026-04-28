from dataclasses import dataclass


@dataclass(slots=True)
class VideoMetadata:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int
