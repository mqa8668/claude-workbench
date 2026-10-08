"""The runner: what it runs, what it refuses, and what it leaves behind."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Port, check, free_port, gate, repo, run_tests  # noqa: E402


def verdict(project, tier):
    with open(os.path.join(project, ".gate-logs", f"{tier}.verdict")) as fh:
        return fh.read()


def test_a_passing_tier():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]}, install_gate=True)
    r = gate(p)
    check(r.returncode == 0, f"exit {r.returncode}, stderr={r.stderr[:200]}")
    check("unit" in r.stdout and "PASS" in r.stdout, r.stdout)
    check(verdict(p, "unit") == "PASS", verdict(p, "unit"))
    check("green." in r.stdout, r.stdout)
    return p


def test_a_failing_tier_prints_the_log_tail():
    p = repo({"tiers": [{"name": "unit", "cmd": "echo boom-line; exit 3"}]}, install_gate=True)
    r = gate(p)
    check(r.returncode == 1, f"exit {r.returncode}")
    check("FAIL" in r.stdout, r.stdout)
    check("boom-line" in r.stdout, "the tail of the log is not on stdout")
    check("full log:" in r.stdout, r.stdout)
    check(verdict(p, "unit") == "FAIL", verdict(p, "unit"))
    check("not green" in r.stdout, r.stdout)
    return p


def test_the_whole_log_goes_to_a_file_not_to_stdout():
    # A loop rather than 200 literal echoes: the command string itself must not
    # contain the line the assertion looks for, or the summary fallback - which
    # is the command - would fail this test on its own.
    noisy = "for i in $(seq 200); do echo line-$i; done"
    p = repo({"tiers": [{"name": "unit", "cmd": noisy}]}, install_gate=True)
    r = gate(p)
    check(r.returncode == 0, r.stdout)
    check("line-3" not in r.stdout, "a passing log reached stdout")
    check(
        len(max(r.stdout.splitlines(), key=len)) < 100,
        "the summary line is not readable beside a clock",
    )
    with open(os.path.join(p, ".gate-logs", "unit.log")) as fh:
        check(len(fh.read().splitlines()) == 200, "the log is not whole")
    return p


def test_summary_any_pass_fail_count_and_default():
    p = repo(
        {
            "tiers": [
                {
                    "name": "any",
                    "cmd": "echo '12 tests, 0 failures'",
                    "summary": {"any": ["[0-9]+ tests, [0-9]+ failures"], "default": "d"},
                },
                {
                    "name": "onpass",
                    "cmd": "echo 'built in 1.4s'",
                    "summary": {"pass": ["built in [0-9.]+s"], "fail": ["nope"], "default": "d"},
                },
                {
                    "name": "fallback",
                    "cmd": "echo nothing-matches",
                    "summary": {"any": ["will-not-match"], "default": "the default"},
                },
            ]
        },
        install_gate=True,
    )
    r = gate(p)
    check("12 tests, 0 failures" in r.stdout, r.stdout)
    check("built in 1.4s" in r.stdout, r.stdout)
    check("the default" in r.stdout, r.stdout)
    return p


def test_summary_count_reports_how_many():
    p = repo(
        {
            "tiers": [
                {
                    "name": "unit",
                    "cmd": "echo 'error TS1 error TS2'; exit 1",
                    "summary": {
                        "fail": {"count": "error TS", "as": "{n} type errors"},
                        "default": "d",
                    },
                }
            ]
        },
        install_gate=True,
    )
    r = gate(p)
    check("2 type errors" in r.stdout, r.stdout)
    return p


def test_env_and_dir_reach_the_command():
    p = repo(
        {
            "tiers": [
                {
                    "name": "unit",
                    "dir": "sub",
                    "cmd": "pwd; echo $WB_FLAG",
                    "env": {"WB_FLAG": "carried"},
                    "summary": {"any": ["carried"], "default": "d"},
                }
            ]
        },
        install_gate=True,
    )
    os.makedirs(os.path.join(p, "sub"))
    r = gate(p)
    check("carried" in r.stdout, r.stdout)
    with open(os.path.join(p, ".gate-logs", "unit.log")) as fh:
        check("/sub" in fh.read(), "the command did not run in `dir`")
    return p


def test_a_live_port_it_refuses_stops_the_gate():
    with Port() as port:
        p = repo(
            {
                "force_env": ["GATE_FORCE"],
                "tiers": [
                    {
                        "name": "unit",
                        "cmd": "true",
                        "refuses_port": [
                            {
                                "port": port,
                                "why": "something is live there.",
                                "hint": "stop it first",
                            }
                        ],
                    }
                ],
            },
            install_gate=True,
        )
        r = gate(p)
        check(r.returncode == 1, f"exit {r.returncode}")
        check("SKIP" in r.stdout and "something is live there." in r.stdout, r.stdout)
        check("stop it first" in r.stdout, "the hint is missing")
        check(verdict(p, "unit") == "SKIP", verdict(p, "unit"))

        forced = gate(p, env={"GATE_FORCE": "1"})
        check(forced.returncode == 0, "the force switch did not override")
        check("PASS" in forced.stdout, forced.stdout)
    return p


def test_a_dead_port_it_requires_stops_the_gate():
    port = free_port()
    p = repo(
        {
            "tiers": [
                {
                    "name": "unit",
                    "cmd": "true",
                    "requires_port": [
                        {"port": port, "why": "nothing answers there.", "hint": "start it"}
                    ],
                }
            ]
        },
        install_gate=True,
    )
    r = gate(p)
    check("SKIP" in r.stdout and "nothing answers there." in r.stdout, r.stdout)
    check(r.returncode == 1, f"exit {r.returncode}")
    return p


def test_force_does_not_buy_a_green_over_a_missing_requirement():
    """The force switch overrules a refusal, never a requirement. Forcing past
    a store that is not answering would produce a green covering less than it
    claims, and the shell this replaced never allowed it."""
    port = free_port()
    p = repo(
        {
            "force_env": ["GATE_FORCE"],
            "tiers": [
                {
                    "name": "unit",
                    "cmd": "true",
                    "requires_port": [
                        {"port": port, "why": "nothing answers there.", "hint": "start it"}
                    ],
                }
            ],
        },
        install_gate=True,
    )
    r = gate(p, env={"GATE_FORCE": "1"})
    check("SKIP" in r.stdout, f"force ran a gate whose requirement was missing: {r.stdout}")
    check(r.returncode == 1, f"exit {r.returncode}")
    return p


def test_two_runs_of_one_tier_do_not_share_a_log():
    """Two sessions on one working tree ran the same tier at once and the
    second truncated the first's log mid-write, leaving a verdict that was
    about neither run."""
    import threading

    p = repo(
        {"tiers": [{"name": "unit", "cmd": "for i in $(seq 40); do echo line-$i; done; sleep 2"}]},
        install_gate=True,
    )
    results = []
    threads = [threading.Thread(target=lambda: results.append(gate(p))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    out = [r.stdout for r in results]
    check(sum("BUSY" in o for o in out) == 1, f"expected exactly one BUSY: {out}")
    check(sum("PASS" in o for o in out) == 1, f"expected exactly one PASS: {out}")
    with open(os.path.join(p, ".gate-logs", "unit.log")) as fh:
        lines = [ln for ln in fh.read().splitlines() if ln.startswith("line-")]
    check(len(lines) == 40, f"the winner's log was cut: {len(lines)} lines of 40")
    check(verdict(p, "unit") == "PASS", verdict(p, "unit"))
    return p


def test_a_named_tier_runs_alone_and_an_unknown_one_is_usage():
    p = repo(
        {"tiers": [{"name": "one", "cmd": "true"}, {"name": "two", "cmd": "true"}]},
        install_gate=True,
    )
    r = gate(p, "one")
    check("one" in r.stdout and "two" not in r.stdout, r.stdout)
    check(
        not os.path.exists(os.path.join(p, ".gate-logs", "two.verdict")),
        "a tier that was not asked for left a verdict",
    )

    bad = gate(p, "three")
    check(bad.returncode == 64, f"exit {bad.returncode}")
    check("usage:" in bad.stderr, bad.stderr)
    return p


def test_all_tiers_run_and_one_failure_reddens_the_run():
    p = repo(
        {
            "tiers": [
                {"name": "one", "cmd": "true"},
                {"name": "two", "cmd": "false"},
                {"name": "three", "cmd": "true"},
            ]
        },
        install_gate=True,
    )
    r = gate(p)
    check(r.returncode == 1, f"exit {r.returncode}")
    check(verdict(p, "three") == "PASS", "a tier after the failure did not run")
    return p


def test_the_verdict_is_written_through_a_temporary_file():
    p = repo({"tiers": [{"name": "unit", "cmd": "true"}]}, install_gate=True)
    gate(p)
    left = [f for f in os.listdir(os.path.join(p, ".gate-logs")) if f.startswith(".")]
    check(not left, f"temporary files left behind: {left}")
    return p


def test_no_config_is_an_explained_exit_rather_than_a_traceback():
    p = repo(None, install_gate=True)
    r = gate(p)
    check(r.returncode != 0, "a repo with no gates.json exited zero")
    check("Traceback" not in r.stderr, r.stderr)
    check("gates.json" in r.stderr, r.stderr)
    return p


def test_broken_json_says_so():
    p = repo({"tiers": []}, install_gate=True)
    with open(os.path.join(p, ".claude", "gates.json"), "w") as fh:
        fh.write("{ not json")
    r = gate(p)
    check("Traceback" not in r.stderr, r.stderr)
    check("not valid JSON" in r.stderr, r.stderr)
    return p


if __name__ == "__main__":
    print("bin/gate")
    sys.exit(run_tests(sys.modules[__name__]))
