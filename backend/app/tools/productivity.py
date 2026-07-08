"""Productivity tools: todo list, notes, reminders, and a safe calculator.

Each public function takes a single ``args`` dict (as sent by Claude) and
returns a short human-readable string that gets fed back to the model.
"""
from __future__ import annotations

import ast
import operator
from datetime import datetime, timedelta, timezone

from ..db import get_conn

# --------------------------------------------------------------------------
# TODOs
# --------------------------------------------------------------------------

def add_todo(args: dict) -> str:
    task = (args.get("task") or "").strip()
    if not task:
        return "No task text was provided."
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO todos (task) VALUES (?)", (task,))
    return f"Added to-do #{cur.lastrowid}: {task!r}."


def list_todos(args: dict) -> str:
    include_done = bool(args.get("include_done", False))
    query = "SELECT id, task, done FROM todos"
    if not include_done:
        query += " WHERE done = 0"
    query += " ORDER BY id"
    with get_conn() as conn:
        rows = conn.execute(query).fetchall()
    if not rows:
        return "The to-do list is empty."
    lines = [
        f"#{r['id']} [{'x' if r['done'] else ' '}] {r['task']}" for r in rows
    ]
    return "To-dos:\n" + "\n".join(lines)


def complete_todo(args: dict) -> str:
    todo_id = args.get("id")
    with get_conn() as conn:
        cur = conn.execute("UPDATE todos SET done = 1 WHERE id = ?", (todo_id,))
    if cur.rowcount == 0:
        return f"No to-do found with id {todo_id}."
    return f"Marked to-do #{todo_id} as done."


# --------------------------------------------------------------------------
# NOTES
# --------------------------------------------------------------------------

def add_note(args: dict) -> str:
    content = (args.get("content") or "").strip()
    if not content:
        return "No note content was provided."
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO notes (content) VALUES (?)", (content,))
    return f"Saved note #{cur.lastrowid}."


def list_notes(args: dict) -> str:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, content, created_at FROM notes ORDER BY id DESC LIMIT 20"
        ).fetchall()
    if not rows:
        return "No notes saved yet."
    return "Notes:\n" + "\n".join(f"#{r['id']} ({r['created_at']}): {r['content']}" for r in rows)


# --------------------------------------------------------------------------
# REMINDERS
# --------------------------------------------------------------------------

def set_reminder(args: dict) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "No reminder text was provided."

    seconds = args.get("in_seconds")
    minutes = args.get("in_minutes")
    if isinstance(seconds, (int, float)) and seconds > 0:
        total_seconds = float(seconds)
    elif isinstance(minutes, (int, float)) and minutes > 0:
        total_seconds = float(minutes) * 60
    else:
        return "Please tell me how long from now (in seconds or minutes)."

    due = datetime.now(timezone.utc) + timedelta(seconds=total_seconds)
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (text, due_at) VALUES (?, ?)",
            (text, due.isoformat()),
        )

    if total_seconds < 60:
        label = f"{int(total_seconds)} second(s)"
    else:
        label = f"{total_seconds / 60:g} minute(s)"
    return f"Reminder #{cur.lastrowid} set for {label} from now: {text!r}."


def list_reminders(args: dict) -> str:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text, due_at, notified FROM reminders ORDER BY due_at"
        ).fetchall()
    if not rows:
        return "No reminders set."
    lines = []
    for r in rows:
        status = "fired" if r["notified"] else "pending"
        lines.append(f"#{r['id']} ({status}) due {r['due_at']}: {r['text']}")
    return "Reminders:\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# CALCULATOR (safe: no eval of arbitrary code)
# --------------------------------------------------------------------------

_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Unsupported expression")


def calculate(args: dict) -> str:
    expr = (args.get("expression") or "").strip()
    if not expr:
        return "No expression was provided."
    try:
        tree = ast.parse(expr, mode="eval")
        result = _safe_eval(tree.body)
    except Exception:
        return f"Could not evaluate {expr!r}. Use only numbers and + - * / % ** operators."
    return f"{expr} = {result}"


def get_datetime(args: dict) -> str:
    now = datetime.now().astimezone()
    return "Current local date/time: " + now.strftime("%A, %d %B %Y, %I:%M %p %Z")
