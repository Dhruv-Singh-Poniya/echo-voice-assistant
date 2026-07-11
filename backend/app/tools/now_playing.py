"""What's playing on this PC — via Windows' system media session (GSMTC).

Windows keeps a global registry of media sessions (the thing the volume-flyout
overlay shows). ANY player that integrates with it — Spotify, YouTube in a
browser, VLC, the Media Player app — reports title/artist/playback state there.
So we never care WHO is playing: one API covers music the user started and
music the assistant started.

WinRT's async API doesn't mix safely with an already-running asyncio loop from
sync code, so the sync wrapper runs each query on a short-lived worker thread
with its own loop.
"""
from __future__ import annotations

import asyncio
import platform
import re
import threading

_STATUS_NAMES = {
    0: "closed",
    1: "opened",
    2: "changing",
    3: "stopped",
    4: "playing",
    5: "paused",
}


def _clean_app_name(aumid: str) -> str:
    """'Brave._crx_cinhimbn...' -> 'Brave'; 'SpotifyAB.SpotifyMusic_x!App' -> 'Spotify'."""
    if not aumid:
        return ""
    name = re.split(r"[._!]", aumid)[0]
    # Store apps often look like 'SpotifyAB' — drop a trailing 'AB'-style suffix
    # only when the second segment repeats the brand (SpotifyAB.SpotifyMusic).
    parts = re.split(r"[._!]", aumid)
    if len(parts) > 1 and parts[1].lower().startswith(name.lower().rstrip("ab")):
        name = re.sub(r"AB$", "", name)
    return name


async def get_async() -> dict:
    """Return {active, status, title, artist, app}. Never raises."""
    empty = {"active": False, "status": "none", "title": "", "artist": "", "app": ""}
    if platform.system() != "Windows":
        return empty
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        manager = await Manager.request_async()
        session = manager.get_current_session()
        if session is None:
            return empty
        info = await session.try_get_media_properties_async()
        playback = session.get_playback_info()
        status = _STATUS_NAMES.get(int(playback.playback_status), "unknown")
        title = (info.title or "").strip()
        if not title or status in {"closed", "stopped"}:
            return empty
        return {
            "active": True,
            "status": status,
            "title": title,
            "artist": (info.artist or "").strip(),
            "app": _clean_app_name(session.source_app_user_model_id or ""),
        }
    except Exception:
        return empty


def get_sync(timeout: float = 5.0) -> dict:
    """Thread-safe sync wrapper — usable from the agent's tool dispatch."""
    result: dict = {"active": False, "status": "none", "title": "", "artist": "", "app": ""}

    def _runner() -> None:
        nonlocal result
        try:
            result = asyncio.run(get_async())
        except Exception:
            pass

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join(timeout)
    return result


def get_now_playing(args: dict) -> str:
    """Tool handler: tell the model (and the user) what's currently playing."""
    info = get_sync()
    if not info["active"]:
        return "Nothing is playing on this PC right now."
    artist = f" by {info['artist']}" if info["artist"] else ""
    app = f" in {info['app']}" if info["app"] else ""
    state = "Paused" if info["status"] == "paused" else "Now playing"
    return f"{state}: {info['title']}{artist}{app}."
