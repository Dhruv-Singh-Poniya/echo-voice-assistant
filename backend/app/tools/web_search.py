"""Web search via DuckDuckGo — no API key required.

Kept provider-agnostic: it's an ordinary client-side tool, so the local
Ollama brain and cloud Claude brain both search the web the same way.
"""
from __future__ import annotations


def web_search(args: dict) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return "No search query was provided."

    try:
        try:
            from ddgs import DDGS  # current package name
        except ImportError:  # pragma: no cover - older installs
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
    except Exception as exc:
        return f"Web search failed: {exc}"

    if not results:
        return f"No results found for {query!r}."

    lines = []
    for r in results:
        title = r.get("title", "").strip()
        body = r.get("body", "").strip()
        href = r.get("href", "").strip()
        lines.append(f"- {title}: {body} ({href})")
    return f"Top web results for {query!r}:\n" + "\n".join(lines)
