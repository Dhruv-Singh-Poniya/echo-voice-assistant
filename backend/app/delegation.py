"""Sub-agents: hand a complex task to a stronger brain.

The main voice loop runs on a fast, cheap model so replies feel instant.
When a request needs real multi-step reasoning (install and configure X,
research then act, several dependent steps), the fast model calls the
``delegate_task`` tool, which spins up a ONE-SHOT agent whose brain is a
stronger model (Claude Sonnet via the gateway) with the same toolbox, and
returns its final result to the conversation.

Two deliberate limits keep it safe and simple:
- Sub-agents never get confirmation-gated tools (messaging, installs, shell).
  If the plan needs one, the sub-agent says so and the MAIN loop runs it
  through the normal user-confirmation flow.
- No recursion: a sub-agent cannot delegate again.
"""
from __future__ import annotations

from .config import settings

_MAX_TURNS = 12

# Tools a sub-agent must NOT hold: anything the user confirms per-use, plus
# delegation itself.
_EXCLUDED = {
    "send_whatsapp",
    "send_discord_message",
    "run_command",
    "close_window",
    "install_software",
    "delegate_task",
}

_SYSTEM = (
    "You are a capable background agent working for {name}, a voice assistant. "
    "You were handed one task. Complete it fully using your tools: search the "
    "web when you need facts or methods, check installed apps, and act. "
    "Never give up after one failed attempt — find another way. "
    "You CANNOT ask the user questions and CANNOT run confirmation-gated "
    "actions (installing software, sending messages, shell commands, closing "
    "windows). If the task needs one of those, finish everything else and end "
    "with a line starting 'NEEDS CONFIRMATION:' describing exactly what to run. "
    "When done, reply with a SHORT plain-text result (it will be read aloud): "
    "what you did and what the user should know. No markdown."
)


def _sub_provider():
    from .llm.gateway_provider import GatewayProvider

    return GatewayProvider(model=settings.gateway_agent_model, max_tokens=1000)


def delegate_task(args: dict) -> str:
    """Tool handler: run a one-shot Sonnet-brained agent over the task."""
    task = (args.get("task") or "").strip()
    if not task:
        return "Delegation needs a task description."
    if settings.llm_provider != "gateway":
        return "Delegation needs the gateway brain (LLM_PROVIDER=gateway)."

    from .tools.registry import TOOL_SCHEMAS, dispatch

    tools = [t for t in TOOL_SCHEMAS if t["name"] not in _EXCLUDED]
    provider = _sub_provider()
    system = _SYSTEM.format(name=settings.assistant_name)
    context = (args.get("context") or "").strip()
    opening = task if not context else f"{task}\n\nContext from the conversation: {context}"
    messages: list[dict] = [{"role": "user", "content": opening}]
    actions: list[str] = []

    for _ in range(_MAX_TURNS):
        try:
            turn = provider.chat(system, messages, tools)
        except Exception as exc:
            return f"The sub-agent failed: {exc}"

        messages.append(
            {
                "role": "assistant",
                "content": turn.text,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in turn.tool_calls
                ],
            }
        )
        if not turn.tool_calls:
            summary = turn.text or "The sub-agent finished without a summary."
            if actions:
                return f"{summary} (sub-agent used: {', '.join(dict.fromkeys(actions))})"
            return summary

        for tc in turn.tool_calls:
            actions.append(tc.name)
            result = dispatch(tc.name, tc.arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                }
            )

    return "The sub-agent ran out of steps before finishing. Partial actions: " + ", ".join(
        dict.fromkeys(actions)
    )
