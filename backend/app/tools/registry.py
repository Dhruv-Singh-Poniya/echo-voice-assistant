"""The tool registry: JSON schemas Claude sees + the Python handlers that run.

`TOOL_SCHEMAS` is the list handed to the Anthropic API. `dispatch()` maps a
tool name back to the local function that executes it. Web search is handled
natively by Anthropic's server-side tool, so it is added separately in agent.py.
"""
from __future__ import annotations

from typing import Callable

from .. import recallr_memory as r
from .. import skills as sk
from . import app_index as ai
from . import productivity as p
from . import system_automation as s
from . import web_search as w

# name -> handler
_HANDLERS: dict[str, Callable[[dict], str]] = {
    "web_search": w.web_search,
    "add_todo": p.add_todo,
    "list_todos": p.list_todos,
    "complete_todo": p.complete_todo,
    "add_note": p.add_note,
    "list_notes": p.list_notes,
    "set_reminder": p.set_reminder,
    "list_reminders": p.list_reminders,
    "list_memories": r.list_memories,
    "calculate": p.calculate,
    "get_datetime": p.get_datetime,
    "open_application": s.open_application,
    "send_whatsapp": s.send_whatsapp,
    "send_discord_message": s.send_discord_message,
    "play_youtube": s.play_youtube,
    "media_control": s.media_control,
    "set_volume": s.set_volume,
    "close_window": s.close_window,
    "open_url": s.open_url,
    "get_system_info": s.get_system_info,
    "run_command": s.run_command,
    "list_installed_apps": ai.list_installed_apps,
    "save_skill": sk.save_skill,
    "list_skills": sk.list_skills,
}

# Schemas advertised to the model. Keep descriptions crisp — the model routes on them.
TOOL_SCHEMAS: list[dict] = [
    {
        "name": "web_search",
        "description": "Search the web for current, up-to-date information (news, weather, facts, prices, events).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_todo",
        "description": "Add a task to the user's to-do list.",
        "input_schema": {
            "type": "object",
            "properties": {"task": {"type": "string", "description": "The task to add."}},
            "required": ["task"],
        },
    },
    {
        "name": "list_todos",
        "description": "List the user's to-do items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "include_done": {
                    "type": "boolean",
                    "description": "Include completed items too. Defaults to false.",
                }
            },
        },
    },
    {
        "name": "complete_todo",
        "description": "Mark a to-do item as done, by its numeric id.",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "integer", "description": "The to-do id."}},
            "required": ["id"],
        },
    },
    {
        "name": "add_note",
        "description": "Save a free-form note for the user.",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "Note text."}},
            "required": ["content"],
        },
    },
    {
        "name": "list_notes",
        "description": "List the user's most recent saved notes.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder to fire after a delay. Any duration works — give in_seconds for short timers (e.g. 10 seconds) or in_minutes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to be reminded about."},
                "in_seconds": {"type": "number", "description": "Seconds from now (use for short timers)."},
                "in_minutes": {"type": "number", "description": "Minutes from now."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List all reminders and their status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_memories",
        "description": "List the user's long-term memories saved by RecallrAI.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum memories to return. Defaults to 10.",
                }
            },
        },
    },
    {
        "name": "calculate",
        "description": "Evaluate a basic arithmetic expression (+ - * / % **).",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "e.g. '12 * (3 + 4)'"}
            },
            "required": ["expression"],
        },
    },
    {
        "name": "get_datetime",
        "description": "Get the current local date and time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_application",
        "description": (
            "Open ANY application installed on this PC by name — desktop or Microsoft "
            "Store app. A live index of every installed app is searched with fuzzy "
            "matching, so just pass what the user said (e.g. 'spotify', 'obs', 'vs code'). "
            "If unsure what's installed, use list_installed_apps first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "App name to open."}},
            "required": ["name"],
        },
    },
    {
        "name": "list_installed_apps",
        "description": (
            "List applications actually installed on this PC, optionally filtered by a "
            "search term. Use it to check whether an app exists before opening it, or "
            "when the user asks what apps they have."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional filter, e.g. 'browser' or 'photo'."}
            },
        },
    },
    {
        "name": "save_skill",
        "description": (
            "Save a learned skill: after you figure out how to do something non-obvious "
            "(via web_search, run_command, or trial and error), record the working method "
            "here so you can do it instantly next time instead of re-deriving it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short skill name, e.g. 'restart wifi adapter'."},
                "description": {"type": "string", "description": "One line: what this skill accomplishes."},
                "triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Phrases the user might say that should invoke this skill.",
                },
                "how": {"type": "string", "description": "The exact steps/commands that worked."},
            },
            "required": ["name", "how"],
        },
    },
    {
        "name": "list_skills",
        "description": "List the skills the assistant has taught itself so far.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_whatsapp",
        "description": (
            "Send a WhatsApp message to a contact by name using WhatsApp Desktop. "
            "Use this when the user asks to message or text someone on WhatsApp. "
            "Provide the contact's name and the exact message text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {"type": "string", "description": "The contact's name as it appears in WhatsApp."},
                "message": {"type": "string", "description": "The exact message text to send."},
            },
            "required": ["contact", "message"],
        },
    },
    {
        "name": "send_discord_message",
        "description": (
            "Send a Discord direct message or channel message by searching Discord. "
            "Use this when the user asks to message, text, DM, or send something on Discord. "
            "Do not use WhatsApp for Discord requests."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Discord contact, DM, server, or channel name to search.",
                },
                "message": {"type": "string", "description": "The exact message text to send."},
            },
            "required": ["contact", "message"],
        },
    },
    {
        "name": "play_youtube",
        "description": (
            "Actually play a song, music, or video on YouTube. Use this whenever the "
            "user says to PLAY something (e.g. 'play Shape of You', 'play some lofi'). "
            "It finds the top result and starts playback — do not just open a website."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Song/video to play, e.g. 'Shape of You Ed Sheeran'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "media_control",
        "description": (
            "Control media that is currently playing (YouTube, Spotify, etc.): pause, "
            "stop, resume/play, skip to next or previous, change volume, or mute. Use "
            "this to STOP or PAUSE music — do NOT call play_youtube again for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play", "pause", "stop", "next", "previous", "volume_up", "volume_down", "mute"],
                    "description": "What to do to the currently playing media.",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "set_volume",
        "description": (
            "Set the system volume to an EXACT level (0-100), e.g. 'set volume to 8%'. "
            "Or pass a relative change like +10 or -20. Use this for any specific volume "
            "request; use media_control(volume_up/volume_down) only for vague 'louder/quieter'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "number", "description": "Absolute volume 0-100."},
                "change": {"type": "number", "description": "Relative change, e.g. 10 or -15."},
            },
        },
    },
    {
        "name": "close_window",
        "description": (
            "Close an open window or browser tab by matching its title (e.g. 'YouTube', "
            "'Notepad', 'Spotify'). Use when the user asks to close/quit a window or tab. "
            "Note: it closes the whole matching window and never closes the assistant itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Text from the window/tab title to match."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "open_url",
        "description": "Open a website in the user's default browser.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "The URL to open."}},
            "required": ["url"],
        },
    },
    {
        "name": "get_system_info",
        "description": "Report basic information about the computer (OS, CPU, Python version).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command on the user's computer and return its output. "
            "Only works if the user has explicitly enabled it; use sparingly and only "
            "for clearly safe commands the user asked for."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The shell command."}},
            "required": ["command"],
        },
    },
]


def dispatch(name: str, args: dict) -> str:
    """Execute a local tool by name and return its string result."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Unknown tool: {name}"
    try:
        return handler(args or {})
    except Exception as exc:  # keep the agent loop alive on tool errors
        return f"Tool {name} failed: {exc}"
