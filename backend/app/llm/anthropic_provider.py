"""Cloud LLM brain via Anthropic's Claude — highest quality, needs an API key."""
from __future__ import annotations

from anthropic import Anthropic

from ..config import settings
from .base import AssistantTurn, LLMProvider, ToolCall


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Normalized history -> Anthropic messages format.

    Consecutive tool results are merged into a single user turn, as the
    Messages API expects all tool_result blocks for a turn together.
    """
    out: list[dict] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m.get("content", "")})
        elif role == "assistant":
            content = []
            if m.get("content"):
                content.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls", []):
                content.append(
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]}
                )
            out.append({"role": "assistant", "content": content})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": m.get("content", ""),
            }
            prev = out[-1] if out else None
            if (
                prev
                and prev["role"] == "user"
                and isinstance(prev["content"], list)
                and prev["content"]
                and prev["content"][0].get("type") == "tool_result"
            ):
                prev["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return out


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        self._client = Anthropic(api_key=settings.anthropic_api_key)

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        response = self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            system=system,
            tools=tools,  # canonical schema already matches Anthropic's format
            messages=_to_anthropic_messages(messages),
        )

        text_parts, tool_calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return AssistantTurn(text=" ".join(p.strip() for p in text_parts if p).strip(), tool_calls=tool_calls)

    def health(self) -> list[str]:
        if not settings.anthropic_api_key:
            return ["ANTHROPIC_API_KEY is missing."]
        return []
