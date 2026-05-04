from app.domain.views import BoundingBoxViewModel

__all__ = ["FrameItemsByIndex"]

type FrameItemsByIndex = dict[int, list[BoundingBoxViewModel]]