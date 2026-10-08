# Changelog

All notable changes are listed here. The format follows Keep a Changelog and
the project follows Semantic Versioning.

## [0.1.0]

First public release.

### Added

- `bin/gate`: runs each tier declared in `.claude/gates.json`, keeps the full
  log in `.gate-logs/`, prints a one-line verdict and leaves a verdict file.
  A tier can refuse to run when a port is up (`refuses_port`) or down
  (`requires_port`).
- Context guard (`hooks/guard.py`): refuses bare gate commands and whole-suite
  runs, nudges long investigations into subagents, brakes repeated rounds with
  one agent, and refuses new fan-out when most of the five-hour window is gone.
  `cheap_agents` in `gates.json` lists the agents that brake lets through.
- Token diet hook (`hooks/diet.py`): blocks a subagent spawn whose prompt lacks
  the token diet block and hands back the text to paste.
- Checkpoint and resume (`hooks/checkpoint.py`, `hooks/resume.py`): a per-turn
  `.claude/session.md` that the next session reads back.
- Subagent ledger (`hooks/agents.py`, `hooks/subagent.py`, `bin/agents`): one
  row per spawn, round and cost, with cost summed from the agent's own transcript.
- Context warning (`hooks/prompt.py`): a single line above 200k and 350k tokens.
- Status line host (`statusline/statusline.py`) and segments
  (`templates/statusline-extra.py`): gate verdicts and staleness, ports, live
  subagents, and the five-hour figure the guard reads.
- Agents: `gate`, `digger`, `reviewer`, `planner`, `scribe`.
- `/init-workbench` command and the `workbench` skill.
- `bin/selftest`: the package's own checks, no network, standard library only.

### Notes

- The self-test suite found five defects before release, the worst being a guard
  that stopped guarding, silently, when its config file was broken. A broken
  config is now reported loudly.
- `planner` and `reviewer` use `model: inherit`.
- POSIX only (the runner uses `fcntl`). Python 3.9 or newer.
