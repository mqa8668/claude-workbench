"""The guard, against a repository's own declared gates rather than any
hard-coded list. This is the check that would have caught the guard refusing
one project's commands inside another project."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import check, hook, repo, run_tests  # noqa: E402

GATES = {
    "force_env": ["GATE_FORCE", "CI_GATE_FORCE"],
    "tiers": [
        {"name": "web", "cmd": "npm run build", "guard": [r"\bnpm\s+run\s+build\b"]},
        {"name": "api", "cmd": "mix precommit", "guard": [r"\bmix\s+precommit\b"]},
    ],
    "deny": [
        {
            "match": r"\bmix\s+test\b(?![^&|]*(test/\S+|\S+\.exs))",
            "say": "A bare suite. Name the file.",
        }
    ],
}


def guard(project, command):
    return hook(
        "guard.py",
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "session_id": "guard-test",
            "cwd": project,
        },
        project,
    )


def test_a_declared_gate_command_is_refused_and_names_its_tier():
    p = repo(GATES)
    for command, tier in (("npm run build", "web"), ("cd api && mix precommit", "api")):
        r = guard(p, command)
        check(r.returncode == 2, f"{command!r} was allowed")
        check(f"bin/gate {tier}" in r.stderr, f"{command!r} -> {r.stderr[:120]}")
    return p


def test_the_wrapper_itself_is_allowed():
    p = repo(GATES)
    check(guard(p, "bin/gate web").returncode == 0, "the wrapper was refused")
    return p


def test_either_force_switch_is_allowed():
    p = repo(GATES)
    for command in ("GATE_FORCE=1 bin/gate api", "CI_GATE_FORCE=1 bin/gate api"):
        check(guard(p, command).returncode == 0, f"{command!r} was refused")
    return p


def test_a_deny_rule_fires_and_its_exception_holds():
    p = repo(GATES)
    r = guard(p, "mix test")
    check(r.returncode == 2, "the bare suite was allowed")
    check("Name the file." in r.stderr, r.stderr)
    check(
        guard(p, "mix test test/thing_test.exs").returncode == 0,
        "a named file was refused - this is the regression that matters",
    )
    return p


def test_a_gate_command_with_its_output_redirected_is_allowed():
    p = repo(GATES)
    check(
        guard(p, "npm run build > /tmp/wb-build.log").returncode == 0,
        "output kept out of the session was still refused",
    )
    return p


def test_an_unrelated_command_is_allowed():
    p = repo(GATES)
    for command in ("git status", "ls -la", "python3 -c 'print(1)'"):
        check(guard(p, command).returncode == 0, f"{command!r} was refused")
    return p


def test_another_repos_gates_do_not_leak_into_this_one():
    """The whole point of reading the project's file: a command that is a gate
    somewhere else is an ordinary command here."""
    p = repo({"tiers": [{"name": "unit", "cmd": "cargo test", "guard": [r"\bcargo\s+test\b"]}]})
    check(
        guard(p, "npm run build").returncode == 0,
        "a foreign project's gate command was refused here",
    )
    check(guard(p, "cargo test").returncode == 2, "this repo's own gate was allowed")
    return p


def test_a_repo_with_no_gates_json_still_runs():
    p = repo(None)
    r = guard(p, "npm run build")
    check("Traceback" not in r.stderr, r.stderr)
    check(r.returncode == 0, "a repo that declares no gates refused a command")
    return p


def test_a_broken_config_is_said_out_loud_once():
    """The bug a review pass found: a broken file was treated
    exactly like an absent one, so the guard stopped refusing anything and said
    nothing about it. Everything downstream looked like a clean run."""
    p = repo(GATES)
    with open(os.path.join(p, ".claude", "gates.json"), "w") as fh:
        fh.write("{ not json")

    first = guard(p, "git status")
    check(first.returncode == 2, "a broken config was passed over in silence")
    check("gates.json" in first.stderr, first.stderr)
    check("not valid JSON" in first.stderr, first.stderr)
    check("Traceback" not in first.stderr, first.stderr)

    second = guard(p, "git status")
    check(
        second.returncode == 0,
        "the guard kept refusing - it is meant to say it once and get out of the way",
    )
    return p


def test_a_config_that_parses_but_cannot_be_used_is_also_said():
    """A regex that does not compile and a tier with no name both read, at a
    glance, like a working file."""
    broken = [
        ({"tiers": None}, "not a list"),
        ({"tiers": [{"cmd": "true"}]}, "no name"),
        ({"tiers": [{"name": "web", "cmd": "true", "guard": ["(unclosed"]}]}, "unusable"),
        (
            {
                "tiers": [{"name": "web", "cmd": "true"}],
                "deny": [{"match": "(also unclosed", "say": "no"}],
            },
            "unusable",
        ),
        ({"tiers": [{"name": "web", "cmd": "true"}], "force_env": "GATE_FORCE"}, "not a list"),
    ]
    last = None
    for gates_json, expected in broken:
        last = repo(gates_json)
        r = guard(last, "git status")
        check(r.returncode == 2, f"{gates_json} was passed over in silence")
        check(expected in r.stderr, f"{gates_json} -> {r.stderr.strip()[:160]}")
    return last


def test_a_broken_config_does_not_guard_on_half_a_list():
    """One tier readable and one not is not a config to enforce: the readable
    half would be refused and the other half would be silently absent."""
    p = repo(
        {
            "tiers": [
                {"name": "web", "cmd": "npm run build", "guard": [r"\bnpm\s+run\s+build\b"]},
                {"name": "broken", "cmd": "true", "guard": ["(unclosed"]},
            ]
        }
    )
    check(guard(p, "git status").returncode == 2, "the breakage was not reported")
    r = guard(p, "npm run build")
    check(
        r.returncode == 0,
        "a tier was enforced out of a config the guard had already called unusable",
    )
    return p


def test_the_read_brake_is_not_tripped_by_one_read():
    p = repo(GATES)
    r = guard(p, "cat README.md")
    check(r.returncode == 0, "a single read was refused")
    return p


if __name__ == "__main__":
    print("hooks/guard.py")
    sys.exit(run_tests(sys.modules[__name__]))
