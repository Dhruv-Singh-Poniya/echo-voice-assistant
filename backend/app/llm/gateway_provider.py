"""Brain via an OpenAI-compatible AI gateway (e.g. Claude through Bedrock).

Uses the standard POST {base}/v1/chat/completions endpoint with function/tool
calling — the same shape OpenAI, LiteLLM, Portkey, OpenRouter, etc. expose.
"""
from __future__ import annotations

import json

import httpx

from ..config import settings
from .base import AssistantTurn, LLMProvider, ToolCall

_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Persistent client → reuse the keep-alive connection to the gateway across turns.
_client = httpx.Client(timeout=_TIMEOUT)


def _to_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": str(m.get("content", ""))})
        elif role == "assistant":
            msg = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                    }
                    for tc in m["tool_calls"]
                ]
            out.append(msg)
        elif role == "tool":
            out.append(
                {"role": "tool", "tool_call_id": m.get("tool_call_id", ""), "content": m.get("content", "")}
            )
    return out


def _to_tools(tools: list[dict]) -> list[dict]:
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


class GatewayProvider(LLMProvider):
    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        body = {
            "model": settings.gateway_chat_model,
            "messages": _to_messages(system, messages),
            "tools": _to_tools(tools),
            "tool_choice": "auto",
            "max_tokens": settings.reply_max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {settings.gateway_api_key}",
            "content-type": "application/json",
        }

        resp = _client.post(
            f"{settings.gateway_base_url}/v1/chat/completions", headers=headers, json=body
        )
        resp.raise_for_status()
        data = resp.json()

        msg = data["choices"][0]["message"]
        text = (msg.get("content") or "").strip()

        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or "{}"
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=fn.get("name", ""), arguments=args or {}))

        return AssistantTurn(text=text, tool_calls=tool_calls)

    def health(self) -> list[str]:
        if not settings.gateway_base_url:
            return ["GATEWAY_BASE_URL is not set."]
        if not settings.gateway_api_key:
            return ["GATEWAY_API_KEY is not set."]
        return []
