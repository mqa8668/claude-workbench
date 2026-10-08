"""PreToolUse on the Agent tool: the ledger, and it blocks nothing.

The case for delegating was argued twice on feeling. `/usage` turned "we are
delegating a lot" into "92% of a day, 47% of it untyped", and that number is
what produced typed agents. Then the question came back a different way -
seventeen subagents, roughly 1.9M subagent tokens, a main
window that stayed usable - and there was no equivalent number for **where the
coordination went**. That is what this writes down.

It is deliberately not a brake. `guard.py` is the brake and it earns that by
refusing four specific things, each once; a second hook refusing spawns would
be a hook that gets switched off. This one appends a line and exits.

**The two hooks match the same three tools and must not share a file.** They
run in parallel, and `_ctx.save_state` is a whole-file write with no lock, so
two writers of `<session>.json` on one event means whichever lands last throws
the other away. This one keeps the read budget there because it is the only
writer of that field on these events; `guard.py` keeps its round and budget
counters in a file of its own.

Three kinds of row go to `.claude/.state/agents.jsonl`, told apart by `kind`:

    spawn  {"ts", "session", "agent", "desc", "chars", "brief", "model"}
    round  {"ts", "session", "agent", "chars"}
    cost   written by `subagent.py` when the agent stops

`brief` is the field the spawn row exists for: whether the prompt handed to the
agent points at a `BRIEF.md`. A fan-out with `brief: false` on every row is
exactly that shape - several agents sent out to work the same facts
out for themselves - and it is invisible in a transcript, because each of those
agents was individually doing the right thing.

**`round` is the row this file was missing, and it was missing the expensive
one.** One day the ledger held thirteen lines for a day that spent
2.4M subagent tokens, because a spawn is one line and the eight `SendMessage`
rounds that followed it were none. Rounds are where the money goes: a spawn
costs the law plus the brief once, while round n re-sends everything the agent
has accumulated, so eight of them is not eight times a round - it is nearer
forty. What is not written down here gets argued about on feeling, twice, which
is how this file came to exist in the first place.

**And rounds were still not the biggest thing.** Measured on my own projects,
a run's cost goes as the square of its *turns* whether those turns arrive in one
round or eight - the longest single run in the ledger was 342 requests and 78M,
in one round. The rows here are what makes a fan-out's shape visible; the turn
count `subagent.py` writes beside them is what predicts the bill.

Reading it back is `bin/agents`.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ctx import load_state, save_state  # noqa: E402

BRIEF = re.compile(r"BRIEF\.md|scratchpad/jobs/", re.IGNORECASE)


def main() -> None:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        return

    tool = payload.get("tool_name") or ""
    if tool not in ("Task", "Agent", "SendMessage"):
        return

    ti = payload.get("tool_input") or {}
    session = payload.get("session_id") or ""

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    d = os.path.join(project, ".claude", ".state")
    os.makedirs(d, exist_ok=True)
    ledger = os.path.join(d, "agents.jsonl")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if tool == "SendMessage":
        # No round number here. Counting is `guard.py`'s, which holds the cap,
        # and two counters for one thing is two things to disagree. Which round
        # this was is how many of these rows come before it.
        row = {
            "ts": now,
            "session": session[:8],
            "kind": "round",
            "agent": ti.get("to") or "?",
            "chars": len(ti.get("message") or ""),
        }
    else:
        prompt = ti.get("prompt") or ""
        row = {
            "ts": now,
            "session": session[:8],
            "kind": "spawn",
            "agent": ti.get("subagent_type") or "general-purpose",
            "desc": (ti.get("description") or "")[:80],
            "chars": len(prompt),
            "brief": bool(BRIEF.search(prompt)),
            "model": ti.get("model") or "",
        }
    with open(ledger, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # A spawn resets guard.py's read budget, and so does a round - both are
    # the session delegating. Two reasons, and they point the same way. The
    # brake exists to push an investigation out of the main window, so a
    # session that has just delegated has done the thing it asks for. And a
    # subagent shares its parent's `session_id` and its state file, so without
    # this it inherits a budget the parent already spent - a reviewer was
    # refused its third read and told to delegate, which it
    # is not permitted to do.
    state = load_state(project, session)
    state["reads"] = 0
    said = state.get("said") or []
    state["said"] = [s for s in said if s != "fanout"]
    save_state(project, session, state)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Nothing here may ever be the thing that stops the work.
        pass
    sys.exit(0)
