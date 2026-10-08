"""Stop hook: rewrite the mechanical half of the session state, every turn.

The reason sessions grow too long is not that nobody watches the number. It is
that ending one is expensive: what was decided, what is half-done and which
files are open all live in the transcript, so a /clear throws them away and
nobody clears. This removes the cost. After every turn the machine-derivable
part of "where are we" is on disk, so a /clear, an autocompact or a crash all
cost the same: nothing.

It writes .claude/session.md, which is deliberately NOT committed. Two sessions
can run against one repo at once and a
per-turn write to a tracked file would collide with whatever the other one is
staging. The prose state stays in the project's own state document,
hand-written.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ctx import git, read_transcript, window_for  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    ctx, edited, ask = read_transcript(payload.get("transcript_path", ""))
    window = window_for((payload.get("model") or {}).get("id", ""))
    pct = round(100 * ctx / window) if window else 0

    branch = git(project, "rev-parse", "--abbrev-ref", "HEAD") or "?"
    status = git(project, "status", "--short")
    recent = git(project, "log", "-3", "--format=%h %s")

    rel = [os.path.relpath(p, project) if p.startswith(project) else p for p in edited]

    lines = [
        "# Session checkpoint",
        "",
        "Written by `.claude/hooks/checkpoint.py` after every turn, and read back",
        "by `SessionStart`. Not committed, and not the prose state - that is",
        "the project's own state document, which stays hand-written.",
        "",
        f"**{time.strftime('%H:%M, %d %b %Y')}** · branch `{branch}` · "
        f"context {ctx // 1000}k ({pct}%)",
        "",
    ]
    if ask:
        lines += [f"**Last ask:** {ask}", ""]
    if rel:
        lines += ["**Edited this session:**", ""]
        lines += [f"- `{p}`" for p in rel[:25]]
        lines += [""]
    if status:
        lines += ["**Working tree:**", "", "```", status, "```", ""]
    if recent:
        lines += ["**Recent commits:**", "", "```", recent, "```", ""]

    try:
        with open(os.path.join(project, ".claude", "session.md"), "w") as fh:
            fh.write("\n".join(lines))
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    # Session hygiene must never be the thing that stops the work. Anything
    # unexpected in here exits clean: the tool runs, the turn ends, the status
    # line just goes quiet.
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
