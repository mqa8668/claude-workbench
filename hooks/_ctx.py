"""Shared helpers for the session-hygiene hooks.

The one thing everything here needs is an honest answer to "how big is this
session now". The transcript JSONL carries it exactly: every assistant message
records the usage of the request that produced it, and the context that request
carried is `input + cache_creation + cache_read`. That is a measurement rather
than an estimate, which matters - a byte-count proxy drifts badly once a
session has read images or been compacted.

Subagent turns live in the same file marked `isSidechain`. They burn their own
window and are the whole point of delegating, so they are skipped: counting
them would make the number climb for work that is deliberately kept out of the
main context.
"""

import json
import os
import re
import subprocess

WINDOW_1M = 1_000_000
WINDOW_STD = 200_000

# Where a session stops being cheap. Not cliffs - the failure of a long session
# is gradual (stale file reads, path dependence), so these are the points where
# the shape of the work should change, not where anything breaks.
WARM = 200_000
HOT = 350_000


def window_for(model_id: str) -> int:
    return WINDOW_1M if "1m" in (model_id or "").lower() else WINDOW_STD


def read_transcript(path: str):
    """Return (context_tokens, edited_paths, last_user_ask)."""
    ctx = 0
    edited: list[str] = []
    ask = ""
    if not path or not os.path.exists(path):
        return ctx, edited, ask

    with open(path, errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("isSidechain"):
                continue

            msg = rec.get("message") or {}
            usage = msg.get("usage")
            if usage:
                ctx = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("output_tokens", 0)
                )

            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        for f in _written(block):
                            if f not in edited:
                                edited.append(f)
                    elif block.get("type") == "text" and rec.get("type") == "user":
                        ask = block.get("text", "") or ask
            elif isinstance(content, str) and rec.get("type") == "user":
                ask = content or ask

    # A pasted system-reminder or a tool result is not the user asking for
    # something; keep what actually reads like a request.
    ask = re.sub(r"<[^>]+>.*?</[^>]+>", " ", ask, flags=re.S)
    ask = " ".join(ask.split())
    return ctx, edited, ask[:200]


# In bypass-permissions mode files get written with a heredoc through Bash
# rather than through Edit or Write, so counting tool names alone reports zero
# edits on a session that rewrote a dozen files. Redirections are the honest
# signal here.
_REDIRECT = re.compile(r">>?\s*([\w./~-]+)")


def _written(block: dict) -> list:
    name = block.get("name")
    args = block.get("input") or {}
    if name in ("Edit", "Write", "NotebookEdit"):
        path = args.get("file_path")
        return [path] if path else []
    if name != "Bash":
        return []
    out = []
    for path in _REDIRECT.findall(args.get("command", "")):
        if path.startswith("/dev/") or path.startswith("/tmp") or "/" not in path:
            continue
        if ".gate-logs" in path or "/scratchpad" in path:
            continue
        out.append(path)
    return out


def state_path(project_dir: str, session_id: str) -> str:
    d = os.path.join(project_dir, ".claude", ".state")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{session_id or 'unknown'}.json")


def load_state(project_dir: str, session_id: str) -> dict:
    try:
        with open(state_path(project_dir, session_id)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(project_dir: str, session_id: str, state: dict) -> None:
    try:
        with open(state_path(project_dir, session_id), "w") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def git(project_dir: str, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
