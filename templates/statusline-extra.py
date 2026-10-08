"""The workbench's segments for a status line.

Claude Code does not call this file itself. `statusline/statusline.py` (the host
that ships with this plugin) imports it, hands over the status payload and a
small colour table, and prints what comes back. Any other status line script
can do the same: import this module and call `segments(payload, c)`.

What it adds:

    5173 5432               which of the project's ports are answering
    gate 12m  e2e 3h        when each verdict last said yes
    gate stale              ...and whether anything has been written since
    deploy 1a2b3c4          what the live site is running, if the project
                            has a .claude/hooks/deploy-probe.py
    2 agents  digger 4m     which subagents are out, and on what

**The ports and the checks come from `.claude/gates.json`**, the same file
`bin/gate` and `guard.py` read, so adding a tier shows up here without anyone
remembering a tuple in a hook. Everything below the checks is optional and
disappears quietly when the project has nothing to report.
"""

import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime

# What the ports are and what the checks are both come out of the project's
# own `.claude/gates.json` - the same file `bin/gate` and `guard.py` read. Three
# copies of one list is three chances to drift, and it was this file's copy that
# would have gone stale first: a tier added to the gate runner still shows
# nothing here until somebody remembers this tuple.
_CFG: dict = {}


def _cfg(project: str) -> dict:
    if not _CFG:
        try:
            with open(os.path.join(project, ".claude", "gates.json")) as fh:
                _CFG.update(json.load(fh))
        except (OSError, json.JSONDecodeError):
            pass
        _CFG.setdefault("tiers", [])
    return _CFG


def _ports(project: str) -> tuple:
    """Port, label, glyph - what the status line watches for a dev stack."""
    return tuple(tuple(row) for row in _cfg(project).get("ports", ()))


def _watched(project: str) -> tuple:
    """A verdict, its kind, and which directories can make it stale. A tier is
    a gate `bin/gate` runs; a check is one a person runs by hand and that still
    leaves a verdict behind - a browser test suite, say. A shared directory
    can age several tiers at once, and that is said in `gates.json` rather than
    here."""
    cfg = _cfg(project)
    rows = [(t["name"], "gate", tuple(t.get("watch", ()))) for t in cfg["tiers"]]
    rows += [(c["name"], "check", tuple(c.get("watch", ()))) for c in cfg.get("checks", ())]
    return tuple(rows)


PROBE_EVERY = 300  # the deploy probe, at most once every five minutes

# How long a subagent's transcript may sit untouched before the line stops
# calling it running. `subagent.py` is what normally ends an agent; this is the
# backstop for the one it cannot see - an agent the user stopped, which never
# reaches `SubagentStop`. Twenty minutes because the longest single tool call
# here is a ten-minute test run, and a transcript writes
# nothing while one is in flight.
STALE_AGENT = 1200


def _listening(port: int) -> bool:
    sock = socket.socket()
    sock.settimeout(0.05)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _clock(seconds: float) -> str:
    """`3d11h`, `2h04m`, `41m`, `12s`. The seconds matter because an agent
    forty seconds out would otherwise read `0m`, which is a duration nobody
    has ever had."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    h, m = divmod(seconds // 60, 60)
    if h >= 48:
        return f"{h // 24}d{h % 24:02d}h"
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _newest(changed: list, prefixes: tuple, project: str) -> float:
    """When anything under those directories was last written. `changed` is
    git's own list of what is not committed, so this is a handful of stats
    rather than a walk of the tree."""
    newest = 0.0
    for path in changed:
        rel = os.path.relpath(path, project)
        if not rel.startswith(prefixes):
            continue
        try:
            newest = max(newest, os.path.getmtime(path))
        except OSError:
            continue
    return newest


def _dev(project: str, c: dict) -> str:
    """A port that answers wears its own colour; one that does not wears the
    same faint grey as everything else that is not running. Green here means
    up, and it is allowed to mean nothing else."""
    glyph = c["glyph"]
    marks = [(label, icon, _listening(port)) for port, label, icon in _ports(project)]
    if not any(up for _, _, up in marks):
        return ""
    # The glyph is the label where the host has glyphs: printing the port
    # numbers as well would repeat what the icon already says. With glyphs off
    # the numbers come back.
    out = []
    for label, icon, up in marks:
        mark = glyph(icon, "", mono="" if up else c["faint"])
        out.append(mark or f"{c['green'] if up else c['faint']}{label}{c['off']}")
    return " ".join(out)


def _checks(project: str, changed: list, c: dict) -> str:
    """The gates and the manual checks, as one segment: what passed, how long ago,
    and whether anything has been written since."""
    gates, check, failed = [], "", []
    for tier, kind, prefixes in _watched(project):
        path = os.path.join(project, ".gate-logs", f"{tier}.verdict")
        try:
            with open(path) as fh:
                said = fh.read().strip()
            stamp = os.path.getmtime(path)
        except OSError:
            continue
        if said != "PASS":
            if kind == "gate":
                failed.append(tier)
            else:
                check = f"{c['red']}{c['bold']}{tier} ✗{c['off']}"
            continue
        stale = _newest(changed, prefixes, project) > stamp
        if kind == "gate":
            gates.append((tier, stamp, stale))
        else:
            tick = c["glyph"](tier, "", mono=c["yellow"] if stale else "")
            check = (
                f"{c['dim']}{tier}{c['off']} {tick}{c['yellow']}stale{c['off']}"
                if stale
                else f"{c['dim']}{tier}{c['off']} {tick}{c['faint']}{_clock(time.time() - stamp)}{c['off']}"
            )

    parts = []
    if failed:
        parts.append(f"{c['red']}{c['bold']}gate {' '.join(t + '✗' for t in failed)}{c['off']}")
    elif gates:
        oldest = min(stamp for _, stamp, _ in gates)
        stale = any(s for _, _, s in gates)
        tick = c["glyph"]("gate", "", mono=c["yellow"] if stale else "")
        parts.append(
            f"{c['dim']}gate{c['off']} {tick}{c['yellow']}stale{c['off']}"
            if stale
            else f"{c['dim']}gate{c['off']} {tick}{c['faint']}{_clock(time.time() - oldest)}{c['off']}"
        )
    if check:
        parts.append(check)
    return "  ".join(parts)


def _local_main(project: str) -> str:
    """`main` as this clone holds it, read from the ref rather than asked of git:
    the status line runs on every keystroke, so the question is deliberately
    about the local branch."""
    try:
        with open(os.path.join(project, ".git", "refs", "heads", "main")) as fh:
            return fh.read().strip()
    except OSError:
        pass
    try:
        with open(os.path.join(project, ".git", "packed-refs")) as fh:
            for line in fh:
                if line.rstrip().endswith(" refs/heads/main"):
                    return line.split()[0]
    except OSError:
        pass
    return ""


def _refresh_deploy(project: str) -> None:
    """Spawn the probe detached when the answer is stale. It never blocks: the
    status line reads the last answer, not this one."""
    state = os.path.join(project, ".claude", ".state")
    answer = os.path.join(state, "deploy.json")
    lock = os.path.join(state, "deploy.lock")
    now = time.time()
    try:
        if now - os.path.getmtime(answer) < PROBE_EVERY:
            return
    except OSError:
        pass
    try:
        os.makedirs(state, exist_ok=True)
        if os.path.exists(lock) and now - os.path.getmtime(lock) < 60:
            return  # one already went out; do not send a second
        probe = os.path.join(project, ".claude", "hooks", "deploy-probe.py")
        if not os.path.exists(probe):
            return  # a project without a probe has no deploy segment
        with open(lock, "w") as fh:
            fh.write(str(now))
        subprocess.Popen(
            [sys.executable, probe],
            cwd=project,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return


def _deploy(project: str, c: dict) -> str:
    """What is actually deployed, and only when that is news.

    Silent while production holds the commit this clone is on - which is the
    normal state and needs no column. It speaks when the two have parted, and
    when the site cannot be reached at all.
    """
    _refresh_deploy(project)
    try:
        with open(os.path.join(project, ".claude", ".state", "deploy.json")) as fh:
            seen = json.load(fh)
    except (OSError, ValueError):
        return ""

    if time.time() - seen.get("ts", 0) > 1800:
        return ""  # too old to be about now; the probe will have gone out again

    glyph = c["glyph"]
    if seen.get("status") == "down":
        return glyph("deploy", then=c["red"], mono=c["red"]) + f"{c['red']}site down{c['off']}"

    revision = seen.get("revision")
    if not revision:
        return ""  # up, and cannot say what it is - see the probe's own note

    local = _local_main(project)
    if local and revision[:7] == local[:7]:
        return ""
    return glyph("deploy", mono=c["yellow"]) + f"{c['yellow']}{revision[:7]}{c['off']}"


def _spawned(project: str, session: str) -> tuple:
    """The delegation ledger, read back as `(spawns, rounds)` for this session.

    The two are counted apart because they are different costs and only one of
    them is visible anywhere else. A spawn is a name in `/tasks`; a round is a
    message that re-sends an agent's whole accumulated transcript and leaves no
    trace at all - which is how a day of heavy delegating showed
    a handful of lines here. Rows written before `kind` existed are spawns."""
    path = os.path.join(project, ".claude", ".state", "agents.jsonl")
    prefix = (session or "")[:8]
    if not prefix or not os.path.exists(path):
        return 0, 0
    spawns = rounds = 0
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("session") != prefix:
                    continue
                kind = row.get("kind", "spawn")
                if kind == "spawn":
                    spawns += 1
                elif kind == "round":
                    rounds += 1
    except OSError:
        return 0, 0
    return spawns, rounds


def _short_model(ident: str) -> str:
    """`claude-haiku-4-5-20251001` -> `haiku4.5`, `claude-opus-5[1m]` ->
    `opus5·1m`. The version digits come off the name segment by segment, so the
    build date on the end of a model id is dropped rather than concatenated."""
    ident = (ident or "").lower()
    wide = "·1m" if "[1m]" in ident else ""
    ident = ident.replace("[1m]", "")
    for family in ("opus", "sonnet", "haiku"):
        if family not in ident:
            continue
        digits = []
        for part in ident.split(family, 1)[1].split("-"):
            if part.isdigit() and len(part) <= 2:
                digits.append(part)
            elif part:
                break
        return family + ".".join(digits) + wide
    return (ident.rsplit("-", 1)[-1] or "?")[:10] + wide


def _effort_of(project: str, name: str, cache: dict) -> str:
    """The thinking level an agent runs at, read from its own definition.

    It is not in the transcript - effort is a request parameter, not something
    the response reports - so the honest source is the `effort:` line in
    `.claude/agents/<name>.md`, which is where that is decided. An agent
    with no definition file (the built-in ones) has no declared level and gets
    no word rather than a guessed one."""
    if name in cache:
        return cache[name]
    level = ""
    path = os.path.join(project, ".claude", "agents", f"{name}.md")
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if line.startswith("---") and level:
                    break
                if line.startswith("effort:"):
                    level = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    cache[name] = level
    return level


def _finished(project: str) -> dict:
    """When `subagent.py` last saw each agent stop.

    Not a set of ids: `SubagentStop` fires per response rather than per agent,
    so an agent that is continued with `SendMessage` is written here at the end
    of round one and then goes back to work. Read as "gone for ever" that
    retires exactly the agents worth watching - the ones being sent rounds.
    The stamp makes it "stopped as of then", and the transcript's mtime says
    whether anything has happened since. Lines written before the stamp existed
    are bare ids and keep the old meaning."""
    path = os.path.join(project, ".claude", ".state", "subagents-done.txt")
    out: dict = {}
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                bits = line.split()
                if not bits:
                    continue
                try:
                    out[bits[0]] = float(bits[1])
                except (IndexError, ValueError):
                    out[bits[0]] = float("inf")
    except OSError:
        return {}
    return out


def _tail(path: str, cap: int = 65536) -> list:
    """The end of a transcript, without reading the transcript. A subagent's
    own log runs to megabytes and the status line renders on every keystroke,
    so this reads the last block and drops the line it landed in the middle
    of."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > cap:
                fh.seek(size - cap)
                fh.readline()
            return fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _running(project: str, scratchpad: str) -> list:
    """What is out there right now, from the subagents' own transcripts.

    One file per agent under the session's `tasks/`, and each assistant row in
    it carries the three things the status line payload does not know: which
    agent this is, **which model it actually got** - the frontmatter says what
    it asks for, a `model:` on the spawn overrides it, and only the response
    says what answered - and how much context it is holding.
    """
    if not scratchpad:
        return []  # an older Claude Code: no scratchpad, no tasks beside it
    tasks = os.path.join(os.path.dirname(scratchpad), "tasks")
    if not os.path.isdir(tasks):
        return []
    done = _finished(project)
    efforts: dict = {}
    out = []
    for entry in sorted(os.listdir(tasks)):
        if not entry.endswith(".output"):
            continue
        agent_id = entry[: -len(".output")]
        path = os.path.join(tasks, entry)
        try:
            touched = os.path.getmtime(path)
            if time.time() - touched > STALE_AGENT:
                continue
        except OSError:
            continue
        # Stopped, and nothing written since - as opposed to stopped at the end
        # of a round and now working again on the same transcript.
        if touched <= done.get(agent_id, 0):
            continue
        rows = _tail(path)
        last = None
        for line in reversed(rows):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("type") == "assistant" and (row.get("message") or {}).get("usage"):
                last = row
                break
        if last is None:
            continue  # opened, nothing said yet - it has no reading to show
        message = last["message"]
        if message.get("stop_reason") == "end_turn":
            continue  # stopped, and the hook has not written it down yet
        usage = message.get("usage") or {}
        started = 0.0
        try:
            with open(path, errors="replace") as fh:
                stamp = (json.loads(fh.readline()).get("timestamp") or "").replace("Z", "+00:00")
            started = datetime.fromisoformat(stamp).timestamp()
        except (OSError, ValueError, KeyError):
            pass
        name = last.get("attributionAgent") or "agent"
        out.append(
            {
                "name": name,
                "model": _short_model(message.get("model")),
                "effort": _effort_of(project, name, efforts),
                "ctx": (
                    (usage.get("input_tokens") or 0)
                    + (usage.get("cache_read_input_tokens") or 0)
                    + (usage.get("cache_creation_input_tokens") or 0)
                ),
                "age": time.time() - started if started else 0.0,
            }
        )
    return out


def _agents(project: str, payload: dict, c: dict) -> str:
    """Delegation, while it is happening.

    The count alone answered "how much went out" after the fact. What a person
    watching a fan-out actually wants is what each agent *is* - and the two
    facts that decide what it costs and what it is worth are the model and the
    thinking level, neither of which the name says. `planner` is opus at high
    effort and `gate` is haiku at low, and the whole argument for delegating is
    that difference.

        planner opus5 high 48k 3m       one out
        planner opus5 high 48k 3m · gate haiku4.5 low 12k 1m
        5 agents  3×opus5 high  2×haiku4.5 low  6m

    Past two it stops being a list and becomes a shape: how many, on what, and
    how long the oldest has been gone. Which agent is which is a question for
    `/tasks`, not for one line above the prompt. With nothing running it falls
    back to the session's own total, which is the segment this used to be.
    """
    glyph = c["glyph"]("subagents")
    live = _running(project, payload.get("scratchpad_dir") or "")

    def _one(a: dict, sep: str = " ") -> str:
        bits = f"{c['calm']}{a['name']}{c['off']}{sep}{c['dim']}{a['model']}{c['off']}"
        if a["effort"]:
            bits += f" {c['faint']}{a['effort']}{c['off']}"
        if a["ctx"]:
            bits += f" {c['faint']}{a['ctx'] / 1000:.0f}k{c['off']}"
        if a["age"]:
            bits += f" {c['faint']}{_clock(a['age'])}{c['off']}"
        return bits

    if 1 <= len(live) <= 2:
        return glyph + f"{c['faint']} · {c['off']}".join(_one(a) for a in live)

    if live:
        kinds: dict = {}
        for a in live:
            key = (a["model"], a["effort"])
            kinds[key] = kinds.get(key, 0) + 1
        ranked = sorted(kinds.items(), key=lambda kv: -kv[1])
        shape = "  ".join(
            f"{c['dim']}{str(n) + '×' if n > 1 else ''}{model}{c['off']}"
            + (f" {c['faint']}{effort}{c['off']}" if effort else "")
            for (model, effort), n in ranked[:3]
        )
        if len(ranked) > 3:
            shape += f"  {c['faint']}+{sum(n for _, n in ranked[3:])}{c['off']}"
        oldest = max(a["age"] for a in live)
        return (
            glyph
            + f"{c['calm']}{len(live)} agents{c['off']}  {shape}"
            + (f"  {c['faint']}{_clock(oldest)}{c['off']}" if oldest else "")
        )

    count, rounds = _spawned(project, payload.get("session_id", ""))
    if not count:
        return ""
    said = f"{count} agent{'s' if count > 1 else ''}"
    if rounds:
        said += f" {rounds} round{'s' if rounds > 1 else ''}"
    return glyph + f"{c['dim']}{said}{c['off']}"


def _stash_budget(project: str, payload: dict) -> None:
    """Leave the five-hour figure where a hook can find it.

    `guard.py` refuses to open a fan-out on a spent window, and it cannot ask:
    the rate limits are in the status line's payload and in no hook's. This is
    the only place both sides can see, and it is written on the way past rather
    than fetched, so it costs nothing. A file that fails to write reads as a
    fresh window and lets the spawn through, which is the right way round."""
    limits = (payload.get("rate_limits") or {}).get("five_hour") or {}
    pct = limits.get("used_percentage")
    if pct is None:
        return
    try:
        d = os.path.join(project, ".claude", ".state")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "budget.json"), "w") as fh:
            json.dump({"five_hour": int(pct), "at": int(time.time())}, fh)
    except (OSError, TypeError, ValueError):
        pass


def segments(payload: dict, c: dict) -> list:
    workspace = payload.get("workspace") or {}
    project = workspace.get("project_dir") or workspace.get("current_dir") or os.getcwd()
    changed = c.get("changed") or []
    _stash_budget(project, payload)
    return [
        _agents(project, payload, c),
        _checks(project, changed, c),
        _deploy(project, c),
        _dev(project, c),
    ]
