"""SubagentStop: the line that says an agent has stopped, and what it cost.

The status line wants to say **which agents are running right now**, and the
payload Claude Code hands it does not carry that - it is about this session,
not about the work sent out of it. What does carry it is the subagent's own
transcript, one file per agent under the session's `tasks/` directory. Reading
those answers name, model and size, but not the one thing they cannot show: a
transcript that has stopped growing is an agent thinking, an agent thirteen
minutes into a long-running check, or an agent that finished an hour ago, and they look
identical on disk.

So this writes the end. One `id timestamp` per line, appended:

    .claude/.state/subagents-done.txt

**The timestamp is the whole of it.** This fires each time an agent finishes
responding, not once per agent, so a `SendMessage` that resumes one writes it
here a second time - which means the file answers "has it stopped at least
once", and on its own that retires an agent the moment its first round ends.
What is wanted is "has it stopped *since*", and the transcript's own mtime
against this stamp is that.

**And it writes the bill, cumulatively.** Same reason: a resumed agent is the
same transcript file, so each stop sums a longer version of it. Every `cost`
row for one agent id supersedes the one before rather than adding to it, and
`bin/agents` keeps the last per id. A delta would be smaller to store and
wrong to read: only the last row is a whole answer.

The answer to "what did today
cost" used to be assembled by hand, by asking each agent what it had spent and
adding the numbers up in a message - which is an estimate wearing a table's clothes,
and it is only available for the session that thinks to ask. The transcript has
the real figure: every assistant row records the usage of the request that
produced it, so the agent's whole bill is those summed, and the model that
answered is on the row beside it. That goes to `agents.jsonl` as a `cost` row,
next to the `spawn` and `round` rows `agents.py` writes, so one file answers
what a fan-out cost and how it was shaped.

Reading the transcript here is affordable in a way it is not in the status
line: this runs once, when an agent stops, rather than on every keystroke.

Like `agents.py` it blocks nothing and may never raise. A missing line costs
one agent shown as running slightly too long, which is why nothing here is
worth being clever about.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone


def short_model(ident: str) -> str:
    """`claude-haiku-4-5-20251001` -> `haiku4.5`. Same shortening the status
    line does, kept simple rather than shared: this file may never import
    something that could fail."""
    ident = (ident or "").lower().replace("[1m]", "")
    for family in ("opus", "sonnet", "haiku"):
        if family not in ident:
            continue
        digits = []
        for part in ident.split(family, 1)[1].split("-"):
            if part.isdigit() and len(part) <= 2:
                digits.append(part)
            elif part:
                break
        return family + ".".join(digits)
    return (ident.rsplit("-", 1)[-1] or "")[:10]


def bill(path: str) -> dict:
    """What the agent actually spent, summed over its own transcript.

    Every request's input is counted the way `_ctx.py` counts a session's:
    `input + cache_creation + cache_read` is what that request carried. Summed
    over the turns it is the volume that was read, which is the number that
    makes a long run expensive - turn n carries everything turns 1..n-1 built
    up, and only a sum shows that.

    **A turn is one API request, not one transcript row, and that distinction
    cost me every figure I first published.** One assistant message
    holding two `tool_use` blocks is written as two rows carrying the *same*
    `usage` object, so counting rows both inflates the token sum - by 1.55x,
    measured - and makes every message look as though it issued exactly one
    tool call. The batching rate came out at 1.00 and was published as "not one
    message in two days issued two calls"; grouped by `message.id` it is 7.4%.
    Deduplicating on that id is what makes `turns` mean the thing `TURN_BUDGET`
    is set in. **Rows written before this fix are in the old unit** - a run
    billed at 300 turns then is about 195 requests."""
    got = {"turns": 0, "in": 0, "out": 0, "cache_read": 0, "model": "", "agent": ""}
    first = last = ""
    counted = set()
    # Tool calls per message, summed across the rows one message was split
    # into. This is the only place the number is free: the transcript is
    # already open, and `bin/agents` would otherwise have to reopen every
    # agent's file to answer the one question the measurement said was the
    # largest lever. Two calls in one message is one turn; the ratio of these
    # two is how much of that is being taken.
    calls = {}
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                stamp = row.get("timestamp") or ""
                if stamp:
                    first = first or stamp
                    last = stamp
                message = row.get("message") or {}
                usage = message.get("usage")
                if row.get("type") != "assistant" or not usage:
                    continue
                # Counted before the dedupe below, because the second row of a
                # split message is exactly where the second tool call is.
                ident = message.get("id")
                if ident:
                    calls[ident] = calls.get(ident, 0) + sum(
                        1
                        for block in (message.get("content") or [])
                        if isinstance(block, dict) and block.get("type") == "tool_use"
                    )
                # One request, however many rows the transcript split it into.
                # A row with no id cannot be joined to another, so it counts as
                # a turn - but it is outside `msgs`/`multi` above, which need an
                # id to group by. No such row exists in this project's
                # transcripts today; if one appears, `batch` under-reports.
                if ident:
                    if ident in counted:
                        continue
                    counted.add(ident)
                got["turns"] += 1
                got["in"] += (usage.get("input_tokens") or 0) + (
                    usage.get("cache_creation_input_tokens") or 0
                )
                got["cache_read"] += usage.get("cache_read_input_tokens") or 0
                got["out"] += usage.get("output_tokens") or 0
                got["model"] = short_model(message.get("model")) or got["model"]
                got["agent"] = row.get("attributionAgent") or got["agent"]
    except OSError:
        return got

    # Messages that called a tool, and how many of those called more than one.
    # A message with no tool call is a report or a question and is not a missed
    # chance to batch, so it is out of both.
    acting = [n for n in calls.values() if n]
    got["msgs"] = len(acting)
    got["multi"] = sum(1 for n in acting if n > 1)

    for fmt in (first, last):
        if not fmt:
            return got
    try:
        a = datetime.fromisoformat(first.replace("Z", "+00:00"))
        b = datetime.fromisoformat(last.replace("Z", "+00:00"))
        got["secs"] = int((b - a).total_seconds())
    except ValueError:
        pass
    return got


def main() -> None:
    payload = json.loads(sys.stdin.read())

    # `agent_id` is the id the tasks directory names its transcript by. The
    # payload's `transcript_path` is the *parent* session's, which is the trap
    # here - it looks like the right field and writes a session id into a file
    # of agent ids, so nothing ever matches and every agent shows as running
    # for ever. `agent_transcript_path` is the subagent's own.
    agent_path = payload.get("agent_transcript_path") or ""
    agent_id = payload.get("agent_id") or ""
    if not agent_id:
        agent_id = os.path.basename(agent_path).rsplit(".", 1)[0].removeprefix("agent-")
    if not agent_id:
        return

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    state = os.path.join(project, ".claude", ".state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "subagents-done.txt"), "a") as fh:
        fh.write(f"{agent_id} {int(time.time())}\n")

    if not agent_path or not os.path.exists(agent_path):
        return
    got = bill(agent_path)
    if not got["turns"]:
        return
    row = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session": (payload.get("session_id") or "")[:8],
        "kind": "cost",
        "agent": got.pop("agent") or "agent",
        "id": agent_id[:8],
        # What `turns` counts. Rows written before the fix carry no
        # `unit` and are transcript lines, about 1.55x a request; a date
        # comparison could not separate them, because the fix landed in the
        # middle of a day whose earlier rows are in the old unit.
        "unit": "req",
    }
    row.update(got)
    with open(os.path.join(state, "agents.jsonl"), "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
