"""RecallrAI long-term memory integration.

This module is deliberately optional. When RECALLRAI_ENABLED=false the rest of
the assistant behaves exactly as before; when enabled, each local conversation
session is mirrored to RecallrAI and low-latency context is fetched before the
LLM answers.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from .config import BACKEND_DIR, settings

_SESSION_MAP_FILE = BACKEND_DIR / "recallr_sessions.json"
_LOCK = threading.RLock()
_CLIENT: Any | None = None
_USER: Any | None = None
_USER_READY = False
_SESSION_CACHE: dict[str, Any] = {}
_LAST_ERROR: str | None = None


def _load_session_map() -> dict[str, str]:
    try:
        if _SESSION_MAP_FILE.exists():
            data = json.loads(_SESSION_MAP_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


_SESSION_MAP = _load_session_map()


def _save_session_map() -> None:
    try:
        _SESSION_MAP_FILE.write_text(json.dumps(_SESSION_MAP), encoding="utf-8")
    except Exception:
        pass


def enabled() -> bool:
    return settings.recallrai_enabled


def last_error() -> str | None:
    return _LAST_ERROR


def _set_error(exc: Exception | str | None) -> None:
    global _LAST_ERROR
    if exc is None:
        _LAST_ERROR = None
    elif isinstance(exc, Exception):
        _LAST_ERROR = str(exc)
    else:
        _LAST_ERROR = exc


def health() -> list[str]:
    if not enabled():
        return []
    try:
        _sdk()
    except Exception as exc:
        return [f"RecallrAI SDK is unavailable: {exc}. Run pip install -r backend/requirements.txt."]
    return []


def _sdk() -> dict[str, Any]:
    from recallrai import RecallrAI
    from recallrai.models import MessageRole, RecallStrategy

    try:
        from recallrai.exceptions import (
            InvalidSessionStateError,
            SessionNotFoundError,
            UserAlreadyExistsError,
            UserNotFoundError,
        )
    except Exception:
        InvalidSessionStateError = SessionNotFoundError = UserAlreadyExistsError = UserNotFoundError = Exception

    return {
        "RecallrAI": RecallrAI,
        "MessageRole": MessageRole,
        "RecallStrategy": RecallStrategy,
        "InvalidSessionStateError": InvalidSessionStateError,
        "SessionNotFoundError": SessionNotFoundError,
        "UserAlreadyExistsError": UserAlreadyExistsError,
        "UserNotFoundError": UserNotFoundError,
    }


def _configure_forward_proxy() -> None:
    """Best-effort proxy support for SDK transports that honor env proxies.

    Prefer RECALLRAI_BASE_URL when you operate an edge/forward proxy that exposes
    the same RecallrAI API. RECALLRAI_FORWARD_PROXY_URL is for classic HTTP(S)
    forward proxies.
    """
    proxy = settings.recallrai_forward_proxy_url
    if not proxy:
        return
    os.environ["HTTPS_PROXY"] = proxy
    os.environ["HTTP_PROXY"] = proxy
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")


def _client():
    global _CLIENT
    if _CLIENT is None:
        sdk = _sdk()
        _configure_forward_proxy()
        _CLIENT = sdk["RecallrAI"](
            api_key=settings.recallrai_api_key,
            project_id=settings.recallrai_project_id,
            base_url=settings.recallrai_base_url,
            timeout=settings.recallrai_timeout,
        )
    return _CLIENT


def _ensure_user():
    global _USER, _USER_READY
    sdk = _sdk()
    client = _client()

    if _USER_READY and _USER is not None:
        return _USER

    def create_user():
        try:
            return client.create_user(
                user_id=settings.recallrai_user_id,
                metadata={"source": "voice-assistant", "assistant": settings.assistant_name},
            )
        except sdk["UserAlreadyExistsError"]:
            return client.get_user(settings.recallrai_user_id)

    try:
        user = client.get_user(settings.recallrai_user_id)
    except sdk["UserNotFoundError"]:
        user = create_user()
    except Exception as exc:
        if "not found" not in str(exc).lower():
            raise
        user = create_user()

    _USER = user
    _USER_READY = True
    return user


def _new_session(app_session_id: str):
    user = _ensure_user()
    session = user.create_session(
        auto_process_after_seconds=settings.recallrai_auto_process_after_seconds,
        metadata={"source": "voice-assistant", "app_session_id": app_session_id},
    )
    _SESSION_MAP[app_session_id] = session.session_id
    _SESSION_CACHE[app_session_id] = session
    _save_session_map()
    return session


def _session_for(app_session_id: str):
    cached = _SESSION_CACHE.get(app_session_id)
    if cached is not None:
        return cached

    user = _ensure_user()
    recallr_session_id = _SESSION_MAP.get(app_session_id)
    if recallr_session_id:
        session = user.get_session(session_id=recallr_session_id)
        _SESSION_CACHE[app_session_id] = session
        return session
    return _new_session(app_session_id)


def _role(name: str):
    roles = _sdk()["MessageRole"]
    return roles.USER if name == "user" else roles.ASSISTANT


def _should_recreate_session(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "processed",
            "invalid session state",
            "cannot add",
            "not found",
            "sessionnotfound",
        )
    )


def _add_message(app_session_id: str, role: str, content: str) -> None:
    if not content.strip():
        return

    try:
        session = _session_for(app_session_id)
        session.add_message(role=_role(role), content=content)
    except Exception as exc:
        if not _should_recreate_session(exc):
            raise
        session = _new_session(app_session_id)
        session.add_message(role=_role(role), content=content)


def _recall_strategy():
    strategies = _sdk()["RecallStrategy"]
    requested = settings.recallrai_recall_strategy
    candidates = {
        "low_latency": ("LOW_LATENCY",),
        "balanced": ("BALANCED",),
        "agentic": ("AGENTIC", "DEEP"),
        "deep": ("DEEP", "AGENTIC"),
    }.get(requested, ("LOW_LATENCY",))
    for name in candidates:
        if hasattr(strategies, name):
            return getattr(strategies, name)
    return getattr(strategies, "LOW_LATENCY")


def _get_context(app_session_id: str) -> str:
    session = _session_for(app_session_id)
    kwargs = {
        "recall_strategy": _recall_strategy(),
        "include_system_prompt": settings.recallrai_include_system_prompt,
    }
    if settings.recallrai_last_n_messages > 0:
        kwargs["last_n_messages"] = max(1, min(settings.recallrai_last_n_messages, 100))

    try:
        context = session.get_context(**kwargs)
    except TypeError:
        kwargs.pop("include_system_prompt", None)
        context = session.get_context(**kwargs)

    return (getattr(context, "context", "") or "").strip()


def before_turn(app_session_id: str, user_text: str) -> str:
    """Record the user turn and return RecallrAI context for the LLM prompt."""
    if not enabled():
        return ""
    with _LOCK:
        try:
            _add_message(app_session_id, "user", user_text)
            context = _get_context(app_session_id)
            _set_error(None)
            return context
        except Exception as exc:
            _set_error(exc)
            return ""


def after_turn(app_session_id: str, assistant_text: str) -> None:
    if not enabled():
        return
    with _LOCK:
        try:
            _add_message(app_session_id, "assistant", assistant_text)
            _set_error(None)
        except Exception as exc:
            _set_error(exc)


def finalize_session(app_session_id: str) -> None:
    """Ask RecallrAI to process the mirrored session now, then forget the mapping."""
    if not enabled():
        return
    with _LOCK:
        recallr_session_id = _SESSION_MAP.pop(app_session_id, None)
        cached = _SESSION_CACHE.pop(app_session_id, None)
        _save_session_map()
        if not recallr_session_id:
            return
        try:
            session = cached
            if session is None:
                user = _ensure_user()
                session = user.get_session(session_id=recallr_session_id)
            session.process()
            _set_error(None)
        except Exception as exc:
            _set_error(exc)


def list_memories(args: dict) -> str:
    if not enabled():
        return "RecallrAI memory is disabled."

    limit = args.get("limit", 10)
    if not isinstance(limit, int):
        limit = 10
    limit = max(1, min(limit, 50))

    with _LOCK:
        try:
            user = _ensure_user()
            memories = user.list_memories(
                offset=0,
                limit=limit,
                include_previous_versions=False,
                include_connected_memories=False,
            )
            items = getattr(memories, "items", []) or []
            if not items:
                _set_error(None)
                return "No RecallrAI memories are available yet."
            lines = []
            for mem in items:
                content = getattr(mem, "content", "")
                categories = ", ".join(getattr(mem, "categories", []) or [])
                prefix = f"[{categories}] " if categories else ""
                lines.append(prefix + content)
            _set_error(None)
            return "RecallrAI memories:\n" + "\n".join(lines)
        except Exception as exc:
            _set_error(exc)
            return f"Could not list RecallrAI memories: {exc}"
