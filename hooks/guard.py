"""PreToolUse hook: the brake, and it is aimed at Claude rather than at the user.

Everything here blocks a tool call and hands the reason back to Claude on
stderr. None of it reaches the terminal, because the user is not meant to manage
this - the status line says where things stand, and the adjusting happens
here.

Four things are stopped. The first two are about this session's own window and
the last two are about the work it sends out; the first three fire once and get
out of the way, and the round brake **re-arms** after each override, so a
further round costs a further deliberate repeat rather than riding one:

* **A gate run bare.** `mix precommit` compiles, formats, runs credo and the
  whole suite; `npm run build` runs tsr, tsc twice and vite. Thousands of lines
  each, several times a session, and none of it is worth keeping once it says
  PASS. `bin/gate` puts the log in a file and prints the verdict.
* **Reading past the point where it should have been delegated.** Not a hard
  stop - it fires once, says its piece, and gets out of the way. A guard that
  keeps refusing gets switched off.
* **A second message to the same agent.** A round re-sends everything that
  agent has accumulated, on top of a transcript that is already the expensive
  thing - measured on my own projects, a run carries 150-350k per request against a 48k cold
  start. The cheaper move is a fresh spawn off the brief, which is by then
  cumulative and holds what the round established. Each further round is
  refused once and let through on the repeat, so an override buys one round
  rather than unlimiting them.
* **Opening a fan-out on a spent five-hour budget.** Once the
  window ran out mid-flight and cut two long-running agents in half; both
  had to be run again from cold, which is the most expensive way there is to
  buy a result already paid for.

A blocked call is never a dead end. Every message below names the thing to do
instead, in a form that runs.
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ctx import load_state, save_state  # noqa: E402

# Reads in the main session before the fan-out is worth a subagent. Generous on
# purpose: the point is to catch a session drifting into an investigation, not
# to police ordinary work.
READ_FANOUT = 30
BIG_FILE_LINES = 400

# Messages to one agent before a fresh spawn off the brief is the cheaper move.
# This was four once, on the theory that the cold start
# dominated below it. Measured on my own projects, the cold start is ~50k and an agent's run
# reaches 60M, so the two costs do not cross anywhere near four - a round is
# never the cheaper move, and a live agent's transcript is already the
# expensive thing before the round is added to it. One, and the second message
# is a spawn.
ROUND_CAP = 1

# The turn budget lives in `bin/agents`, which is the only thing that reads it.
# A copy stood here for one afternoon and nothing consulted it: `PreToolUse`
# fires inside a subagent on some days and not others, so this hook cannot count an agent's turns and a constant here would
# have been documentation wearing a brake's clothes.

# The agents a spent five-hour window should not stop, because re-running one
# costs almost nothing: each runs a script and hands back a verdict. The list
# is `cheap_agents` in `.claude/gates.json`; this is the default.
#
# **By name, not by model.** This once read `_pinned_model in ("haiku",
# "sonnet")`, which quietly made the brake a function of a frontmatter line
# rather than of what an agent does. Repinning a build agent to a cheaper model
# would have handed the most expensive agent in the project a free pass through
# the brake below, which is the opposite of what it is for. A model pin is a
# statement about the work's difficulty; it was never a statement about what a
# run costs, and one measured build run cost 78M tokens on either model.
DEFAULT_CHEAP = ["gate"]

# Percent of the five-hour window spent before a new fan-out is a bad bet. An
# agent cut off mid-run is not a partial result, it is no result.
BUDGET_SPENT = 75

# How old the status line's reading may be and still mean anything. It renders
# on every keystroke of a live session, so anything older than this is from a
# session that has ended - possibly before the window reset.
BUDGET_FRESH = 300

# In bypass-permissions mode a file is read with `cat` or `sed -n` through Bash
# rather than through the Read tool, so a counter that only watches Read counts
# zero on the session that read forty files. Same class of blind spot as the one
# _ctx.py already fixes for writes, and it made the fan-out brake below dead in
# exactly the mode this project runs in.
BASH_READ = re.compile(r"(?:^|[|;&]\s*)\s*(?:cat|bat|head|tail|sed|less)\s")

# `cat > file <<EOF` and `sed -i` open the same commands and are writes. What
# makes a read expensive is the content landing in this window, so a command
# whose output goes somewhere else is not one.
BASH_NOT_READ = re.compile(r"\bsed\s+-i\b")

# A redirect to a real file means the output is already being kept out of the
# session, which is the whole point of the wrapper. `2>/dev/null` and `>&2` are
# not that, and a bare `>` test let a gate through.
KEPT = re.compile(r">>?\s*(?!/dev/)[\w./~-]+")

# The gates, the force switches and the extra refusals all come out of the
# project's own `.claude/gates.json` - see that file's header. This hook held
# its own copy of the three, in its own words, at first: a third
# place for one list to drift, and the reason a guard could not be shared
# between projects.
_CFG: dict = {}


def _shape_problems(cfg: dict) -> list:
    """What is wrong with a config that parsed. A regex that does not compile
    and a tier with no name both read, at a glance, like a working file."""
    problems = []
    tiers = cfg.get("tiers", [])
    if not isinstance(tiers, list):
        return [f"has a `tiers` that is {type(tiers).__name__}, not a list"]
    for i, tier in enumerate(tiers):
        where = f"tier {i}"
        if not isinstance(tier, dict):
            problems.append(f"{where} is not an object")
            continue
        name = tier.get("name")
        if not isinstance(name, str) or not name:
            problems.append(f"{where} has no name")
            continue
        patterns = tier.get("guard", [])
        if not isinstance(patterns, list):
            problems.append(f"tier `{name}` has a `guard` that is not a list")
            continue
        for pattern in patterns:
            try:
                re.compile(pattern)
            except (re.error, TypeError) as exc:
                problems.append(f"tier `{name}` has an unusable guard pattern: {exc}")
    rules = cfg.get("deny", [])
    if not isinstance(rules, list):
        problems.append("has a `deny` that is not a list")
    else:
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict) or "match" not in rule or "say" not in rule:
                problems.append(f"deny rule {i} needs a `match` and a `say`")
                continue
            try:
                re.compile(rule["match"])
            except (re.error, TypeError) as exc:
                problems.append(f"deny rule {i} has an unusable pattern: {exc}")
    if not isinstance(cfg.get("force_env", []), list):
        problems.append("has a `force_env` that is not a list")
    return problems


def gates(project: str) -> dict:
    """`.claude/gates.json`, read once per process.

    **Three outcomes, and the middle one is why this is not four lines.** The
    file is absent, which means this project declares no gates and silence is
    the right answer. It is present and usable. Or it is present and wrong -
    unparseable, or parsed but shaped in a way nothing can be read out of.

    At first the third was treated as the first: a broken config
    and no config both produced an empty tier list, and the guard went on
    saying nothing while refusing nothing. That is the one failure a guard
    cannot have, because everything downstream looks exactly the same as a
    clean run. `bin/gate` has always told the two apart; now so does this.
    """
    if _CFG:
        return _CFG
    path = os.path.join(project, ".claude", "gates.json")
    problems, raw = [], {}
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        raw = {}
    except OSError as exc:
        problems.append(f"cannot be read: {exc.strerror or exc}")
    except json.JSONDecodeError as exc:
        problems.append(f"is not valid JSON: {exc}")
    if not isinstance(raw, dict):
        problems.append(f"is {type(raw).__name__} at the top level, not an object")
        raw = {}

    _CFG.update(raw)
    _CFG["tiers"] = raw.get("tiers", [])
    problems += _shape_problems(_CFG)
    if problems:
        # Guarding on half a list is worse than saying so: a tier that parsed
        # would be enforced and the one that did not would be silently absent.
        _CFG["tiers"], _CFG["deny"] = [], []
    _CFG["problems"] = problems
    return _CFG


def deny(reason: str) -> int:
    print(reason, file=sys.stderr)
    return 2


def bump_reads(state: dict) -> int:
    """One counter for both ways a file gets read. Fires once, then gets out of
    the way - a guard that keeps refusing is a guard that gets switched off.

    `agents.py` zeroes this on every subagent spawn, and that is deliberate
    rather than a leak: the brake exists to push an investigation out of the
    main window, so the moment the session actually delegates it has done the
    thing being asked and the budget starts again. It also repairs the one case
    this counter gets wrong - a subagent shares its parent's `session_id` and
    writes to the same state file, so before the reset a subagent inherited a
    read budget the parent had already spent. A reviewer was refused its third
    read that way and told to delegate, which it is not
    allowed to do."""
    n = state.get("reads", 0) + 1
    state["reads"] = n
    if n >= READ_FANOUT and "fanout" not in state.setdefault("said", []):
        state["said"].append("fanout")
        return deny(
            f"{n} files read since the last delegation. If this is an "
            "investigation rather than an edit, send it to a subagent - it burns "
            "its own window and returns the conclusion. Repeat the call if this "
            "read is the edit, or if you are already a subagent: the count is "
            "per session id and a subagent shares its parent's."
        )
    return 0


def check_bash(cmd: str, project: str, state: dict) -> int:
    # Counted before anything below can return early: a read is a read whether
    # or not the command also redirects.
    if BASH_READ.search(cmd) and not (KEPT.search(cmd) or BASH_NOT_READ.search(cmd)):
        code = bump_reads(state)
        if code:
            return code

    cfg = gates(project)
    # A guard that cannot read its own config says so, once, and then gets out
    # of the way - the same shape as the read brake below, and for the same
    # reason. Blocking every command would also block the ones that fix the
    # file; saying nothing is what this bug was.
    if cfg["problems"] and "gates" not in state.setdefault("said", []):
        state["said"].append("gates")
        return deny(
            ".claude/gates.json " + "; ".join(cfg["problems"]) + ".\n"
            "Until it parses, no gate command is being refused in this project "
            "- which is why you are being told rather than left to find out. "
            "Fix the file, or repeat this call to carry on without it."
        )

    # An explicit redirect to a file, or the wrapper itself, means the output is
    # already being kept out of the way.
    forced = any(name in cmd for name in cfg.get("force_env", []))
    if "bin/gate" in cmd or forced or KEPT.search(cmd):
        return 0

    for tier in cfg["tiers"]:
        for pattern in tier.get("guard", []):
            if re.search(pattern, cmd):
                return deny(
                    f"That gate prints thousands of lines straight into this "
                    f"session. Run `bin/gate {tier['name']}` instead: the full log "
                    f"goes to .gate-logs/ and you get the verdict. Read the failing "
                    f"part with `sed -n` on the log."
                )
    for rule in cfg.get("deny", []):
        if re.search(rule["match"], cmd):
            return deny(rule["say"])

    m = re.match(r"\s*cat\s+([^\s|;&<>]+)\s*$", cmd)
    if m:
        path = m.group(1).strip("\"'")
        full = path if os.path.isabs(path) else os.path.join(project, path)
        try:
            with open(full, errors="replace") as fh:
                n = sum(1 for _ in fh)
        except OSError:
            return 0
        if n > BIG_FILE_LINES:
            seen = state.setdefault("big_cat", [])
            if path not in seen:
                seen.append(path)
                return deny(
                    f"`{path}` is {n} lines. Read the part you need - "
                    f"`sed -n '1,80p' {path}`, or grep to the symbol first. Repeat "
                    f"this exact command if you really do want all of it."
                )
    return 0


def check_read(state: dict) -> int:
    return bump_reads(state)


# The delegation checks keep their own state file, and that is not tidiness.
# `agents.py` matches the same three tools and writes `<session>.json` too, and
# hooks for one event run in parallel: two `load_state`/`save_state` pairs over
# one non-atomic whole-file write means whichever lands last silently discards
# the other. That would have cost either the round cap or the read-budget reset
# depending on the day. Nothing else writes this file.
def _gstate(project: str, session: str) -> str:
    d = os.path.join(project, ".claude", ".state")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{session or 'unknown'}-agents.json")


def load_gstate(project: str, session: str) -> dict:
    try:
        with open(_gstate(project, session)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_gstate(project: str, session: str, state: dict) -> None:
    try:
        with open(_gstate(project, session), "w") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def check_round(args: dict, g: dict) -> int:
    """The cap on messages to one live agent."""
    target = args.get("to") or "?"
    # A subagent reporting back addresses the parent, and it shares the
    # parent's session id, so without this its second report is refused as a
    # round and told to spawn a new `main` off the brief.
    if target in ("main", "parent"):
        return 0
    # The slot a round is counted in. A bare name is reused by every agent
    # spawned under it, so the generation `check_spawn` bumps is what keeps one
    # agent's rounds off the next one's counter. An id - what a background
    # agent is addressed by, and what every real round row in the ledger holds -
    # has no generation and keys exactly.
    slot = f"{target}#{g.get('gen', {}).get(target, 0)}"
    rounds = g.setdefault("rounds", {})
    # **Counted only when it is let through.** Incrementing on the refused
    # attempt made the stored count read double and the message name a round
    # number that had never been sent - "Round 4" on the third one delivered.
    n = rounds.get(slot, 0) + 1
    if n <= ROUND_CAP:
        rounds[slot] = n
        return 0
    # Refuse once, then let the repeat through and **re-arm**. Leaving the
    # marker in place made this a one-time speed bump: round two was refused
    # and rounds three onward passed in silence, which is not a cap.
    key = f"round:{slot}"
    said = g.setdefault("said", [])
    if key in said:
        said.remove(key)
        rounds[slot] = n
        return 0
    said.append(key)
    return deny(
        f"Round {n} to `{target}`. A round re-sends everything that agent has "
        f"accumulated, and its transcript is already the expensive thing - a "
        f"measured run carries 150-350k per request, against a 48k cold start. "
        f"Append what this round established to the job's BRIEF.md under "
        f"`## Derived` and spawn a new `{target}` off it: it starts with the "
        f"conclusions and none of the transcript. Repeat this call if the "
        f"agent is mid-task and a respawn would lose real state."
    )


def five_hour_spent(project: str) -> int:
    """How much of the five-hour window has gone, as the status line last saw
    it. The figure is only in the status line's payload - no hook is handed it -
    so `statusline-extra.py` leaves it in `.claude/.state/budget.json` on the
    way past.

    **A figure is only worth reading while it is fresh.** The status line
    renders only while a session is open, so between sessions the file keeps
    whatever it last held - which on the day this was written for is the high
    number - and it would go on refusing spawns into a window that had since
    reset. Older than a few minutes is treated as no reading at all, which
    lets the spawn through: this brake may cost a repeat, never a wrong stop."""
    try:
        with open(os.path.join(project, ".claude", ".state", "budget.json")) as fh:
            got = json.load(fh)
        if time.time() - float(got.get("at") or 0) > BUDGET_FRESH:
            return 0
        return int(got.get("five_hour") or 0)
    except (OSError, ValueError, TypeError):
        return 0


def check_spawn(project: str, args: dict, g: dict) -> int:
    # A spawn is a new agent under that name, so the round count that belonged
    # to the last one is not this one's. Without this the cap is once per name
    # per session rather than once per agent, and the respawn it just asked for
    # arrives already over the line.
    #
    # **Bumping a generation, not deleting the counter.** Deleting it reset the
    # count for *every* agent of that name, so spawning a second `digger` while
    # the first was live handed the first a fresh allowance - three were live at
    # once in one session. A generation orphans the old counter instead.
    #
    # The residual case is named rather than papered over: two live agents of
    # one name, both addressed by that name, are still one slot. `SendMessage`
    # to an **id** keys exactly and is the way out of it.
    # Both, because `SendMessage` addresses whatever the agent answers to: the
    # type when nothing else was given, its own `name` when one was, and an id
    # for a background agent. Bumping only the type left a named agent
    # inheriting the previous one's counter, which is the case the generation
    # exists for.
    name = args.get("subagent_type") or ""
    gen = g.setdefault("gen", {})
    for key in (name, args.get("name") or ""):
        if key:
            gen[key] = gen.get(key, 0) + 1

    # The cheap agents exist to be run freely; refusing a `gate` on a spent
    # window costs a repeat and buys nothing. What this is protecting is an
    # expensive agent cut off half way - and that is a question about the
    # agent, not about its model.
    cheap = gates(project).get("cheap_agents", DEFAULT_CHEAP)
    if isinstance(cheap, list) and name in cheap:
        return 0

    spent = five_hour_spent(project)
    if spent < BUDGET_SPENT or "budget" in g.setdefault("said", []):
        return 0
    g["said"].append("budget")
    return deny(
        f"{spent}% of the five-hour window is gone, and `{name or 'this'}` is "
        f"not a cheap one. An agent cut off mid-run has to be bought again from "
        f"cold - that has happened. Finish and commit "
        f"what is open rather than opening a fan-out, or repeat this call if "
        f"this one agent is the thing that closes the unit."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    session = payload.get("session_id", "")
    tool = payload.get("tool_name", "")
    args = payload.get("tool_input") or {}

    # Two stores, and only one of them is touched per event. The read budget
    # lives in the file `agents.py` also writes; the delegation counters live
    # in a file nothing else opens. Saving both here would put this hook back
    # in the race the second store exists to avoid.
    if tool in ("Bash", "Read"):
        state = load_state(project, session)
        if tool == "Bash":
            code = check_bash(args.get("command", ""), project, state)
        else:
            code = check_read(state)
        save_state(project, session, state)
        return code

    if tool in ("SendMessage", "Task", "Agent"):
        g = load_gstate(project, session)
        if tool == "SendMessage":
            code = check_round(args, g)
        else:
            code = check_spawn(project, args, g)
        save_gstate(project, session, g)
        return code

    return 0


if __name__ == "__main__":
    # Session hygiene must never be the thing that stops the work. Anything
    # unexpected in here exits clean: the tool runs, the turn ends, the status
    # line just goes quiet.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see above
        # Clean exit, but not a silent one. A hook that fails without a word is
        # a hook nobody knows has stopped working, which is the same class of
        # bug as a guard that stops guarding on a broken config.
        print(f"guard.py: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
