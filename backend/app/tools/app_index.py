"""Dynamic index of every installed application — no hardcoded app lists.

HOW IT WORKS (the interesting part):
Windows keeps a virtual "AppsFolder" — the same list the Start Menu shows.
``Get-StartApps`` enumerates it, covering BOTH classic desktop apps (.exe/.lnk)
and Store/UWP apps. Every entry has an AppID, and every AppID — regardless of
app type — launches the same way: ``shell:AppsFolder\\<AppID>``. So instead of
maintaining a dictionary of known apps, we scan once, cache to disk, and fuzzy
match whatever the user says against the real installed set.

The index refreshes in a background thread (startup + when stale), so lookups
are always instant reads from memory/disk.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import threading
import time

from ..config import BACKEND_DIR

_INDEX_FILE = BACKEND_DIR / "app_index.json"
_MAX_AGE_SECONDS = 6 * 60 * 60  # rescan if the cache is older than 6 hours
_LOCK = threading.Lock()
_APPS: list[dict] | None = None  # [{"name": ..., "appid": ...}]
_REFRESHING = False

_PS_LIST_APPS = (
    "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
)


def _normalize(text: str) -> str:
    """Lowercase and strip everything but letters/digits/spaces, collapse spaces."""
    text = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " ".join(text.split())


def _scan() -> list[dict]:
    """Ask Windows for the full installed-app list (takes ~1-2s, so we cache)."""
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_LIST_APPS],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    raw = json.loads(completed.stdout or "[]")
    if isinstance(raw, dict):  # ConvertTo-Json unwraps single-item lists
        raw = [raw]
    apps = []
    for item in raw:
        name, appid = item.get("Name"), item.get("AppID")
        if name and appid:
            apps.append({"name": name, "appid": appid, "key": _normalize(name)})
    return apps


def _load_cache() -> list[dict] | None:
    try:
        data = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        if time.time() - data.get("built_at", 0) < _MAX_AGE_SECONDS:
            return data.get("apps") or None
        return data.get("apps") or None  # stale cache still usable; refresh happens async
    except Exception:
        return None


def _save_cache(apps: list[dict]) -> None:
    try:
        _INDEX_FILE.write_text(
            json.dumps({"built_at": time.time(), "apps": apps}), encoding="utf-8"
        )
    except Exception:
        pass


def _cache_is_stale() -> bool:
    try:
        data = json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
        return time.time() - data.get("built_at", 0) >= _MAX_AGE_SECONDS
    except Exception:
        return True


def refresh(block: bool = False) -> None:
    """Rebuild the index. Non-blocking by default (background thread)."""
    global _REFRESHING

    def _do() -> None:
        global _APPS, _REFRESHING
        try:
            apps = _scan()
            if apps:
                with _LOCK:
                    _APPS = apps
                _save_cache(apps)
        except Exception:
            pass
        finally:
            _REFRESHING = False

    with _LOCK:
        if _REFRESHING:
            return
        _REFRESHING = True
    if block:
        _do()
    else:
        threading.Thread(target=_do, daemon=True).start()


def get_apps() -> list[dict]:
    """Return the app list, loading cache / triggering scans as needed."""
    global _APPS
    with _LOCK:
        apps = _APPS
    if apps is None:
        cached = _load_cache()
        if cached:
            with _LOCK:
                _APPS = cached
            if _cache_is_stale():
                refresh()
            return cached
        # No cache at all: first ever run — must scan synchronously once.
        refresh(block=True)
        with _LOCK:
            return _APPS or []
    return apps


def _initials(tokens: list[str]) -> set[str]:
    """All acronyms of consecutive words: 'visual studio code' -> vs, sc, vsc."""
    out = set()
    n = len(tokens)
    for i in range(n):
        for j in range(i + 2, n + 1):
            out.add("".join(t[0] for t in tokens[i:j]))
    return out


def _acronym_variants(tokens: list[str]) -> set[str]:
    """Space-less name variants with word spans collapsed to their initials.

    'visual studio code' -> {'vscode', 'visualsc', 'vsc', ...} so the single
    token 'vscode' still finds Visual Studio Code.
    """
    out = set()
    n = len(tokens)
    for i in range(n):
        for j in range(i + 2, n + 1):
            acronym = "".join(t[0] for t in tokens[i:j])
            out.add("".join(tokens[:i]) + acronym + "".join(tokens[j:]))
    return out


def _tokens_cover(q_tokens: set[str], key_tokens: list[str]) -> bool:
    """Every query token matches a name word, a word prefix, or an acronym.

    This is what lets 'vs code' find 'Visual Studio Code': 'vs' matches the
    initials of 'Visual Studio', and 'code' matches the word 'code'.
    """
    key_set = set(key_tokens)
    acronyms = _initials(key_tokens)
    for qt in q_tokens:
        if qt in key_set or qt in acronyms:
            continue
        if len(qt) >= 3 and any(kt.startswith(qt) for kt in key_set):
            continue
        return False
    return True


def find(query: str, limit: int = 5) -> list[tuple[float, dict]]:
    """Score every installed app against the query; return the best matches.

    Scoring tiers (highest wins):
      1.0  exact name match          ("calculator" == "Calculator")
      0.9  name starts with query    ("word" -> "Word")
      0.8  all query words match words/prefixes/acronyms of the name
           ("vs code" -> "Visual Studio Code")
      0.7  plain substring           ("photosho" -> "Photoshop")
      <=0.6 fuzzy similarity          (typos, partial words)
    """
    q = _normalize(query)
    if not q:
        return []
    q_ns = q.replace(" ", "")  # space-less form: 'whats app' -> 'whatsapp'
    scored: list[tuple[float, dict]] = []
    q_tokens = set(q.split())
    for app in get_apps():
        key = app["key"]
        key_tokens = key.split()
        key_ns = key.replace(" ", "")
        if key == q or key_ns == q_ns:
            score = 1.0
        elif key.startswith(q) or key_ns.startswith(q_ns):
            score = 0.9
        elif q_tokens and _tokens_cover(q_tokens, key_tokens):
            score = 0.8
        elif q_ns in _acronym_variants(key_tokens):
            score = 0.8
        elif q in key or q_ns in key_ns:
            score = 0.7
        else:
            ratio = difflib.SequenceMatcher(None, q, key).ratio()
            score = ratio * 0.6
        if score >= 0.45:
            scored.append((score, app))
    scored.sort(key=lambda pair: (-pair[0], len(pair[1]["key"])))
    return scored[:limit]


def launch(app: dict) -> None:
    """Launch any indexed app — desktop or Store — via the shell AppsFolder."""
    os.startfile(f"shell:AppsFolder\\{app['appid']}")  # noqa: S606 - Windows only


def open_by_name(name: str) -> str:
    """Find the best-matching installed app and launch it. Honest about misses."""
    matches = find(name)
    if not matches:
        refresh()  # maybe it was installed since the last scan
        return (
            f"I couldn't find any installed app matching '{name}'. "
            "It may not be installed — I can search the web for it or install it if you want."
        )

    best_score, best = matches[0]
    if best_score >= 0.7:
        try:
            launch(best)
        except Exception as exc:
            return f"I found {best['name']} but couldn't launch it: {exc}"
        return f"Opening {best['name']}."

    # Low confidence: don't guess-launch the wrong thing; offer the candidates.
    options = ", ".join(app["name"] for _, app in matches[:3])
    return (
        f"I'm not sure which app you mean by '{name}'. "
        f"Closest installed matches: {options}. Which one?"
    )


def list_installed_apps(args: dict) -> str:
    """Tool-handler wrapper for the registry."""
    return list_installed((args.get("query") or "").strip())


def list_installed(query: str = "") -> str:
    """List installed apps, optionally filtered — lets the LLM see what exists."""
    if query:
        matches = find(query, limit=15)
        names = [app["name"] for _, app in matches]
        if not names:
            # The filter is probably a category ('browser'), not an app name.
            # Return everything and let the model pick what fits the category.
            all_names = sorted(app["name"] for app in get_apps())
            return (
                f"No app is named '{query}'. Full installed list so you can pick: "
                + ", ".join(all_names)
            )
    else:
        names = sorted(app["name"] for app in get_apps())
    if not names:
        return "No installed apps matched."
    shown = names[:60]
    suffix = f" (+{len(names) - 60} more)" if len(names) > 60 else ""
    return f"{len(names)} installed apps: " + ", ".join(shown) + suffix
