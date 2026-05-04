from app.domain.views import FrameBoxViewModel

__all__ = ["FrameItemsByIndex"]

type FrameItemsByIndex = dict[int, list[FrameBoxViewModel]]