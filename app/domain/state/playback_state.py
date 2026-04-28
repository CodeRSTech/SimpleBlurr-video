from dataclasses import dataclass


@dataclass(slots=True)
class PlaybackState:
    current_frame_index: int = 0
    is_playing: bool = False
