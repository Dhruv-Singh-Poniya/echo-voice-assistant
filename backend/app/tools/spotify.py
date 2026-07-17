"""Spotify playback via the official Web API.

Auth is OAuth 2.0 with PKCE — a "public client" flow, so only a Client ID is
needed (no secret to protect). One-time setup:

  1. https://developer.spotify.com/dashboard -> Create app
     Redirect URI:  http://127.0.0.1:8000/api/spotify/callback   (Web API)
  2. Put the app's Client ID in backend/.env as SPOTIFY_CLIENT_ID=...
  3. Open http://127.0.0.1:8000/api/spotify/login once and approve.

Tokens land in backend/spotify_tokens.json (git-ignored) and refresh
automatically. Starting playback on a device requires Spotify Premium —
that's Spotify's API rule, not ours.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse

import httpx

from ..config import BACKEND_DIR, settings

_TOKENS_FILE = BACKEND_DIR / "spotify_tokens.json"
_AUTH_URL = "https://accounts.spotify.com/authorize"
_TOKEN_URL = "https://accounts.spotify.com/api/token"
_API = "https://api.spotify.com/v1"
_SCOPES = "user-modify-playback-state user-read-playback-state"
_REDIRECT_URI = "http://127.0.0.1:8000/api/spotify/callback"
_LOCK = threading.Lock()

# PKCE state held between /login and /callback (single-user assistant).
_pending: dict[str, str] = {}


def enabled() -> bool:
    return bool(settings.spotify_client_id)


def is_connected() -> bool:
    return bool(_load_tokens().get("refresh_token"))


def _load_tokens() -> dict:
    try:
        return json.loads(_TOKENS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_tokens(tokens: dict) -> None:
    with _LOCK:
        _TOKENS_FILE.write_text(json.dumps(tokens), encoding="utf-8")


def begin_auth() -> str:
    """Build the Spotify authorize URL (PKCE challenge) for the login redirect."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    state = secrets.token_urlsafe(16)
    _pending["verifier"] = verifier
    _pending["state"] = state
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": _REDIRECT_URI,
        "scope": _SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    }
    return f"{_AUTH_URL}?{urllib.parse.urlencode(params)}"


def handle_callback(code: str, state: str, error: str = "") -> str:
    """Exchange the authorization code for tokens. Returns a human message."""
    if error:
        return f"Spotify said no: {error}."
    if not code or state != _pending.get("state"):
        return "That login attempt looks stale — start again at /api/spotify/login."
    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": settings.spotify_client_id,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _REDIRECT_URI,
                "code_verifier": _pending.get("verifier", ""),
            },
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        return f"Could not reach Spotify to finish login: {exc}"
    if "access_token" not in data:
        return f"Spotify login failed: {data.get('error_description') or data}"
    data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    _save_tokens(data)
    return "Spotify connected! Echo can now play songs for you."


def _access_token() -> str | None:
    tokens = _load_tokens()
    if not tokens.get("refresh_token"):
        return None
    if time.time() < tokens.get("expires_at", 0) - 60:
        return tokens.get("access_token")
    try:
        resp = httpx.post(
            _TOKEN_URL,
            data={
                "client_id": settings.spotify_client_id,
                "grant_type": "refresh_token",
                "refresh_token": tokens["refresh_token"],
            },
            timeout=15,
        )
        data = resp.json()
    except Exception:
        return tokens.get("access_token")  # stale but worth one try
    if "access_token" not in data:
        return None
    data.setdefault("refresh_token", tokens["refresh_token"])
    data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
    _save_tokens(data)
    return data["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _devices(token: str) -> list[dict]:
    try:
        resp = httpx.get(f"{_API}/me/player/devices", headers=_headers(token), timeout=10)
        return resp.json().get("devices", []) if resp.status_code == 200 else []
    except Exception:
        return []


def _ensure_device(token: str) -> str | None:
    """Find a Spotify device; if none, launch the desktop app and wait for it."""
    devices = _devices(token)
    if not devices:
        try:
            os.startfile("spotify:")  # noqa: S606 - opens/focuses the desktop app
        except Exception:
            return None
        for _ in range(8):
            time.sleep(1)
            devices = _devices(token)
            if devices:
                break
    if not devices:
        return None
    active = next((d for d in devices if d.get("is_active")), None)
    chosen = active or devices[0]
    return chosen.get("id")


def _open_spotify_search(query: str) -> str:
    """Zero-setup fallback: open the Spotify app straight at the search
    results for this query (spotify: URI scheme). One click and it plays —
    no Web API key or account setup needed."""
    import os
    import urllib.parse

    try:
        os.startfile(f"spotify:search:{urllib.parse.quote(query)}")  # noqa: S606
    except OSError:
        return (
            f"Spotify doesn't seem to be installed, so I can't open it. "
            f"Want me to play {query} on YouTube instead?"
        )
    return (
        f"I opened Spotify with search results for {query} — tap the first "
        "one to play it."
    )


def play_spotify(args: dict) -> str:
    """Tool handler: search Spotify and start the top matching track."""
    query = (args.get("query") or "").strip()
    if not query:
        return "What should I play on Spotify?"
    if not enabled():
        # No API key configured — regular-use fallback: open the app at the
        # results instead of lecturing the user about developer setup.
        return _open_spotify_search(query)
    if not is_connected():
        # Key present but the one-time approval was never done — still be useful.
        return _open_spotify_search(query) + (
            " (For full voice auto-play, approve once at "
            "http://127.0.0.1:8000/api/spotify/login.)"
        )
    token = _access_token()
    if not token:
        return "My Spotify login expired and refresh failed — visit /api/spotify/login again."

    try:
        resp = httpx.get(
            f"{_API}/search",
            params={"q": query, "type": "track", "limit": 3},
            headers=_headers(token),
            timeout=15,
        )
        items = resp.json().get("tracks", {}).get("items", [])
    except Exception as exc:
        return f"Spotify search failed: {exc}"
    if not items:
        return f"Spotify has no track matching '{query}'."
    track = items[0]
    uri = track["uri"]
    name = track.get("name", query)
    artists = ", ".join(a.get("name", "") for a in track.get("artists", [])[:2])

    device_id = _ensure_device(token)
    if not device_id:
        return "I couldn't find a Spotify device — open the Spotify app once and try again."

    try:
        resp = httpx.put(
            f"{_API}/me/player/play",
            params={"device_id": device_id},
            json={"uris": [uri]},
            headers=_headers(token),
            timeout=15,
        )
    except Exception as exc:
        return f"Spotify playback failed: {exc}"
    if resp.status_code in (200, 202, 204):
        return f"Playing {name} by {artists} on Spotify."
    if resp.status_code == 403:
        return "Spotify refused playback — starting songs remotely needs Spotify Premium."
    if resp.status_code == 404:
        return "Spotify lost the device — open the Spotify app and try again."
    return f"Spotify playback failed with status {resp.status_code}."
