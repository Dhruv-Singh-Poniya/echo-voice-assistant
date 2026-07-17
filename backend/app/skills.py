"""Procedural memory: the assistant learns HOW to do things, not just facts.

Two layers, both persisted to disk:

1. SKILLS (``backend/skills/*.json``) — recipes the LLM writes for itself via
   the ``save_skill`` tool after it figures something out (e.g. via web search
   or trial and error). Relevant skills are retrieved by trigger-phrase match
   and injected into the system prompt, so next time the answer is instant.
   This is the Voyager pattern: an agent that grows its own skill library.

2. LEARNED ROUTES (``backend/learned_routes.json``) — a phrase -> tool-call
   cache. When the LLM resolves a spoken command into ONE safe tool call and
   it succeeds, we remember the mapping and skip the LLM entirely next time
   (instant + free). Safety rule: we only cache when every argument value
   appears verbatim in the phrase itself — that proves the command is
   self-contained and not dependent on conversation context.
"""
from __future__ import annotations

import difflib
import json
import re
import threading
import time

from .config import BACKEND_DIR

SKILLS_DIR = BACKEND_DIR / "skills"
_ROUTES_FILE = BACKEND_DIR / "learned_routes.json"
_LOCK = threading.Lock()

# Tools that are safe to replay from cache without re-thinking: idempotent-ish,
# never destructive, never needing confirmation.
_ROUTE_SAFE_TOOLS = {
    "open_application",
    "open_url",
    "play_youtube",
    "play_spotify",
    "media_control",
    "set_volume",
    "list_todos",
    "list_notes",
    "list_reminders",
}
_MAX_SKILLS_IN_PROMPT = 3


def _normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " ".join(text.split())


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "skill"


# --------------------------------------------------------------------------
# Layer 1: skills the model saves for itself
# --------------------------------------------------------------------------

def _load_skills() -> list[dict]:
    skills = []
    try:
        for path in sorted(SKILLS_DIR.glob("*.json")):
            try:
                skills.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    except Exception:
        pass
    return skills


def save_skill(args: dict) -> str:
    """Tool handler: persist a learned recipe."""
    name = (args.get("name") or "").strip()
    how = (args.get("how") or "").strip()
    if not name or not how:
        return "A skill needs both a name and the steps that worked."
    triggers = args.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    skill = {
        "name": name,
        "description": (args.get("description") or "").strip(),
        "triggers": [t.strip() for t in triggers if t and t.strip()],
        "how": how,
        "created": time.time(),
        "uses": 0,
    }
    SKILLS_DIR.mkdir(exist_ok=True)
    path = SKILLS_DIR / f"{_slug(name)}.json"
    updating = path.exists()
    with _LOCK:
        path.write_text(json.dumps(skill, indent=2), encoding="utf-8")
    verb = "Updated" if updating else "Saved"
    return f"{verb} skill '{name}'. I'll remember how to do this."


def list_skills(args: dict) -> str:
    """Tool handler: show what the assistant has taught itself."""
    skills = _load_skills()
    if not skills:
        return "I haven't saved any learned skills yet."
    lines = [
        f"{s['name']}: {s.get('description') or s['how'][:80]}" for s in skills
    ]
    return f"{len(skills)} learned skills — " + "; ".join(lines)


def relevant_skills(user_text: str) -> str:
    """Return a system-prompt block of skills matching this request, if any."""
    q = _normalize(user_text)
    if not q:
        return ""
    q_tokens = set(q.split())
    scored: list[tuple[float, dict]] = []
    for skill in _load_skills():
        best = 0.0
        candidates = [skill["name"], skill.get("description", ""), *skill.get("triggers", [])]
        for cand in candidates:
            c = _normalize(cand)
            if not c:
                continue
            c_tokens = set(c.split())
            overlap = len(q_tokens & c_tokens) / max(1, len(c_tokens))
            fuzzy = difflib.SequenceMatcher(None, q, c).ratio()
            best = max(best, overlap, fuzzy)
        if best >= 0.5:
            scored.append((best, skill))
    if not scored:
        return ""
    scored.sort(key=lambda pair: -pair[0])
    parts = []
    for _, skill in scored[:_MAX_SKILLS_IN_PROMPT]:
        parts.append(f"- {skill['name']}: {skill['how']}")
    return (
        "You previously learned how to handle requests like this. "
        "Follow these proven steps instead of re-figuring them out:\n" + "\n".join(parts)
    )


# --------------------------------------------------------------------------
# Layer 2: learned phrase -> tool-call routes (the fast path)
# --------------------------------------------------------------------------

def _load_routes() -> dict[str, dict]:
    try:
        data = json.loads(_ROUTES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_routes(routes: dict[str, dict]) -> None:
    try:
        _ROUTES_FILE.write_text(json.dumps(routes, indent=2), encoding="utf-8")
    except Exception:
        pass


def lookup_route(user_text: str) -> dict | None:
    """Return a previously learned tool call for this exact phrase, if safe."""
    key = _normalize(user_text)
    if not key:
        return None
    route = _load_routes().get(key)
    if route and route.get("name") in _ROUTE_SAFE_TOOLS:
        return route
    return None


def _args_are_self_contained(phrase_norm: str, arguments: dict) -> bool:
    """True if every string argument appears inside the phrase itself.

    This is the safety gate: it guarantees the tool call was derived purely
    from the words spoken, not from conversation context, so replaying it
    later can't be wrong in a new context.
    """
    for value in (arguments or {}).values():
        if isinstance(value, str):
            if _normalize(value) not in phrase_norm:
                return False
        elif isinstance(value, (int, float)):
            if str(int(value) if float(value).is_integer() else value) not in phrase_norm:
                return False
    return True


def learn_route(user_text: str, calls: list[dict], results: list[str]) -> None:
    """Cache a successful single-tool resolution for instant replay next time."""
    if len(calls) != 1:
        return
    call = calls[0]
    name = call.get("name")
    if name not in _ROUTE_SAFE_TOOLS:
        return
    result = (results[0] if results else "").lower()
    if result.startswith(("tool ", "could not", "i couldn't", "i'm not sure", "something went wrong")):
        return  # only learn from success
    key = _normalize(user_text)
    if not key or len(key) > 80:
        return
    arguments = call.get("arguments") or {}
    if not _args_are_self_contained(key, arguments):
        return
    with _LOCK:
        routes = _load_routes()
        routes[key] = {"name": name, "arguments": arguments, "learned_at": time.time()}
        _save_routes(routes)


def forget_route(user_text: str) -> None:
    """Drop a learned route (called when a replay fails — self-healing)."""
    key = _normalize(user_text)
    with _LOCK:
        routes = _load_routes()
        if key in routes:
            routes.pop(key)
            _save_routes(routes)
