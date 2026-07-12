"""Find and install software via winget, Windows' official package manager.

Flow the model is told to follow: search first (so it learns the exact
package Id), then install with that Id. Installation is gated behind the
assistant's voice-confirmation flow (see agent._CONFIRM_TOOLS) — Echo always
asks before changing what's installed on the PC.

winget output is a fixed-width text table; we locate the column offsets from
the header row and slice each line, which survives long names and the
truncation ellipsis winget inserts.
"""
from __future__ import annotations

import shutil
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _winget_available() -> bool:
    return shutil.which("winget") is not None


def _run(args: list[str], timeout: int) -> tuple[int, str]:
    completed = subprocess.run(
        ["winget", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    out = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, out


def _parse_search_table(output: str) -> list[dict]:
    """Slice winget's fixed-width results table using header column offsets."""
    lines = [ln.rstrip() for ln in output.splitlines() if ln.strip()]
    header_idx = next(
        (i for i, ln in enumerate(lines) if "Name" in ln and "Id" in ln and "Source" in ln),
        None,
    )
    if header_idx is None or header_idx + 2 >= len(lines) + 1:
        return []
    header = lines[header_idx]
    # "Match" is an optional column winget inserts between Version and Source
    # when a result matched via tag/moniker/product code.
    cols = {name: header.index(name) for name in ("Name", "Id", "Version", "Match", "Source") if name in header}
    version_end = cols.get("Match") or cols.get("Source")
    results = []
    for line in lines[header_idx + 2:]:  # skip the ----- separator row
        if len(line) < cols["Id"]:
            continue
        entry = {
            "name": line[cols["Name"]:cols["Id"]].strip(),
            "id": line[cols["Id"]:cols.get("Version", len(line))].strip(),
            "version": line[cols.get("Version", 0):version_end].strip()
            if "Version" in cols else "",
            "source": line[cols["Source"]:].strip() if "Source" in cols else "",
        }
        if entry["name"] and entry["id"]:
            results.append(entry)
    # Prefer the community winget source over msstore (msstore installs can
    # require a signed-in Store account; winget-source ones never do).
    results.sort(key=lambda e: 0 if e["source"] == "winget" else 1)
    return results


def search_software(args: dict) -> str:
    """Tool handler: find installable packages matching a name."""
    query = (args.get("query") or "").strip()
    if not query:
        return "What software should I search for?"
    if not _winget_available():
        return "winget isn't available on this PC, so I can't search for software."
    try:
        code, out = _run(
            ["search", query, "--count", "8", "--disable-interactivity"], timeout=60
        )
    except subprocess.TimeoutExpired:
        return "The software search timed out. Try again?"
    if "No package found" in out or code != 0 and not out.strip():
        return f"No installable package found matching '{query}'."
    results = _parse_search_table(out)
    if not results:
        return f"No installable package found matching '{query}'."
    lines = [
        f'{e["name"]} (id: {e["id"]}'
        + (f', version {e["version"]}' if e["version"] else "")
        + (f", from {e['source']}" if e["source"] else "")
        + ")"
        for e in results[:5]
    ]
    return "Found: " + "; ".join(lines) + ". Use install_software with the exact id."


def install_software(args: dict) -> str:
    """Tool handler: install a package by its exact winget Id (confirmed first)."""
    package_id = (args.get("id") or args.get("name") or "").strip()
    if not package_id:
        return "I need the package id to install (use search_software first)."
    if not _winget_available():
        return "winget isn't available on this PC, so I can't install software."
    try:
        code, out = _run(
            [
                "install",
                "--id", package_id,
                "--exact",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            timeout=900,  # big installers are slow
        )
    except subprocess.TimeoutExpired:
        return f"The install of {package_id} is taking longer than 15 minutes — check on it manually."
    lowered = out.lower()
    if code == 0:
        if "already installed" in lowered:
            return f"{package_id} is already installed on this PC."
        return f"Installed {package_id} successfully."
    if "already installed" in lowered:
        return f"{package_id} is already installed on this PC."
    tail = out.strip().splitlines()[-1] if out.strip() else f"exit code {code}"
    return f"Could not install {package_id}: {tail}"
