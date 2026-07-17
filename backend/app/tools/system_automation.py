"""System automation tools (Windows-focused, cross-platform where easy).

`open_application` verifies an app is actually installed (real exe path or a
registered URL protocol) BEFORE launching, and reports honestly when it can't
find it — instead of blindly running `start <name>` and claiming success.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import webbrowser

from ..config import settings

# Friendly name -> ordered list of launch strategies. Each strategy is a tuple:
#   ("exe",   "<name on PATH>", [extra args])
#   ("path",  r"%ENV%\App.exe", [extra args])   # only if the file exists
#   ("proto", "<url scheme>")                    # only if the protocol is registered
#   ("shell", "<command>")                       # always attempted (builtin URIs)
_WINDOWS_APPS: dict[str, list[tuple]] = {
    "notepad": [("exe", "notepad")],
    "calculator": [("exe", "calc"), ("proto", "calculator")],
    "calc": [("exe", "calc")],
    "paint": [("exe", "mspaint")],
    "explorer": [("exe", "explorer")],
    "file explorer": [("exe", "explorer")],
    "command prompt": [("exe", "cmd")],
    "cmd": [("exe", "cmd")],
    "powershell": [("exe", "powershell")],
    "terminal": [("exe", "wt"), ("exe", "powershell")],
    "task manager": [("exe", "taskmgr")],
    "settings": [("shell", 'start "" ms-settings:')],
    "chrome": [
        ("path", r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        ("path", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        ("path", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ("exe", "chrome"),
    ],
    "edge": [
        ("path", r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        ("path", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ("exe", "msedge"),
    ],
    "browser": [
        ("path", r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        ("exe", "msedge"),
        ("exe", "chrome"),
    ],
    "discord": [
        ("path", r"%LOCALAPPDATA%\Discord\Update.exe", ["--processStart", "Discord.exe"]),
        ("proto", "discord"),
    ],
    "whatsapp": [("proto", "whatsapp")],
    "telegram": [("path", r"%APPDATA%\Telegram Desktop\Telegram.exe"), ("proto", "tg")],
    "spotify": [("path", r"%APPDATA%\Spotify\Spotify.exe"), ("proto", "spotify")],
    "steam": [("path", r"%ProgramFiles(x86)%\Steam\steam.exe"), ("proto", "steam")],
    "vscode": [("exe", "code")],
    "vs code": [("exe", "code")],
    "code": [("exe", "code")],
    "word": [("exe", "winword")],
    "excel": [("exe", "excel")],
    "outlook": [("exe", "outlook")],
}


def _protocol_registered(scheme: str) -> bool:
    """True if a Windows app has registered this URL scheme (i.e. it's installed)."""
    if platform.system() != "Windows":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, scheme):
            return True
    except OSError:
        return False


def _try_strategy(kind: str, value: str, extra: list | None) -> bool:
    """Attempt one launch strategy. Returns True only if it plausibly launched."""
    if kind == "exe":
        exe = shutil.which(value)
        if exe:
            subprocess.Popen([exe, *(extra or [])])
            return True
        return False
    if kind == "path":
        full = os.path.expandvars(value)
        if os.path.exists(full):
            subprocess.Popen([full, *(extra or [])])
            return True
        return False
    if kind == "proto":
        if _protocol_registered(value):
            os.startfile(f"{value}://")  # noqa: S606 - Windows only
            return True
        return False
    if kind == "shell":
        subprocess.Popen(value, shell=True)
        return True
    return False


def open_application(args: dict) -> str:
    name = (args.get("name") or "").strip().lower()
    if not name:
        return "No application name was provided."

    system = platform.system()
    if system != "Windows":
        opener = "open" if system == "Darwin" else "xdg-open"
        if shutil.which(opener):
            try:
                subprocess.Popen([opener, name])
                return f"Attempting to open {name}."
            except Exception as exc:
                return f"Could not open {name}: {exc}"
        return f"Opening apps isn't supported on this platform ({system})."

    # Primary path: the dynamic index of everything installed (no hardcoding).
    from . import app_index

    # "open youtube" means the website, even though a YouTube Music app may be
    # installed — spoken web destinations beat fuzzy app matches.
    if name in app_index.WEBSITES:
        webbrowser.open(app_index.WEBSITES[name])
        return f"Opened {name} in the browser."

    result = app_index.open_by_name(name)
    if not result.startswith("I couldn't find"):
        return result

    # Fallbacks for things without a Start Menu entry: PATH exes, URL protocols,
    # and the small legacy strategy table.
    strategies = _WINDOWS_APPS.get(name, [("exe", name), ("proto", name)])
    for strat in strategies:
        kind, value = strat[0], strat[1]
        extra = strat[2] if len(strat) > 2 else None
        try:
            if _try_strategy(kind, value, extra):
                return f"Opening {name}."
        except Exception:
            continue

    return result


def send_whatsapp(args: dict) -> str:
    """Send a WhatsApp message to a contact by NAME via WhatsApp Desktop.

    Drives the keyboard: opens WhatsApp, searches the contact, types the
    message, and presses Enter to send. Requires WhatsApp Desktop installed
    and logged in. Best-effort UI automation — timing dependent.
    """
    contact = (args.get("contact") or "").strip()
    message = (args.get("message") or "").strip()
    if not contact or not message:
        return "I need both a contact name and a message to send."
    if platform.system() != "Windows":
        return "WhatsApp automation is only supported on Windows right now."
    if not _protocol_registered("whatsapp"):
        return "WhatsApp Desktop doesn't appear to be installed on this PC."

    try:
        import time

        import pyautogui
        import pyperclip
    except Exception as exc:  # pragma: no cover
        return f"WhatsApp automation needs extra packages that aren't available: {exc}"

    try:
        pyautogui.FAILSAFE = True
        os.startfile("whatsapp://")           # open / focus WhatsApp Desktop
        time.sleep(5)
        pyautogui.hotkey("ctrl", "n")          # new-chat contact search
        time.sleep(2)
        pyperclip.copy(contact)                # paste (handles any characters)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(2.5)
        pyautogui.press("enter")               # open the top matching contact
        time.sleep(2)
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1)
        pyautogui.press("enter")               # send
        time.sleep(0.5)
    except Exception as exc:
        return f"Something went wrong while automating WhatsApp: {exc}"

    return (
        f'Unverified WhatsApp send: I pressed send for "{message}" to {contact}, '
        "but WhatsApp Desktop does not expose reliable delivery verification to this automation. "
        "Please check the chat."
    )


def _verify_discord_last_message(pyautogui, pyperclip, expected: str) -> bool:
    """Best-effort Discord check: Up opens edit mode for your last message."""
    try:
        import time

        previous_clipboard = pyperclip.paste()
        time.sleep(1)
        pyautogui.press("up")
        time.sleep(0.35)
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)
        copied = (pyperclip.paste() or "").strip()
        pyautogui.press("esc")
        if previous_clipboard is not None:
            pyperclip.copy(previous_clipboard)
        return copied == expected.strip()
    except Exception:
        return False


def send_discord_message(args: dict) -> str:
    """Send a Discord direct message by contact/server-channel search.

    Uses Discord's quick switcher (Ctrl+K), so the contact or channel name must
    be searchable in the signed-in Discord account.
    """
    contact = (args.get("contact") or "").strip()
    message = (args.get("message") or "").strip()
    if not contact or not message:
        return "I need both a Discord contact/channel name and a message to send."
    if platform.system() != "Windows":
        return "Discord message automation is only supported on Windows right now."

    try:
        import time

        import pyautogui
        import pyperclip
    except Exception as exc:  # pragma: no cover
        return f"Discord automation needs extra packages that aren't available: {exc}"

    launched = False
    for strat in _WINDOWS_APPS.get("discord", []):
        kind, value = strat[0], strat[1]
        extra = strat[2] if len(strat) > 2 else None
        try:
            if _try_strategy(kind, value, extra):
                launched = True
                break
        except Exception:
            continue
    if not launched:
        return "Discord doesn't appear to be installed or registered on this PC."

    try:
        pyautogui.FAILSAFE = True
        time.sleep(6)
        pyautogui.hotkey("ctrl", "k")          # Discord quick switcher
        time.sleep(1)
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(1.5)
        pyautogui.press("enter")
        time.sleep(2)
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.5)
        pyautogui.press("enter")
        verified = _verify_discord_last_message(pyautogui, pyperclip, message)
    except Exception as exc:
        return f"Something went wrong while automating Discord: {exc}"

    if verified:
        return (
            f'Verified Discord send: "{message}" appeared as your latest sent message '
            f"after opening {contact}."
        )
    return (
        f'Unverified Discord send: I pressed send for "{message}" after opening {contact}, '
        "but I could not verify the sent text in Discord. Please check the chat."
    )


def play_youtube(args: dict) -> str:
    """Actually PLAY a song/video on YouTube: find the top search result and
    open its watch page (which autoplays). Use this for "play X" requests."""
    query = (args.get("query") or "").strip()
    if not query:
        return "What would you like me to play?"

    import re
    import urllib.parse
    import webbrowser

    import httpx

    search_url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    try:
        html = httpx.get(
            search_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"},
            timeout=10,
            follow_redirects=True,
        ).text
        match = re.search(r'"videoId":"([\w-]{11})"', html)
    except Exception as exc:
        webbrowser.open(search_url)
        return f"I opened a YouTube search for {query} (couldn't auto-play: {exc})."

    if not match:
        webbrowser.open(search_url)
        return f"I opened a YouTube search for {query}, but couldn't auto-pick a video."

    webbrowser.open(f"https://www.youtube.com/watch?v={match.group(1)}")
    return f"Now playing {query} on YouTube."


def _volume_iface():
    """Get the Windows master-volume COM interface (via pycaw)."""
    from ctypes import POINTER, cast

    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(args: dict) -> str:
    """Set the system volume to an exact level (0-100), or change it by an amount."""
    if platform.system() != "Windows":
        return "Volume control is only supported on Windows."
    try:
        vol = _volume_iface()
        current = vol.GetMasterVolumeLevelScalar() * 100
    except Exception as exc:
        return f"Couldn't access the system volume: {exc}"

    level = args.get("level")
    change = args.get("change")
    if isinstance(level, (int, float)):
        target = float(level)
    elif isinstance(change, (int, float)):
        target = current + float(change)
    else:
        return "Tell me a volume level (0-100) or how much to change it by."

    target = max(0.0, min(100.0, target))
    try:
        vol.SetMasterVolumeLevelScalar(target / 100.0, None)
        vol.SetMute(0, None)  # setting a level implies unmute
    except Exception as exc:
        return f"Couldn't change the volume: {exc}"
    return f"Volume set to {int(round(target))}%."


def media_control(args: dict) -> str:
    """Control playback per media session (targeted), volume via pycaw.

    Session-targeted control means "pause the music" pauses the actual music
    app instead of blindly toggling whatever Windows considers active — the
    global media key is only the fallback.
    """
    action = (args.get("action") or "").strip().lower()
    target = (args.get("target") or "").strip()

    playback = {
        "play": "playpause",
        "pause": "playpause",
        "stop": "playpause",
        "playpause": "playpause",
        "next": "nexttrack",
        "previous": "prevtrack",
        "prev": "prevtrack",
    }
    if action in playback:
        if action != "playpause":
            from . import now_playing

            result = now_playing.control_sync(action, target)
            if result is not None:
                return result
        try:
            import pyautogui

            pyautogui.press(playback[action])
        except Exception as exc:
            return f"Couldn't send the media key: {exc}"
        return f"Done — {action}."

    # Volume actions go through the precise pycaw path.
    if action == "volume_up":
        return set_volume({"change": 10})
    if action == "volume_down":
        return set_volume({"change": -10})
    if action in ("mute", "unmute"):
        if platform.system() != "Windows":
            return "Mute is only supported on Windows."
        try:
            vol = _volume_iface()
            new_state = 0 if action == "unmute" else 1
            vol.SetMute(new_state, None)
        except Exception as exc:
            return f"Couldn't toggle mute: {exc}"
        return "Muted." if new_state else "Unmuted."

    return (
        f"I can't do '{action}'. Try: play, pause, stop, next, previous, "
        "volume_up, volume_down, or mute. To set an exact level, use set_volume."
    )


def close_window(args: dict) -> str:
    """Close an open window / browser tab-window by matching its title.

    Note: browsers don't expose individual tabs to outside apps, so this closes
    the whole matching window. It never closes the assistant's own window.
    """
    name = (args.get("name") or "").strip().lower()
    if not name:
        return "Which window should I close?"

    try:
        import pygetwindow as gw
    except Exception as exc:  # pragma: no cover
        return f"Window control isn't available: {exc}"

    self_markers = ("echo", "voice assistant", "jarvis", "localhost:5173")
    matches = [
        w
        for w in gw.getAllWindows()
        if w.title
        and name in w.title.lower()
        and not any(mark in w.title.lower() for mark in self_markers)
    ]
    if not matches:
        return f"I couldn't find an open window matching '{name}'."

    try:
        matches[0].close()
    except Exception as exc:
        return f"I found it but couldn't close it: {exc}"
    return f"Closed the window matching '{name}'."


def open_url(args: dict) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        return "No URL was provided."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the default browser."


def get_system_info(args: dict) -> str:
    uname = platform.uname()
    return (
        f"System: {uname.system} {uname.release}\n"
        f"Machine: {uname.machine}\n"
        f"Processor: {uname.processor or 'unknown'}\n"
        f"Python: {platform.python_version()}"
    )


def run_command(args: dict) -> str:
    if not settings.allow_shell_commands:
        return (
            "Shell command execution is disabled for safety. "
            "Set ALLOW_SHELL_COMMANDS=true in the .env file to enable it."
        )
    command = (args.get("command") or "").strip()
    if not command:
        return "No command was provided."
    try:
        completed = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds."
    out = (completed.stdout or "").strip()
    err = (completed.stderr or "").strip()
    parts = [f"Exit code: {completed.returncode}"]
    if out:
        parts.append(f"stdout:\n{out[:2000]}")
    if err:
        parts.append(f"stderr:\n{err[:1000]}")
    return "\n".join(parts)
