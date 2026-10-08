#!/usr/bin/env python3
"""A small status line for Claude Code that shows the workbench's segments.

Claude Code runs the command named in `statusLine` in settings.json, writes a
JSON payload to its stdin and shows the first line of stdout. This script reads
that payload and prints something like:

    myrepo  main*  opus  5h 41%  gate 12m  e2e stale  5173 5432

The first four fields come from the payload and git. The rest come from
`statusline-extra.py`, which reads `.claude/gates.json`. That module also leaves
the five-hour usage figure in `.claude/.state/budget.json`, which is how the
context guard knows the window is nearly spent. So this host is the thing that
makes the rate-window brake work.

It looks for the segments module next to itself first (`/init-workbench` copies
both into `.claude/hooks/`), then in the plugin's `templates/` directory.
Nothing here raises: a broken segment is dropped and the rest still print.

Standard library only. Set NO_COLOR=1 for plain text.
"""

import importlib.util
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def colours() -> dict:
    """ANSI codes, or empty strings when colour is off."""
    on = not os.environ.get("NO_COLOR")
    code = (
        {
            "off": "\033[0m",
            "dim": "\033[2m",
            "faint": "\033[90m",
            "bold": "\033[1m",
            "calm": "\033[36m",
            "green": "\033[32m",
            "red": "\033[31m",
            "yellow": "\033[33m",
        }
        if on
        else {}
    )
    c = {
        k: code.get(k, "")
        for k in ("off", "dim", "faint", "bold", "calm", "green", "red", "yellow")
    }

    def glyph(name: str, then: str = "", mono: str = "") -> str:
        """This host draws no icons, so every glyph is its `mono` fallback."""
        return mono

    c["glyph"] = glyph
    return c


def git_state(project: str) -> tuple:
    """(branch, changed absolute paths). Empty on anything that goes wrong."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "-b"],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return "", []
    branch = ""
    changed = []
    for line in out:
        if line.startswith("## "):
            branch = line[3:].split("...")[0].split(" ")[0]
        elif len(line) > 3:
            path = line[3:].split(" -> ")[-1].strip('"')
            changed.append(os.path.join(project, path))
    return branch, changed


def load_extra():
    """The segments module, from beside this file or from the plugin."""
    for path in (
        os.path.join(HERE, "statusline-extra.py"),
        os.path.join(os.path.dirname(HERE), "templates", "statusline-extra.py"),
    ):
        if not os.path.exists(path):
            continue
        spec = importlib.util.spec_from_file_location("workbench_extra", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    return None


def render(payload: dict) -> str:
    c = colours()
    workspace = payload.get("workspace") or {}
    project = workspace.get("project_dir") or workspace.get("current_dir") or os.getcwd()
    branch, changed = git_state(project)
    c["changed"] = changed

    head = [f"{c['bold']}{os.path.basename(project) or project}{c['off']}"]
    if branch:
        head.append(f"{c['calm']}{branch}{'*' if changed else ''}{c['off']}")
    model = (payload.get("model") or {}).get("display_name")
    if model:
        head.append(f"{c['dim']}{model}{c['off']}")
    five = ((payload.get("rate_limits") or {}).get("five_hour") or {}).get("used_percentage")
    if five is not None:
        try:
            hot = int(five) >= 75
            colour = c["red"] if hot else c["faint"]
            head.append(f"{colour}5h {int(five)}%{c['off']}")
        except (TypeError, ValueError):
            pass

    rest = []
    try:
        extra = load_extra()
        if extra is not None:
            rest = [s for s in extra.segments(payload, c) if s]
    except Exception:  # a segment must never take the line down
        rest = []
    return "  ".join(head + rest)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}
    print(render(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
