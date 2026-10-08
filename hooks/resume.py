"""SessionStart hook: a new session opens warm.

Pairs with checkpoint.py. Together they are what makes a fresh session cheap
enough to actually start one - the mechanical state is handed straight back,
so /clear stops being a decision with a cost attached to it.
"""

import json
import os
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    path = os.path.join(project, ".claude", "session.md")
    try:
        with open(path) as fh:
            body = fh.read().strip()
    except OSError:
        return 0

    if body:
        print("Where the last session left off (machine-written, may be stale):\n")
        print(body)
    return 0


if __name__ == "__main__":
    # Session hygiene must never be the thing that stops the work. Anything
    # unexpected in here exits clean: the tool runs, the turn ends, the status
    # line just goes quiet.
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
