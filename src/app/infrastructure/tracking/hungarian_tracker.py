"""
HungarianIoUTracker — pure NumPy/SciPy multi-object tracker.

Architectural contract
----------------------
- ZERO Qt dependencies.
- ZERO UI / views imports.
- Accepts and returns only plain Python / NumPy data.
- The TrackingWorker (infrastructure layer) is responsible for unpacking
  ReviewFrameItemViewModel dicts, feeding this engine, and repacking results.

Algorithm
---------
1. For each new frame, compute IoU between all active tracks and all detections.
2. Build a cost matrix  (cost = 1.0 - IoU).
3. Solve the linear assignment problem with scipy.optimize.linear_sum_assignment.
4. Accept matches whose IoU >= iou_threshold.
5. Unmatched detections → new tracks.
6. Unmatched tracks → coast (move by last velocity, decay confidence).
7. Tracks whose confidence drops below min_confidence are pruned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linear_sum_assignment


# ---------------------------------------------------------------------------
# Public data contract
# ---------------------------------------------------------------------------

@dataclass
class TrackInput:
    """One detection handed to the tracker for a single frame."""
    bbox_xyxy: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    confidence: float
    label: str


@dataclass
class TrackState:
    """The live state of one confirmed track, returned per frame."""
    uid: int
    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    label: str
    # velocity in (x, y) pixels — centroid-based, updated on each match
    velocity: tuple[float, float] = field(default=(0.0, 0.0))


# ---------------------------------------------------------------------------
# Internal track record (not exposed to callers)
# ---------------------------------------------------------------------------

@dataclass
class _Track:
    uid: int
    bbox_xyxy: tuple[int, int, int, int]
    confidence: float
    label: str
    velocity: tuple[float, float] = field(default=(0.0, 0.0))

    def centroid(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.bbox_xyxy
        return (x1 + x2) / 2.0, (y1 + y2) / 2.0

    def coast(self, confidence_decay: float) -> None:
        """Advance the track by its velocity and decay confidence."""
        dx, dy = self.velocity
        x1, y1, x2, y2 = self.bbox_xyxy
        self.bbox_xyxy = (
            int(round(x1 + dx)),
            int(round(y1 + dy)),
            int(round(x2 + dx)),
            int(round(y2 + dy)),
        )
        self.confidence = max(0.0, self.confidence - confidence_decay)

    def to_state(self) -> TrackState:
        return TrackState(
            uid=self.uid,
            bbox_xyxy=self.bbox_xyxy,
            confidence=self.confidence,
            label=self.label,
            velocity=self.velocity,
        )


# ---------------------------------------------------------------------------
# IoU utility
# ---------------------------------------------------------------------------

def _iou_matrix(
        tracks: list[_Track],
        detections: list[TrackInput],
) -> np.ndarray:
    """Return an (n_tracks × n_detections) IoU matrix."""
    n_t = len(tracks)
    n_d = len(detections)
    mat = np.zeros((n_t, n_d), dtype=np.float32)

    for ti, track in enumerate(tracks):
        tx1, ty1, tx2, ty2 = track.bbox_xyxy
        for di, det in enumerate(detections):
            dx1, dy1, dx2, dy2 = det.bbox_xyxy

            inter_x1 = max(tx1, dx1)
            inter_y1 = max(ty1, dy1)
            inter_x2 = min(tx2, dx2)
            inter_y2 = min(ty2, dy2)

            inter_w = max(0, inter_x2 - inter_x1)
            inter_h = max(0, inter_y2 - inter_y1)
            inter_area = inter_w * inter_h

            area_t = max(0, tx2 - tx1) * max(0, ty2 - ty1)
            area_d = max(0, dx2 - dx1) * max(0, dy2 - dy1)
            union_area = area_t + area_d - inter_area

            mat[ti, di] = inter_area / union_area if union_area > 0 else 0.0

    return mat


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class HungarianIoUTracker:
    """
    Stateful multi-object tracker using the Hungarian algorithm on IoU cost.

    Instantiate once per tracking session, then call `update()` for each frame
    in chronological order.

    Parameters
    ----------
    iou_threshold:
        Minimum IoU for a track-detection pair to be considered a match.
        Default 0.3.
    confidence_decay:
        Amount subtracted from a coasting track's confidence each frame.
        Default 0.05.
    min_confidence:
        Tracks whose confidence drops below this are pruned.
        Default 0.1.
    """

    def __init__(
            self,
            iou_threshold: float = 0.3,
            confidence_decay: float = 0.05,
            min_confidence: float = 0.1,
    ) -> None:
        self._iou_threshold = iou_threshold
        self._confidence_decay = confidence_decay
        self._min_confidence = min_confidence

        self._tracks: list[_Track] = []
        self._next_uid: int = 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Clear all live tracks and reset the UID counter."""
        self._tracks = []
        self._next_uid = 1

    def update(self, detections: list[TrackInput]) -> list[TrackState]:
        """
        Process one frame of detections and return the list of active tracks.

        Parameters
        ----------
        detections:
            All detections for the current frame.

        Returns
        -------
        list[TrackState]
            Active tracks after matching, coasting, and pruning.
        """
        if not self._tracks and not detections:
            return []

        # --- Step 1: coast all existing tracks (tentatively) ---
        # We apply the actual update below; for now just build the
        # coasted positions for matching.
        coasted_tracks: list[_Track] = []
        for t in self._tracks:
            import copy as _copy
            ct = _copy.copy(t)
            ct.coast(self._confidence_decay)
            coasted_tracks.append(ct)

        # --- Step 2: match ---
        matched_track_ids: set[int] = set()  # indices into coasted_tracks
        matched_det_ids: set[int] = set()  # indices into detections
        matches: list[tuple[int, int]] = []  # (track_idx, det_idx)

        if coasted_tracks and detections:
            iou_mat = _iou_matrix(coasted_tracks, detections)
            cost_mat = 1.0 - iou_mat
            row_inds, col_inds = linear_sum_assignment(cost_mat)

            for row, col in zip(row_inds, col_inds):
                iou_val = iou_mat[row, col]
                if iou_val >= self._iou_threshold:
                    matches.append((row, col))
                    matched_track_ids.add(row)
                    matched_det_ids.add(col)

        # --- Step 3: update matched tracks in-place ---
        for track_idx, det_idx in matches:
            old_track = self._tracks[track_idx]
            det = detections[det_idx]

            old_cx, old_cy = old_track.centroid()
            x1, y1, x2, y2 = det.bbox_xyxy
            new_cx = (x1 + x2) / 2.0
            new_cy = (y1 + y2) / 2.0

            # Update the live track (not the coasted copy)
            old_track.bbox_xyxy = det.bbox_xyxy
            old_track.confidence = 1.0  # reset on match
            old_track.label = det.label
            old_track.velocity = (new_cx - old_cx, new_cy - old_cy)

        # --- Step 4: coast unmatched existing tracks ---
        for idx, track in enumerate(self._tracks):
            if idx not in matched_track_ids:
                track.coast(self._confidence_decay)

        # --- Step 5: spawn new tracks for unmatched detections ---
        for det_idx, det in enumerate(detections):
            if det_idx not in matched_det_ids:
                self._tracks.append(
                    _Track(
                        uid=self._next_uid,
                        bbox_xyxy=det.bbox_xyxy,
                        confidence=det.confidence,
                        label=det.label,
                    )
                )
                self._next_uid += 1

        # --- Step 6: prune dead tracks ---
        self._tracks = [
            t for t in self._tracks if t.confidence >= self._min_confidence
        ]

        return [t.to_state() for t in self._tracks]
