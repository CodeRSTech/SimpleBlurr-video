from __future__ import annotations

import os
from collections.abc import Iterable

from app.domain.session import Session
from app.infrastructure.video.vid_reader import VideoReader
from app.domain.views import SessionListItemViewModel
from app.shared.logging_cfg import get_logger

logger = get_logger("Application->SessionManager")


class SessionManager:
    """
    Owns the dict of open sessions.
    Single responsibility: open, close, switch, and look up sessions.
    All other services receive a SessionManager reference and call
    get_session() to retrieve domain state.
    """

    def __init__(self) -> None:
        logger.debug("Initializing SessionManager...")
        self._sessions: dict[str, Session] = {}
        self._active_session_id: str | None = None
        logger.debug("SessionManager initialized.")

    # -------------------------------------------------------------------------
    # Session lifecycle
    # -------------------------------------------------------------------------

    def open_videos(self, paths: Iterable[str]) -> list[str]:
        newly_opened: list[str] = []

        for path in paths:
            if path in self._sessions:
                logger.info("Skipping already-open session: {}", path)
                continue

            logger.info("Opening video: {}", path)
            reader = VideoReader(path)
            metadata = reader.read_metadata()
            session = Session(session_id=path, metadata=metadata, reader=reader)
            self._sessions[path] = session
            newly_opened.append(path)
            logger.debug(
                "Created session: id={}, frames={}, fps={}",
                path,
                metadata.frame_count,
                metadata.fps,
            )

        if self._active_session_id is None and self._sessions:
            self._active_session_id = next(iter(self._sessions.keys()))
            logger.info("Active session initialized: {}", self._active_session_id)

        return newly_opened

    def get_session(self, session_id: str) -> Session:
        session = self._sessions.get(session_id)
        if session is None:
            logger.error("Attempted to access unknown session: {}", session_id)
            raise KeyError(f"Unknown session id: {session_id}")
        return session

    def get_active_session(self) -> Session | None:
        if self._active_session_id is None:
            return None
        return self._sessions.get(self._active_session_id)

    def set_active_session(self, session_id: str) -> Session:
        session = self.get_session(session_id)
        if self._active_session_id != session_id:
            self._active_session_id = session_id
            logger.debug("Active session set: {}", session_id)
        return session

    def close_all(self) -> None:
        logger.info("SessionManager closing all sessions")
        for session in self._sessions.values():
            if session.has_detection_worker():
                session.detection_worker.stop()
            if session.has_tracking_worker():
                session.tracking_worker.stop()
            session.reader.close()
        self._sessions.clear()
        self._active_session_id = None

    # -------------------------------------------------------------------------
    # Iteration helpers
    # -------------------------------------------------------------------------

    def all_sessions(self) -> Iterable[Session]:
        return self._sessions.values()

    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    def stop_all_playback(self) -> None:
        logger.trace("Stopping all playback sessions")
        for session in self._sessions.values():
            session.playback.is_playing = False
        logger.trace("Stopped playback for all sessions")

    # -------------------------------------------------------------------------
    # View model builders
    # -------------------------------------------------------------------------

    def get_session_list_items(self) -> list[SessionListItemViewModel]:
        items: list[SessionListItemViewModel] = []
        for session in self._sessions.values():
            m = session.metadata
            items.append(
                SessionListItemViewModel(
                    session_id=session.session_id,
                    title=os.path.basename(m.path),
                    subtitle=f"{m.width}x{m.height} | {m.fps:.2f} fps | {m.frame_count} frames",
                )
            )
        logger.debug("Built {} session list item(s)", len(items))
        return items

    def get_active_status_text(self) -> str:
        session = self.get_active_session()
        if session is None:
            return "No session loaded"
        m = session.metadata
        idx = session.playback.current_frame_index
        state = "Playing" if session.playback.is_playing else "Paused"
        return (
            f"{os.path.basename(m.path)} | "
            f"{m.width}x{m.height} | "
            f"{m.fps:.2f} fps | "
            f"{idx + 1}/{m.frame_count} frames | "
            f"{state} | "
            f"Model: {session.settings.detection_model_name}"
        )

    def __repr__(self) -> str:
        return f"SessionManager(sessions={len(self._sessions)}, active={self._active_session_id})"