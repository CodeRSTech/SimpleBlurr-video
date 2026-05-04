from __future__ import annotations

from app.application.coordinator import Coordinator
from app.shared.logging_cfg import get_logger

logger = get_logger("UI->SessionHandler")


class SessionHandler:
    def __init__(self, window, coordinator: Coordinator) -> None:
        logger.debug("Initializing SessionHandler...")
        self._window = window
        self._coordinator = coordinator
        logger.debug("SessionHandler initialized.")

    def on_open_videos(self, paths: list[str]) -> None:
        try:
            logger.debug("Opening {} video(s)", len(paths))
            self._coordinator.stop_all_playback()
            self._coordinator.open_videos(paths)
            self._window.set_session_items(self._coordinator.get_session_list_items())
            active = self._coordinator.get_active_session()
            if active is not None:
                self._window.select_session(active.session_id)
        except Exception as exc:
            self._window.show_error("Open Video(s) Failed", str(exc))
            logger.opt(exception=exc).error("Failed to open videos")

    def on_session_selected(self, session_id: str, stop_playback_fn, render_fn) -> None:
        logger.info("Session selected: {}", session_id)
        try:
            stop_playback_fn()
            self._coordinator.set_active_session(session_id)
            settings_vm = self._coordinator.get_session_settings(session_id)
            self._window.restore_session_settings(settings_vm)
            render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Session Load Failed", str(exc))
            logger.opt(exception=exc).error("Failed to load session")