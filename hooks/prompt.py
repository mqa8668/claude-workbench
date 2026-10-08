"""UserPromptSubmit hook: tell Claude where the session stands, not the user.

This is the half of point 2 that is NOT the status line. The status line is for
a person to glance at; this one line goes into Claude's own context, because
the whole agreement was that the adjusting is done by the machine rather than
asked of the reader. Silent below 200k, so it costs nothing on a normal turn.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ctx import HOT, WARM, read_transcript, window_for  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    ctx, _, _ = read_transcript(payload.get("transcript_path", ""))
    window = window_for((payload.get("model") or {}).get("id", ""))
    pct = round(100 * ctx / window) if window else 0

    if ctx >= HOT:
        print(
            f"[session] context {ctx // 1000}k ({pct}%). Take no new work. Finish the "
            "step in hand, make sure docs/STATE.md carries the prose state, and tell "
            "the user plainly that the next chunk wants a fresh session."
        )
    elif ctx >= WARM:
        print(
            f"[session] context {ctx // 1000}k ({pct}%). Past here, delegate rather "
            "than read: send investigation and file-heavy work to subagents and keep "
            "only their conclusions. Say so once, briefly, rather than every turn."
        )
    return 0


if __name__ == "__main__":
    # Session hygiene must never be the thing that stops the work. Anything
    # unexpected in here exits clean: the tool runs, the turn ends, the status
    # line just goes quiet.
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
