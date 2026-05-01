# app/ui/state/preview_state.py
from enum import Enum, auto


class ToolMode(Enum):
    """
    Defines the current interactive mode of the preview canvas.

    ADD: Clicking starts a new bounding box. Ignores existing boxes.
    EDIT: Clicking selects, moves, or resizes an existing box.
    DELETE: Clicking an existing box deletes it instantly.
    """
    ADD = auto()
    EDIT = auto()
    DELETE = auto()