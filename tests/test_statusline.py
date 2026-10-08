"""The status line host: it must print a line on stock Claude Code, with or
without a gates.json, and it must leave the five-hour figure where the guard
looks for it."""

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import ROOT, check, hook, repo, run_tests  # noqa: E402

HOST = os.path.join(ROOT, "statusline", "statusline.py")


def render(project, payload):
    return subprocess.run(
        [sys.executable, HOST],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ, NO_COLOR="1"),
    )


def payload(project, **extra):
    base = {
        "workspace": {"project_dir": project, "current_dir": project},
        "model": {"display_name": "Opus"},
    }
    base.update(extra)
    return base


def test_it_prints_a_line_with_no_config():
    p = repo()
    r = render(p, payload(p))
    check("Traceback" not in r.stderr, r.stderr[-200:])
    check(r.returncode == 0, f"exit {r.returncode}")
    check(r.stdout.strip() != "", "an empty line")
    check("Opus" in r.stdout, r.stdout)
    return p


def test_it_prints_a_line_on_garbage_input():
    p = repo()
    r = subprocess.run(
        [sys.executable, HOST], input="not json", capture_output=True, text=True, cwd=p
    )
    check("Traceback" not in r.stderr and r.returncode == 0, r.stderr[-200:])
    check(r.stdout.strip() != "", "an empty line")
    return p


def test_a_passing_gate_shows_up_in_the_line():
    p = repo(
        {"tiers": [{"name": "unit", "cmd": "true", "watch": ["src/"]}]},
        install_gate=True,
    )
    subprocess.run([sys.executable, os.path.join(p, "bin", "gate")], cwd=p, capture_output=True)
    r = render(p, payload(p))
    check("gate" in r.stdout, f"no gate segment: {r.stdout!r}")
    return p


def test_the_five_hour_figure_is_left_for_the_guard():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    r = render(p, payload(p, rate_limits={"five_hour": {"used_percentage": 80}}))
    check("5h 80%" in r.stdout, r.stdout)
    with open(os.path.join(p, ".claude", ".state", "budget.json")) as fh:
        check(json.load(fh)["five_hour"] == 80, "budget.json holds the wrong figure")
    return p


def spawn(project, name):
    return hook(
        "guard.py",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"subagent_type": name, "description": "d", "prompt": "p"},
            "session_id": f"cheap-{name}",
            "cwd": project,
        },
        project,
    )


def test_a_spent_window_refuses_an_expensive_agent_and_passes_a_cheap_one():
    p = repo({"cheap_agents": ["gate", "lint"], "tiers": [{"name": "unit", "cmd": "true"}]})
    render(p, payload(p, rate_limits={"five_hour": {"used_percentage": 90}}))
    check(spawn(p, "digger").returncode == 2, "an expensive agent was allowed")
    check(spawn(p, "lint").returncode == 0, "a configured cheap agent was refused")
    q = repo({"tiers": [{"name": "unit", "cmd": "true"}]})
    render(q, payload(q, rate_limits={"five_hour": {"used_percentage": 90}}))
    check(spawn(q, "gate").returncode == 0, "the default cheap agent was refused")
    check(spawn(q, "lint").returncode == 2, "an unlisted agent was allowed")
    shutil.rmtree(q, ignore_errors=True)
    return p


if __name__ == "__main__":
    print("the status line host")
    sys.exit(run_tests(sys.modules[__name__]))
