from __future__ import annotations

import copy
import os
from collections.abc import Iterable

from app.domain.session import Session
from app.infrastructure.video.cv2_vid_reader import OpenCvVideoReader
from app.infrastructure.video.detect_models import get_available_detection_model_names
from app.infrastructure.video.detect_worker import DetectionWorker
from app.infrastructure.video.frame_parser import DetectionResult, FrameParser
from app.presentation.view_models import (
    DetectionModelItemViewModel,
    FrameDataItemViewModel,
    FramePresentationViewModel,
    ReviewFrameItemViewModel,
    SessionListItemViewModel,
)
from app.shared.logging_cfg import get_logger

"""
Application service for the Qt rewrite.

This module contains the main use-case orchestration class used by the UI layer.
`EditorAppService` sits between the Qt controller and the lower-level domain /
infrastructure objects.

Key responsibilities
--------------------
- open videos and create sessions
- track the active session
- load frames for preview/playback
- configure and trigger detection
- maintain the review/edit state for frame items
- expose UI-friendly view models

A/B review model
----------------
The current rewrite follows a practical A/B split for frame items:

- A = raw detection items
  Stored in `raw_frame_items_by_frame_index`.
  These represent model output and should be treated as the raw source state.

- B = reviewed/editable items
  Stored in `review_frame_items_by_frame_index`.
  These are copied from A lazily when a frame first needs review state, then
  mutated by user actions such as delete, duplicate, manual add, and manual move.

Important rules
---------------
- Raw detection state must remain the source of truth for reset operations.
- User edits operate on review state, not raw detection state.
- Reset current frame = rebuild B(frame) from A(frame).
- Reset all review = clear all B state and rebuild lazily from A later.

This module intentionally returns presentation-layer shaped data because the
current rewrite already uses lightweight view models for table/overlay display.
"""

logger = get_logger("Application->EditorAppService")


class EditorAppService:
    """
    Main application-layer service for editor workflows.

    The UI should call this class for user-driven operations such as opening
    videos, switching sessions, rendering frame state, starting detection, and
    editing review items.

    Internally it owns all sessions and provides a stable orchestration boundary
    between UI code and infrastructure code.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._active_session_id: str | None = None
        logger.debug("EditorAppService initialized")

    # --- Properties ---

    @property
    def number_of_sessions(self) -> int:
        """Return the number of open sessions."""
        return len(self._sessions)

    # --- Public API: Session Management ---

    def close(self) -> None:
        """Release readers and stop background workers during application shutdown."""
        logger.info("Closing EditorAppService")
        for session in self._sessions.values():
            if session.has_detection_worker():
                session.detection_worker.stop()
            session.reader.close()

    def get_active_session(self) -> Session | None:
        """Return the active session, if any."""
        if self._active_session_id is None:
            return None
        return self._sessions.get(self._active_session_id)

    def get_active_status_text(self) -> str:
        """Build the status-bar text for the active session."""
        session = self.get_active_session()
        if session is None:
            return "No session loaded"

        metadata = session.metadata
        current_index = session.playback.current_frame_index
        playback_text = "Playing" if session.playback.is_playing else "Paused"
        detection_text = session.settings.detection_model_name

        return (
            f"{os.path.basename(metadata.path)} | "
            f"{metadata.width}x{metadata.height} | "
            f"{metadata.fps:.2f} fps | "
            f"{current_index + 1}/{metadata.frame_count} frames | "
            f"{playback_text} | "
            f"Model: {detection_text}"
        )

    def get_session_list_items(self) -> list[SessionListItemViewModel]:
        """Build the session list model shown in the UI sidebar."""
        items: list[SessionListItemViewModel] = []

        for session in self._sessions.values():
            metadata = session.metadata
            title = os.path.basename(metadata.path)
            subtitle = (
                f"{metadata.width}x{metadata.height} | "
                f"{metadata.fps:.2f} fps | "
                f"{metadata.frame_count} frames"
            )
            items.append(
                SessionListItemViewModel(
                    session_id=session.session_id,
                    title=title,
                    subtitle=subtitle,
                )
            )

        logger.debug("Built {} session list item(s)", len(items))
        return items

    def open_videos(self, paths: Iterable[str]) -> None:
        """
        Open one or more videos and create sessions for them.

        The video path currently doubles as the session id.
        The first opened session becomes the active session if none was active yet.
        """
        for path in paths:
            if path in self._sessions:
                logger.info("Skipping already-open session: {}", path)
                continue

            logger.info("Opening video: {}", path)
            reader = OpenCvVideoReader(path)
            metadata = reader.read_metadata()

            session = Session(
                session_id=path,
                metadata=metadata,
                reader=reader,
            )
            self._sessions[session.session_id] = session
            logger.debug(
                "Created session: id={}, frames={}, fps={}",
                session.session_id,
                metadata.frame_count,
                metadata.fps,
            )

        if self._active_session_id is None and self._sessions:
            self._active_session_id = next(iter(self._sessions.keys()))
            logger.info("Active session initialized: {}", self._active_session_id)

    def set_active_session(self, session_id: str) -> Session:
        """Mark a session as active and return it."""
        session = self._get_session(session_id)

        if self._active_session_id != session_id:
            self._active_session_id = session_id
            logger.debug("Active session set: {}", session_id)

        return session

    # --- Public API: Playback & Navigation ---

    def get_session_current_frame_index(self, session_id: str) -> int:
        """Expose the current playback frame index."""
        session = self._get_session(session_id)
        return session.playback.current_frame_index

    def get_session_frame_count(self, session_id: str) -> int:
        """Expose frame count for UI navigation."""
        session = self._get_session(session_id)
        return session.metadata.frame_count

    def get_session_frame_interval_ms(self, session_id: str) -> int:
        """Convert session FPS into a playback timer interval."""
        session = self._get_session(session_id)
        fps = session.metadata.fps if session.metadata.fps > 1e-6 else 30.0
        interval_ms = max(1, int(round(1000.0 / fps)))
        logger.debug(
            "Frame interval calculated: session_id={}, fps={}, interval_ms={}",
            session_id,
            fps,
            interval_ms,
        )
        return interval_ms

    def get_session_frame_label(self, session_id: str) -> str:
        """Return a human-readable frame label for the UI."""
        session = self._get_session(session_id)
        return f"Frame {session.playback.current_frame_index + 1}/{session.metadata.frame_count}"

    def is_at_last_frame(self, session_id: str) -> bool:
        """Return whether playback is at the final frame."""
        session = self._get_session(session_id)
        if session.metadata.frame_count <= 0:
            return True
        return session.playback.current_frame_index >= session.metadata.frame_count - 1

    def is_session_playing(self, session_id: str) -> bool:
        """Return whether the session is marked as playing."""
        session = self._get_session(session_id)
        return session.playback.is_playing

    def load_first_frame(self, session_id: str):
        """Convenience wrapper for loading the first frame."""
        return self.load_frame(session_id, 0)

    def load_frame(self, session_id: str, frame_index: int):
        """Load a specific frame from a session and update its playback index."""
        session = self._get_session(session_id)

        safe_index = max(0, min(frame_index, max(session.metadata.frame_count - 1, 0)))
        logger.trace(
            "Loading frame: session_id={}, requested_index={}, safe_index={}",
            session_id,
            frame_index,
            safe_index,
        )
        frame = session.reader.read_frame(safe_index)
        session.playback.current_frame_index = safe_index
        return frame

    def load_next_frame(self, session_id: str):
        """Advance to the next frame, clamped at the end of the video."""
        session = self._get_session(session_id)

        next_index = session.playback.current_frame_index + 1
        if next_index >= session.metadata.frame_count:
            next_index = max(session.metadata.frame_count - 1, 0)

        return self.load_frame(session_id, next_index)

    def load_previous_frame(self, session_id: str):
        """Move to the previous frame, clamped at zero."""
        session = self._get_session(session_id)

        previous_index = max(session.playback.current_frame_index - 1, 0)
        return self.load_frame(session_id, previous_index)

    def set_session_playing(self, session_id: str, is_playing: bool) -> Session:
        """Update playback state for a specific session."""
        session = self._get_session(session_id)
        session.playback.is_playing = is_playing
        logger.info("Session playback changed to {} for {}", is_playing, session_id)
        return session

    def stop_all_playback(self) -> None:
        """Stop playback flags for all sessions."""
        logger.info("Stopping all playback sessions")
        for session in self._sessions.values():
            session.playback.is_playing = False
        logger.info("Stopped playback for all sessions")

    # --- Public API: Detection ---

    def detect_current_frame(self, session_id: str) -> list[DetectionResult]:
        """
        Run detection on the current frame only.

        Raw A state is overwritten for that frame.
        Review B state for that frame is cleared so it can be rebuilt from the new raw state.
        """
        session = self._get_session(session_id)
        model_name = session.settings.detection_model_name
        frame_index = session.playback.current_frame_index

        if model_name == "None":
            session.raw_frame_items_by_frame_index.pop(frame_index, None)
            session.review_frame_items_by_frame_index.pop(frame_index, None)
            logger.info("Detect current frame skipped because model is None")
            return []

        if session.parser is None:
            logger.warning("Attempted to detect without a parser, initializing FrameParser...")
            session.parser = FrameParser(model_name)

        frame = self.load_frame(session_id, frame_index)
        detections = session.parser.detect(frame)
        session.raw_frame_items_by_frame_index[frame_index] = self._map_detection_results_to_review_items(detections)
        session.review_frame_items_by_frame_index.pop(frame_index, None)
        logger.info(
            "Detected {} item(s) for session {} at frame {}",
            len(detections),
            session_id,
            frame_index,
        )
        return detections

    def get_selected_detection_model_name(self, session_id: str) -> str:
        """Return the model currently configured for a session."""
        session = self._get_session(session_id)
        return session.settings.detection_model_name

    def set_detection_model(self, session_id: str, model_name: str) -> None:
        """
        Switch the detection model for a session.

        Changing the model invalidates both raw and review caches because any old
        detections were produced by a different parser/model configuration.
        """
        session = self._get_session(session_id)
        session.settings.detection_model_name = model_name
        logger.info("Setting detection model '{}' for session '{}'", model_name, session_id)

        if session.has_detection_worker():
            logger.warning("Stopping existing detection worker for session '{}'", session_id)
            session.detection_worker.stop()
            session.detection_worker = None

        if model_name == "None":
            session.parser = None
            session.raw_frame_items_by_frame_index.clear()
            session.review_frame_items_by_frame_index.clear()
            logger.info("Detection disabled for session {}", session_id)
            return

        if not session.has_parser():
            logger.info("Frame parser was not initialized, initializing...")
            session.parser = FrameParser(model_name)
        else:
            session.parser.set_model(model_name)

        session.raw_frame_items_by_frame_index.clear()
        session.review_frame_items_by_frame_index.clear()
        logger.info("Detection model set for session {}: {}", session_id, model_name)

    def start_background_detection(self, session_id: str) -> None:
        """
        Start async/background detection for the full session video.

        Existing raw/review caches are cleared before the new worker begins filling
        raw detection results.
        """
        session = self._get_session(session_id)
        model_name = session.settings.detection_model_name

        logger.info("Starting background detection for session '{}'...", session_id)

        if model_name == "None":
            logger.error("Attempted to start background detection without choosing a model.")
            raise ValueError("Select a detection model before starting background detection.")

        if not session.has_parser():
            logger.warning("FrameParser not found for session {}, initializing FrameParser('{}')", session_id, model_name)
            session.parser = FrameParser(model_name)

        if session.has_detection_worker() and session.detection_worker.is_running():
            logger.info("Background detection already running for {}", session_id)
            return

        session.raw_frame_items_by_frame_index.clear()
        session.review_frame_items_by_frame_index.clear()
        session.detection_worker = DetectionWorker(session.metadata.path, session.parser)
        session.detection_worker.start()
        logger.info("Background detection started for {}", session_id)

    def sync_detection_cache(self, session_id: str) -> None:
        """
        Pull newly available worker detections into raw A cache.

        This method only fills missing raw frames. It does not overwrite existing
        raw entries, which helps preserve stable review behavior during playback.
        """
        logger.trace("Syncing detection cache for session '{}'...", session_id)
        session = self._get_session(session_id)
        if not session.has_detection_worker():
            logger.warning("Attempted to sync detection cache for session {} without detection_worker present", session_id)
            return

        worker_cache = session.detection_worker.get_all_detections()
        if worker_cache:
            for frame_index, detections in worker_cache.items():
                if frame_index not in session.raw_frame_items_by_frame_index:
                    session.raw_frame_items_by_frame_index[frame_index] = self._map_detection_results_to_review_items(detections)

    # --- Public API: Review & Editing ---

    def add_manual_frame_item(
            self,
            session_id: str,
            label: str,
            bbox_xyxy: tuple[int, int, int, int],
            color_hex: str = "#00ff00",
    ) -> None:
        """Add a new Manual review item to the current frame."""
        session = self._get_session(session_id)
        frame_index = session.playback.current_frame_index

        self._seed_review_frame_from_raw_if_needed(session, frame_index)

        manual_item = ReviewFrameItemViewModel(
            item_id=f"manual-{session.next_annotation_id}",
            source="Manual",
            label=label,
            bbox_xyxy=bbox_xyxy,
            color_hex=color_hex,
            confidence=None,
            item_key=f"manual:manual-{session.next_annotation_id}",
        )
        session.next_annotation_id += 1

        session.review_frame_items_by_frame_index.setdefault(frame_index, []).append(manual_item)
        logger.info(
            "Added manual frame item {} to session {} frame {}",
            manual_item.item_id,
            session_id,
            frame_index,
        )

    def delete_frame_item(self, session_id: str, item_key: str) -> None:
        """Compatibility wrapper for deleting a single item."""
        self.delete_frame_items(session_id, [item_key])

    def delete_frame_items(self, session_id: str, item_keys: Iterable[str]) -> None:
        """
        Delete selected items from review B state on the current frame.

        This does not touch raw A state, so reset can restore the original detection items.
        """
        session = self._get_session(session_id)
        frame_index = session.playback.current_frame_index

        item_keys_set = {item_key for item_key in item_keys if item_key}
        if not item_keys_set:
            return

        self._seed_review_frame_from_raw_if_needed(session, frame_index)
        review_items = session.review_frame_items_by_frame_index.get(frame_index, [])

        session.review_frame_items_by_frame_index[frame_index] = [
            item
            for item in review_items
            if item.item_key not in item_keys_set
        ]

        logger.info(
            "Deleted {} frame item(s) from session {} frame {}",
            len(item_keys_set),
            session_id,
            frame_index,
        )

    def duplicate_frame_item_to_next_frame(self, session_id: str, item_key: str) -> None:
        """Compatibility wrapper for duplicating a single item."""
        self.duplicate_frame_items_to_next_frame(session_id, [item_key])

    def duplicate_frame_items_to_next_frame(self, session_id: str, item_keys: Iterable[str]) -> None:
        """
        Duplicate selected current-frame items into the next frame as Manual items.

        Duplication always creates editable Manual items on the destination frame,
        even when the source item originated from Detection.
        """
        session = self._get_session(session_id)
        current_frame_index = session.playback.current_frame_index
        next_frame_index = min(current_frame_index + 1, max(session.metadata.frame_count - 1, 0))

        if next_frame_index == current_frame_index:
            return

        item_keys_set = {item_key for item_key in item_keys if item_key}
        if not item_keys_set:
            return

        self._seed_review_frame_from_raw_if_needed(session, current_frame_index)
        self._seed_review_frame_from_raw_if_needed(session, next_frame_index)

        source_items = session.review_frame_items_by_frame_index.get(current_frame_index, [])
        items_to_duplicate = [
            item
            for item in source_items
            if item.item_key in item_keys_set
        ]

        if not items_to_duplicate:
            return

        target_items = session.review_frame_items_by_frame_index.setdefault(next_frame_index, [])

        for source_item in items_to_duplicate:
            duplicated_item = ReviewFrameItemViewModel(
                item_id=f"manual-{session.next_annotation_id}",
                source="Manual",
                label=source_item.label,
                bbox_xyxy=source_item.bbox_xyxy,
                color_hex=source_item.color_hex,
                confidence=source_item.confidence,
                item_key=f"manual:manual-{session.next_annotation_id}",
            )
            session.next_annotation_id += 1
            target_items.append(duplicated_item)

        logger.info(
            "Duplicated {} frame item(s) to frame {} for session {}",
            len(items_to_duplicate),
            next_frame_index,
            session_id,
        )

    def get_frame_presentation(self, session_id: str) -> FramePresentationViewModel:
        """
        Build the current frame presentation model for UI rendering.

        This method is the normal UI read path for the frame table and overlay.
        """
        session = self._get_session(session_id)
        if session.has_detection_worker():
            self.sync_detection_cache(session_id)

        frame_index = session.playback.current_frame_index
        review_items = self._get_effective_review_items(session, frame_index)

        items = [
            self._to_frame_data_item_view_model(item)
            for item in review_items
        ]

        return FramePresentationViewModel(frame_data_items=items)

    def get_review_frame_item(self, session_id: str, item_key: str) -> ReviewFrameItemViewModel | None:
        """Return a single review item on the current frame, if present."""
        session = self._get_session(session_id)
        frame_index = session.playback.current_frame_index
        return self._get_review_item_by_key(session, frame_index, item_key)

    def move_manual_frame_items(
            self,
            session_id: str,
            item_keys: Iterable[str],
            delta_x: int,
            delta_y: int,
    ) -> int:
        """
        Move selected Manual items on the current frame by a delta.

        This is used by keyboard nudging in the Qt UI.
        Only Manual items are moved; Detection items are ignored for now to keep
        raw A state immutable.
        """
        session = self._get_session(session_id)
        frame_index = session.playback.current_frame_index

        item_keys_set = {item_key for item_key in item_keys if item_key}
        if not item_keys_set:
            return 0

        self._seed_review_frame_from_raw_if_needed(session, frame_index)
        review_items = session.review_frame_items_by_frame_index.get(frame_index, [])

        moved_count = 0
        for item in review_items:
            if item.item_key not in item_keys_set:
                continue
            if item.source != "Manual":
                continue

            x1, y1, x2, y2 = item.bbox_xyxy
            item.bbox_xyxy = (
                x1 + delta_x,
                y1 + delta_y,
                x2 + delta_x,
                y2 + delta_y,
            )
            moved_count += 1

        logger.info(
            "Moved {} manual frame item(s) in session {} frame {} by dx={}, dy={}",
            moved_count,
            session_id,
            frame_index,
            delta_x,
            delta_y,
        )
        return moved_count

    def reset_all_review_frames(self, session_id: str) -> None:
        """
        Clear all review B state for a session.

        Raw A state is preserved, so review state can be rebuilt lazily later.
        """
        session = self._get_session(session_id)
        session.review_frame_items_by_frame_index.clear()
        logger.info("Reset all review state for session {}", session_id)

    def reset_review_frame(self, session_id: str, frame_index: int) -> None:
        """
        Reset one frame's review B state from raw A state.

        If no raw state exists for that frame, the frame's review state is cleared.
        """
        session = self._get_session(session_id)

        if frame_index in session.raw_frame_items_by_frame_index:
            session.review_frame_items_by_frame_index[frame_index] = copy.deepcopy(
                session.raw_frame_items_by_frame_index[frame_index]
            )
            logger.info("Reset review state for session {} frame {}", session_id, frame_index)
        else:
            session.review_frame_items_by_frame_index.pop(frame_index, None)
            logger.info("Cleared review state for session {} frame {} (no raw source)", session_id, frame_index)

    def update_manual_frame_item(
            self,
            session_id: str,
            item_key: str,
            label: str,
            bbox_xyxy: tuple[int, int, int, int],
    ) -> None:
        """
        Edit an item in review B state.

        Detection items are intentionally not edited in place, because raw A state
        must remain resettable.
        """
        session = self._get_session(session_id)
        frame_index = session.playback.current_frame_index

        item = self._get_review_item_by_key(session, frame_index, item_key)
        if item is None:
            raise ValueError(f"Unknown frame item: {item_key}")

        item.label = label
        item.bbox_xyxy = bbox_xyxy

        logger.info(
            "Updated manual frame item {} in session {} frame {}",
            item_key,
            session_id,
            frame_index,
        )

    # --- Special Methods ---

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(total sessions={len(self._sessions)})"

    # --- Protected Methods ---

    def _get_effective_review_items(self, session: Session, frame_index: int) -> list[ReviewFrameItemViewModel]:
        """
        Return the editable items currently visible for a frame.

        This ensures the frame has B/review state if raw A state exists.
        """
        self._seed_review_frame_from_raw_if_needed(session, frame_index)
        return session.review_frame_items_by_frame_index.get(frame_index, [])

    def _get_review_item_by_key(
            self,
            session: Session,
            frame_index: int,
            item_key: str,
    ) -> ReviewFrameItemViewModel | None:
        """Look up a review item on the current frame by its stable item key."""
        self._seed_review_frame_from_raw_if_needed(session, frame_index)
        review_items = session.review_frame_items_by_frame_index.get(frame_index, [])
        return next((item for item in review_items if item.item_key == item_key), None)

    def _get_session(self, session_id: str) -> Session:
        """Return a known session or raise if the UI references an invalid id."""
        session = self._sessions.get(session_id)
        if session is None:
            logger.error("Attempted to access unknown session: {}", session_id)
            raise KeyError(f"Unknown session id: {session_id}")
        return session

    # --- Static Methods ---

    @staticmethod
    def get_available_detection_models() -> list[DetectionModelItemViewModel]:
        """Expose available model names in a UI-friendly list."""
        return [
            DetectionModelItemViewModel(model_id=model_name, display_name=model_name)
            for model_name in get_available_detection_model_names()
        ]

    @staticmethod
    def _map_detection_results_to_review_items(
            detections: list[DetectionResult],
    ) -> list[ReviewFrameItemViewModel]:
        """
        Convert raw parser results into the review-item shape used by the UI.

        Even though these originate from detection output, they are mapped into
        the common review item structure so the overlay and table can consume one
        consistent item type.
        """
        return [
            ReviewFrameItemViewModel(
                item_id=detection.item_id,
                source="Detection",
                label=detection.label,
                bbox_xyxy=detection.bbox_xyxy,
                color_hex=detection.color_hex,
                confidence=detection.confidence,
                item_key=f"detection:{detection.item_id}",
            )
            for detection in detections
        ]

    @staticmethod
    def _seed_review_frame_from_raw_if_needed(session: Session, frame_index: int) -> None:
        """
        Lazily create editable review state for a frame from raw detections.

        If review state for this frame already exists, it is left untouched.
        If raw state does not exist, nothing is created.
        """
        if frame_index in session.review_frame_items_by_frame_index:
            return

        raw_items = session.raw_frame_items_by_frame_index.get(frame_index)
        if raw_items is None:
            return

        session.review_frame_items_by_frame_index[frame_index] = copy.deepcopy(raw_items)

    @staticmethod
    def _to_frame_data_item_view_model(item: ReviewFrameItemViewModel) -> FrameDataItemViewModel:
        """Map an internal review item to the table/overlay view model used by the UI."""
        return FrameDataItemViewModel(
            item_id=item.item_id,
            source=item.source,
            label=item.label,
            confidence_text="" if item.confidence is None else f"{item.confidence:.2f}",
            bbox_text=(
                f"({item.bbox_xyxy[0]},{item.bbox_xyxy[1]})-"
                f"({item.bbox_xyxy[2]},{item.bbox_xyxy[3]})"
            ),
            color_hex=item.color_hex,
            item_key=item.item_key,
        )