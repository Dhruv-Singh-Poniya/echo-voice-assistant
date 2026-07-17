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
    sessions = list_sessions_sync()
    if not sessions:
        return "Nothing is playing on this PC right now."
    parts = []
    for s in sessions:
        artist = f" by {s['artist']}" if s["artist"] else ""
        parts.append(f"{s['title']}{artist} ({s['status']} in {s['app']})")
    return "Media sessions: " + "; ".join(parts) + "."


# ---------------------------------------------------------------------------
# Per-session control — the fix for "pause hits the wrong app".
# Every media app has its OWN session here; instead of firing a global media
# key (which Windows routes to whichever session it considers active), we pick
# the session the user actually means and control just that one.
# ---------------------------------------------------------------------------

async def _all_sessions() -> list[tuple]:
    """Return [(session, info_dict)] for every current media session."""
    out = []
    if platform.system() != "Windows":
        return out
    try:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager as Manager,
        )

        manager = await Manager.request_async()
        for session in manager.get_sessions():
            try:
                info = await session.try_get_media_properties_async()
                playback = session.get_playback_info()
                out.append(
                    (
                        session,
                        {
                            "app": _clean_app_name(session.source_app_user_model_id or ""),
                            "title": (info.title or "").strip(),
                            "artist": (info.artist or "").strip(),
                            "status": _STATUS_NAMES.get(int(playback.playback_status), "unknown"),
                        },
                    )
                )
            except Exception:
                continue
    except Exception:
        pass
    return out


def list_sessions_sync(timeout: float = 5.0) -> list[dict]:
    result: list[dict] = []

    def _runner() -> None:
        nonlocal result
        try:
            result = [info for _, info in asyncio.run(_all_sessions())]
        except Exception:
            pass

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join(timeout)
    return result


def _match_session(pairs: list[tuple], target: str, want_status: str | None) -> tuple | None:
    """Pick the session the user means.

    1. A named target ('spotify', 'brave', part of the title) wins.
    2. Otherwise a session in the state we want to change (playing for pause,
       paused for resume) — preferring real music apps over browsers, since
       'the music' usually doesn't mean a browser tab's video.
    """
    if target:
        t = target.lower()
        for pair in pairs:
            info = pair[1]
            if t in info["app"].lower() or t in info["title"].lower() or t in info["artist"].lower():
                return pair
        return None
    candidates = [p for p in pairs if want_status is None or p[1]["status"] == want_status]
    if not candidates:
        return None
    music_apps = ("spotify", "music", "vlc", "winamp", "foobar")
    for pair in candidates:
        if any(m in pair[1]["app"].lower() for m in music_apps):
            return pair
    return candidates[0]


async def _control_async(action: str, target: str) -> str:
    pairs = await _all_sessions()
    if not pairs:
        return "There is no media session to control right now."

    want_status = {"pause": "playing", "stop": "playing", "play": "paused"}.get(action)
    pair = _match_session(pairs, target, want_status)
    if pair is None and target:
        names = ", ".join(f"{i['title'] or i['app']} ({i['app']})" for _, i in pairs)
        return f"I couldn't find media matching '{target}'. Currently: {names}."
    if pair is None:
        # Nothing in the desired state (e.g. "pause" but nothing playing).
        pair = pairs[0]
    session, info = pair

    try:
        if action in ("pause", "stop"):
            ok = await session.try_pause_async()
        elif action == "play":
            ok = await session.try_play_async()
        elif action == "next":
            ok = await session.try_skip_next_async()
        elif action in ("previous", "prev"):
            ok = await session.try_skip_previous_async()
        else:
            return f"Unknown media action '{action}'."
    except Exception as exc:
        return f"Media control failed: {exc}"

    label = info["title"] or info["app"]
    verb = {"pause": "Paused", "stop": "Paused", "play": "Resumed", "next": "Skipped", "previous": "Went back"}[
        "prev" if action == "prev" else action
    ]
    if not ok:
        return f"{info['app']} refused the {action} command."
    return f"{verb} {label} in {info['app']}."


def control_sync(action: str, target: str = "", timeout: float = 8.0) -> str | None:
    """Thread-safe wrapper. Returns None if WinRT is unavailable (caller falls
    back to global media keys)."""
    if platform.system() != "Windows":
        return None
    result: dict = {}

    def _runner() -> None:
        try:
            result["v"] = asyncio.run(_control_async(action, target))
        except Exception:
            pass

    worker = threading.Thread(target=_runner, daemon=True)
    worker.start()
    worker.join(timeout)
    return result.get("v")
