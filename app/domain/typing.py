from app.domain.views import FrameItemViewModel

__all__ = ["FrameItemsByIndex"]

type FrameItemsByIndex = dict[int, list[FrameItemViewModel]]