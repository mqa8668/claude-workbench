"""Every hook, run from the package the way Claude Code will run it: from the
plugin directory, told where the project is. A hook that resolves anything
relative to itself rather than to the project fails here."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, hook, repo, run_tests  # noqa: E402


def payload(project, **extra):
    transcript = os.path.join(project, "transcript.jsonl")
    if not os.path.exists(transcript):
        with open(transcript, "w") as fh:
            fh.write(
                json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n"
            )
    base = {
        "session_id": "hooks-test",
        "cwd": project,
        "transcript_path": transcript,
        "workspace": {"project_dir": project, "current_dir": project},
        "model": {"id": "claude-opus-5"},
        "scratchpad_dir": project,
    }
    base.update(extra)
    return base


EVENTS = [
    ("resume.py", {"hook_event_name": "SessionStart", "source": "startup"}),
    ("prompt.py", {"hook_event_name": "UserPromptSubmit", "prompt": "do a thing"}),
    (
        "guard.py",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        },
    ),
    (
        "agents.py",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": "digger", "description": "d", "prompt": "find it"},
        },
    ),
    ("checkpoint.py", {"hook_event_name": "Stop"}),
    ("subagent.py", {"hook_event_name": "SubagentStop"}),
]


def test_every_hook_runs_without_crashing():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    for name, extra in EVENTS:
        r = hook(name, payload(p, **extra), p)
        check("Traceback" not in r.stderr, f"{name}: {r.stderr.strip()[-200:]}")
        check(r.returncode in (0, 2), f"{name}: exit {r.returncode}")
    return p


def test_the_checkpoint_is_written_into_the_project():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    hook("checkpoint.py", payload(p, hook_event_name="Stop"), p)
    path = os.path.join(p, ".claude", "session.md")
    check(os.path.exists(path), "no .claude/session.md in the project")
    with open(path) as fh:
        check(fh.read().strip() != "", "the checkpoint is empty")
    return p


def test_the_checkpoint_is_read_back_at_session_start():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    hook("checkpoint.py", payload(p, hook_event_name="Stop"), p)
    r = hook("resume.py", payload(p, hook_event_name="SessionStart", source="startup"), p)
    check(r.returncode == 0, r.stderr[:200])
    check(r.stdout.strip() != "", "SessionStart handed nothing back")
    return p


def test_a_spawn_is_written_to_the_ledger():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    hook(
        "agents.py",
        payload(
            p,
            hook_event_name="PreToolUse",
            tool_name="Agent",
            tool_input={"subagent_type": "digger", "description": "d", "prompt": "find it"},
        ),
        p,
    )
    path = os.path.join(p, ".claude", ".state", "agents.jsonl")
    check(os.path.exists(path), "no ledger written")
    with open(path) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    check(rows, "the ledger is empty")
    check(
        any("digger" in json.dumps(row) for row in rows), f"the spawn is not in the ledger: {rows}"
    )
    return p


def test_nothing_is_written_outside_the_project():
    """A hook that wrote next to itself would put one project's state in the
    package, and every other project would then read it."""
    package = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    before = {os.path.join(r, f) for r, _, fs in os.walk(package) for f in fs}
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    for name, extra in EVENTS:
        hook(name, payload(p, **extra), p)
    after = {os.path.join(r, f) for r, _, fs in os.walk(package) for f in fs}
    new = {f for f in after - before if "__pycache__" not in f}
    check(not new, f"the package was written into: {sorted(new)}")
    return p


if __name__ == "__main__":
    print("hooks/*.py")
    sys.exit(run_tests(sys.modules[__name__]))
