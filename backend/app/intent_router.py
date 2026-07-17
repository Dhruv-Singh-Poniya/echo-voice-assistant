"""Fast, deterministic routing for common automation commands.

The LLM is still useful for fuzzy questions, but simple desktop actions should
not depend on model guesswork. This router catches high-frequency commands and
turns them into explicit tool calls before the provider is asked.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class RoutedIntent:
    calls: list[dict] = field(default_factory=list)
    reply: str | None = None
    handled: bool = False
    pending: dict | None = None


_MESSAGE_VERBS = ("message", "text", "dm", "send")
_PLATFORMS = {
    "discord": "send_discord_message",
    "whatsapp": "send_whatsapp",
    "whats app": "send_whatsapp",
}
_APP_ALIASES = {
    "vs code": "vscode",
    "visual studio code": "vscode",
    "file manager": "file explorer",
}


def route(text: str) -> RoutedIntent | None:
    raw = _clean(text)
    if not raw:
        return None

    lowered = raw.lower()

    routed = _route_multi(raw, lowered)
    if routed:
        return routed

    routed = _route_message(raw, lowered)
    if routed:
        return routed

    routed = _route_volume(lowered)
    if routed:
        return routed

    routed = _route_media_control(lowered)
    if routed:
        return routed

    routed = _route_youtube(raw, lowered)
    if routed:
        return routed

    routed = _route_close_window(raw, lowered)
    if routed:
        return routed

    routed = _route_open(raw, lowered)
    if routed:
        return routed

    return None


def _clean(text: str) -> str:
    text = " ".join((text or "").strip().split())
    text = re.sub(
        r"^(hey\s+)?(echo|jarvis|assistant|please|can you|could you|would you)\s+",
        "",
        text,
        flags=re.I,
    )
    return text.strip(" .?!")


def _call(name: str, arguments: dict) -> dict:
    return {"id": f"fast_{name}", "name": name, "arguments": arguments}


def _route_message(raw: str, lowered: str) -> RoutedIntent | None:
    if not any(verb in lowered.split() for verb in _MESSAGE_VERBS):
        return None

    platform = _extract_platform(lowered)
    if not platform:
        contact, message = _extract_message_parts_without_platform(raw)
        if contact and message:
            return RoutedIntent(
                reply=f"Which app should I use to message {contact}: WhatsApp or Discord?",
                handled=True,
                pending={"type": "message_platform", "contact": contact, "message": message},
            )
        return RoutedIntent(
            reply="Which app should I use for that message: WhatsApp or Discord?",
            handled=True,
        )

    contact, message = _extract_message_parts(raw, lowered, platform)
    if not contact:
        return RoutedIntent(reply=f"Who should I message on {platform.title()}?", handled=True)
    if not message:
        return RoutedIntent(reply=f"What should I say to {contact} on {platform.title()}?", handled=True)

    calls: list[dict] = []
    if re.search(rf"\b(open|launch|start)\s+{re.escape(platform)}\b", lowered):
        calls.append(_call("open_application", {"name": platform}))
    calls.append(_call(_PLATFORMS[platform], {"contact": contact, "message": message}))
    return RoutedIntent(calls=calls, handled=True)


def _route_multi(raw: str, lowered: str) -> RoutedIntent | None:
    parts = re.split(r"\s+(?:and then|then|and)\s+", raw, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None

    first = route(parts[0])
    second = route(parts[1])
    if not first or not second:
        return None

    calls = [*first.calls, *second.calls]
    if first.pending and first.pending.get("type") == "music_query" and second.pending:
        calls.insert(0, _call("play_youtube", {"query": "music"}))
    reply = second.reply or first.reply
    pending = second.pending or first.pending
    if calls or reply:
        return RoutedIntent(calls=calls, reply=reply, pending=pending, handled=True)
    return None


def _extract_platform(lowered: str) -> str | None:
    for name in _PLATFORMS:
        if re.search(rf"\b{re.escape(name)}\b", lowered):
            return "whatsapp" if name == "whats app" else name
    # "open discord and message Devashish hi" implies the messaging target.
    match = re.search(r"\b(?:open|launch|start)\s+(discord|whatsapp|whats app)\b", lowered)
    if match:
        value = match.group(1)
        return "whatsapp" if value == "whats app" else value
    return None


def _extract_message_parts(raw: str, lowered: str, platform: str) -> tuple[str, str]:
    platform_re = r"(?:on|via|in)\s+(?:discord|whatsapp|whats\s+app)"
    say_re = r"(?:saying|say|that says|with message|with the message|:)"
    patterns = [
        rf"(?:message|text|dm)\s+(?P<contact>.+?)\s+{platform_re}\s+{say_re}\s+(?P<message>.+)$",
        rf"(?:message|text|dm)\s+(?P<contact>.+?)\s+{say_re}\s+(?P<message>.+?)\s+{platform_re}$",
        rf"send\s+(?P<message>.+?)\s+to\s+(?P<contact>.+?)\s+{platform_re}$",
        rf"send\s+(?:a\s+)?(?:discord|whatsapp|whats\s+app)?\s*message\s+to\s+(?P<contact>.+?)\s+{say_re}\s+(?P<message>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            return _tidy_contact(match.group("contact"), platform), _tidy_message(match.group("message"))

    # Remove leading app launch and platform words, then handle compact forms:
    # "open discord and message Devashish hi" -> Devashish / hi.
    compact = re.sub(r"^(?:open|launch|start)\s+(?:discord|whatsapp|whats\s+app)\s+(?:and\s+)?", "", raw, flags=re.I)
    compact = re.sub(rf"\b{platform_re}\b", "", compact, flags=re.I)
    compact = re.sub(r"^(?:message|text|dm|send)\s+", "", compact, flags=re.I).strip()
    compact = re.sub(r"^(?:a\s+)?(?:discord|whatsapp|whats\s+app)\s+message\s+(?:to\s+)?", "", compact, flags=re.I).strip()

    quote = re.search(r'(?P<contact>.+?)\s+["“](?P<message>.+?)["”]\s*$', compact)
    if quote:
        return _tidy_contact(quote.group("contact"), platform), _tidy_message(quote.group("message"))

    say_match = re.search(rf"(?P<contact>.+?)\s+{say_re}\s+(?P<message>.+)$", compact, flags=re.I)
    if say_match:
        return _tidy_contact(say_match.group("contact"), platform), _tidy_message(say_match.group("message"))

    words = compact.split()
    if len(words) >= 2:
        return _tidy_contact(" ".join(words[:-1]), platform), _tidy_message(words[-1])
    return _tidy_contact(compact, platform), ""


def _extract_message_parts_without_platform(raw: str) -> tuple[str, str]:
    say_re = r"(?:saying|say|that says|with message|with the message|:)"
    patterns = [
        rf"^send\s+(?:a\s+)?message\s+to\s+(?P<contact>.+?)\s+{say_re}\s+(?P<message>.+)$",
        rf"^send\s+(?P<message>.+?)\s+to\s+(?P<contact>.+?)$",
        rf"^(?:message|text|dm)\s+(?P<contact>.+?)\s+{say_re}\s+(?P<message>.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.I)
        if match:
            return _tidy_contact(match.group("contact"), ""), _tidy_message(match.group("message"))

    compact = re.sub(r"^(?:message|text|dm|send)\s+", "", raw, flags=re.I).strip()
    compact = re.sub(r"^(?:a\s+)?message\s+(?:to\s+)?", "", compact, flags=re.I).strip()
    say_match = re.search(rf"(?P<contact>.+?)\s+{say_re}\s+(?P<message>.+)$", compact, flags=re.I)
    if say_match:
        return _tidy_contact(say_match.group("contact"), ""), _tidy_message(say_match.group("message"))
    words = compact.split()
    if len(words) >= 2:
        return _tidy_contact(" ".join(words[:-1]), ""), _tidy_message(words[-1])
    return "", ""


def _tidy_contact(value: str, platform: str) -> str:
    if platform:
        value = re.sub(rf"\b(?:on|via|in)\s+{re.escape(platform)}\b", "", value, flags=re.I)
    value = re.sub(r"^to\s+", "", value, flags=re.I)
    return value.strip(" ,.-")


def _tidy_message(value: str) -> str:
    return value.strip(" ,.-\"“”")


def _route_volume(lowered: str) -> RoutedIntent | None:
    match = re.search(r"\b(?:set|make|change)\s+(?:the\s+)?volume\s+(?:to\s+)?(?P<level>\d{1,3})\s*%?", lowered)
    if match:
        return RoutedIntent(
            calls=[_call("set_volume", {"level": int(match.group("level"))})],
            handled=True,
        )
    if re.search(r"\b(volume|sound)\s+(up|increase|louder)\b|\bturn it up\b", lowered):
        return RoutedIntent(calls=[_call("media_control", {"action": "volume_up"})], handled=True)
    if re.search(r"\b(volume|sound)\s+(down|decrease|quieter|lower)\b|\bturn it down\b", lowered):
        return RoutedIntent(calls=[_call("media_control", {"action": "volume_down"})], handled=True)
    if re.search(r"\bunmute\b", lowered):
        return RoutedIntent(calls=[_call("media_control", {"action": "unmute"})], handled=True)
    if re.search(r"\b(mute|silence)\b", lowered):
        return RoutedIntent(calls=[_call("media_control", {"action": "mute"})], handled=True)
    return None


_MEDIA_TARGETS = ("spotify", "brave", "chrome", "edge", "firefox", "vlc", "youtube")


def _media_target(lowered: str) -> str:
    """'pause the spotify music' -> 'spotify'; 'stop the video' -> '' (auto-pick)."""
    for name in _MEDIA_TARGETS:
        if name in lowered:
            return name
    return ""


def _route_media_control(lowered: str) -> RoutedIntent | None:
    if re.search(r"\b(stop|pause)\b.*\b(music|song|video|youtube|playback|audio)\b|\b(stop|pause)\s+(this|it)\b", lowered):
        action = "pause" if "pause" in lowered else "stop"
        args = {"action": action}
        target = _media_target(lowered)
        if target:
            args["target"] = target
        return RoutedIntent(calls=[_call("media_control", args)], handled=True)
    if re.search(r"\b(resume|continue|play)\s+(music|song|video|youtube|playback|audio|it)\b", lowered) and not re.search(
        r"\b(?:on|in|via|from)\s+(?:spotify|youtube)\b", lowered
    ):
        # "play music" = resume; "play music ON spotify" = a play request, let
        # the music router pick the service instead.
        return RoutedIntent(calls=[_call("media_control", {"action": "play"})], handled=True)
    if re.search(r"\b(next|skip)\b", lowered):
        return RoutedIntent(calls=[_call("media_control", {"action": "next"})], handled=True)
    if re.search(r"\b(previous|prev|back)\s+(song|track|video)?\b", lowered):
        return RoutedIntent(calls=[_call("media_control", {"action": "previous"})], handled=True)
    return None


def play_call(query: str) -> dict:
    """Pick the right player for a music query.

    Explicit service wins; otherwise prefer Spotify when it's connected
    (real music app) and fall back to YouTube.
    """
    lowered = query.lower()
    wants_spotify = "spotify" in lowered
    wants_youtube = "youtube" in lowered or "video" in lowered
    cleaned = re.sub(r"\b(?:on|in|via|from)\s+(?:spotify|youtube)\b|\b(?:spotify|youtube)\b", "", query, flags=re.I)
    cleaned = " ".join(cleaned.split()).strip(" ,.-") or query

    if wants_spotify:
        return _call("play_spotify", {"query": cleaned})
    if wants_youtube:
        return _call("play_youtube", {"query": cleaned})

    from .tools import spotify

    if spotify.enabled() and spotify.is_connected():
        return _call("play_spotify", {"query": cleaned})
    return _call("play_youtube", {"query": cleaned})


def _route_youtube(raw: str, lowered: str) -> RoutedIntent | None:
    match = re.search(r"^(?:play|put on|start playing)\s+(?P<query>.+)$", raw, flags=re.I)
    if not match:
        return None
    query = _clean_media_query(match.group("query"))
    if not query:
        return RoutedIntent(reply="What should I play?", handled=True)
    if query.lower() in {"a music", "music", "some music", "a song", "song", "something",
                         "music on spotify", "spotify", "the music on spotify", "something on spotify"}:
        return RoutedIntent(
            reply="What kind of music would you like to hear?",
            pending={"type": "music_query"},
            handled=True,
        )
    return RoutedIntent(calls=[play_call(query)], handled=True)


def _clean_media_query(query: str) -> str:
    query = re.sub(r"\b(?:rather than|instead of)\s+this\b.*$", "", query, flags=re.I)
    query = re.sub(r"\b(?:for me|please)\b", "", query, flags=re.I)
    return " ".join(query.strip(" .?!").split())


def _route_close_window(raw: str, lowered: str) -> RoutedIntent | None:
    match = re.search(r"^(?:close|quit|exit)\s+(?:the\s+)?(?P<name>.+?)(?:\s+window|\s+tab)?$", raw, flags=re.I)
    if not match:
        return None
    name = match.group("name").strip()
    if name.lower() in {"app", "application", "window", "tab"}:
        return RoutedIntent(reply="Which window should I close?", handled=True)
    return RoutedIntent(calls=[_call("close_window", {"name": name})], handled=True)


def _route_open(raw: str, lowered: str) -> RoutedIntent | None:
    match = re.search(r"^(?:open|launch|start)\s+(?P<target>.+)$", raw, flags=re.I)
    if not match:
        return None
    target = match.group("target").strip()
    target_lower = target.lower()
    target_lower = _APP_ALIASES.get(target_lower, target_lower)

    if re.search(r"\b(website|site|url)\b", target_lower) or "." in target_lower:
        url = re.sub(r"\b(?:website|site|url)\b", "", target, flags=re.I).strip()
        return RoutedIntent(calls=[_call("open_url", {"url": url})], handled=True)

    return RoutedIntent(calls=[_call("open_application", {"name": target_lower})], handled=True)
