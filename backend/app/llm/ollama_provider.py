"""Local LLM brain via Ollama — free, offline, no API key.

Requires the Ollama app running locally with a tool-capable model pulled,
e.g.  `ollama pull llama3.2:3b`.  Docs: https://ollama.com
"""
from __future__ import annotations

import json

import ollama

from ..config import settings
from .base import AssistantTurn, LLMProvider, ToolCall


def _to_ollama_messages(system: str, messages: list[dict]) -> list[dict]:
    """Normalized history -> Ollama chat format (OpenAI-style)."""
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": str(m.get("content", ""))})
        elif role == "assistant":
            msg = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif role == "tool":
            out.append(
                {"role": "tool", "content": m.get("content", ""), "tool_name": m.get("name", "")}
            )
    return out


def _to_ollama_tools(tools: list[dict]) -> list[dict]:
    """Canonical tool schema -> Ollama/OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _get(obj, key):
    """Read a field whether obj is a dict or an object (ollama SDK returns both)."""
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        self._client = ollama.Client(host=settings.ollama_host)

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        resp = self._client.chat(
            model=settings.ollama_model,
            messages=_to_ollama_messages(system, messages),
            tools=_to_ollama_tools(tools),
        )
        msg = _get(resp, "message")
        text = (_get(msg, "content") or "").strip()

        tool_calls: list[ToolCall] = []
        for idx, tc in enumerate(_get(msg, "tool_calls") or []):
            fn = _get(tc, "function")
            name = _get(fn, "name")
            args = _get(fn, "arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(id=f"call_{idx}", name=name, arguments=args or {}))

        return AssistantTurn(text=text, tool_calls=tool_calls)

    def health(self) -> list[str]:
        try:
            listed = self._client.list()
        except Exception:
            return [
                f"Cannot reach Ollama at {settings.ollama_host}. "
                "Install it from https://ollama.com and make sure it's running."
            ]
        # Confirm the configured model has been pulled.
        names = [ _get(m, "model") or _get(m, "name") for m in (_get(listed, "models") or []) ]
        wanted = settings.ollama_model
        if not any(n and (n == wanted or n.startswith(wanted.split(":")[0])) for n in names):
            return [
                f"Ollama model {wanted!r} isn't downloaded yet. "
                f"Run:  ollama pull {wanted}"
            ]
        return []
