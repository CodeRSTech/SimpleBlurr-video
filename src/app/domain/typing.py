from app.domain.presentation import FrameItemViewModel

__all__ = ["FrameItemsByIndex"]

type FrameItemsByIndex = dict[int, list[FrameItemViewModel]]