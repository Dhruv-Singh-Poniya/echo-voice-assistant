"""Provider-agnostic LLM interface.

The agent speaks one normalized message/tool-call format; each concrete
provider (Ollama, Anthropic) translates it to and from its own API shape.
This is what makes the "brain" swappable via a single .env setting.

Normalized conversation messages are plain dicts:
  {"role": "user",      "content": "<text>"}
  {"role": "assistant", "content": "<text>", "tool_calls": [ {id,name,arguments}, ... ]}
  {"role": "tool",      "tool_call_id": "<id>", "name": "<tool>", "content": "<result>"}
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class AssistantTurn:
    """One model response: some text and/or a set of tool calls to run."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider:
    """Interface every brain implements."""

    def chat(self, system: str, messages: list[dict], tools: list[dict]) -> AssistantTurn:
        raise NotImplementedError

    def health(self) -> list[str]:
        """Return a list of human-readable problems (empty = healthy)."""
        return []
