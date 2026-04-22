from __future__ import annotations

from app.application.coordinator import AppCoordinator
from app.shared.logging_cfg import get_logger

logger = get_logger("UI->PlaybackHandler")


class PlaybackHandler:
    def __init__(self, window, facade: AppCoordinator, render_fn) -> None:
        self._window = window
        self._facade = facade
        self._render_fn = render_fn

    def on_play(self, timer_start_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            self._facade.set_active_session(session_id)
            self._facade.set_session_playing(session_id, True)
            interval = self._facade.get_session_frame_interval_ms(session_id)
            timer_start_fn(interval)
            self._window.set_status_text(self._facade.get_active_status_text())
        except Exception as exc:
            self._window.show_error("Play Failed", str(exc))

    @staticmethod
    def on_pause(stop_playback_fn) -> None:
        stop_playback_fn()

    def on_next_frame(self, stop_playback_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            stop_playback_fn()
            self._facade.set_active_session(session_id)
            self._facade.load_next_frame(session_id)
            self._render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Next Frame Failed", str(exc))

    def on_previous_frame(self, stop_playback_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            stop_playback_fn()
            self._facade.set_active_session(session_id)
            self._facade.load_previous_frame(session_id)
            self._render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Previous Frame Failed", str(exc))

    def on_seek(self, frame_index: int, stop_playback_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            return
        try:
            stop_playback_fn()
            self._facade.set_active_session(session_id)
            self._facade.load_frame(session_id, frame_index)
            self._render_fn(session_id)
        except Exception as exc:
            self._window.show_error("Seek Failed", str(exc))

    def on_playback_tick(self, stop_playback_fn) -> None:
        session_id = self._window.get_selected_session_id()
        if session_id is None:
            stop_playback_fn()
            return

        try:
            self._facade.set_active_session(session_id)
            if self._facade.is_at_last_frame(session_id):
                stop_playback_fn()
                return

            self._facade.load_next_frame(session_id)
            self._render_fn(session_id)
        except Exception as exc:
            stop_playback_fn()
            logger.opt(exception=exc).error("Playback tick failed")