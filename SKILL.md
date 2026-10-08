---
name: workbench
description: Session machinery for any repository - config-driven gates (bin/gate and .claude/gates.json), a context guard that pushes investigation into subagents, a checkpoint the next session reads back, and a ledger of what every subagent spent. Use when setting a new repository up ("/init-workbench", "add gates here", "set up the workbench"), when a gate command or tier changes, when the status line's gate segment is wrong or missing, or when asked how the guard, the checkpoint or the agent ledger work.
---

# The workbench

Machinery, not law. It answers three questions that every repository has and
no repository answers by itself: **is it green**, **is this session about to
read forty files it should have delegated**, and **what did the delegation
actually cost**.

## One file says what a project's gates are

`.claude/gates.json`. Three readers, one list:

| reader | what it takes from the file |
|---|---|
| `bin/gate` | the tiers, their commands, their ports, how to summarise a log |
| `hooks/guard.py` | which bare command to refuse, and what to suggest instead |
| `statusline-extra.py` | which verdicts to show, and what makes each stale |

The file also takes `cheap_agents`, the agents the five-hour brake lets through.

Before this file each of the three held its own copy, and the third to drift
was always the status line: a tier added to the runner showed nothing until
somebody remembered a tuple in a hook.

`bin/gate` runs a tier and prints only the verdict; the log goes to
`.gate-logs/` and the verdict outlives the run in `.gate-logs/<tier>.verdict`,
which is what the status line reads. A tier can refuse rather than run -
`refuses_port` for a gate that would build over something live, `requires_port`
for one that would otherwise run a smaller suite than it claims.

## The hooks come from here, not from the project

`hooks/hooks.json` wires all of them, so a project needs no hook entries in its
own `settings.json`:

- **`guard.py`** counts reads, refuses a bare gate command, refuses a whole
  test suite where a named file was meant, and brakes a fan-out.
- **`checkpoint.py`** rewrites `.claude/session.md` after every turn;
  **`resume.py`** reads it back at session start. That is what makes ending a
  session cheap, which is the only thing that makes anyone do it.
- **`agents.py`** and **`subagent.py`** write a row per spawn and per round to
  `.claude/.state/agents.jsonl`, with what each agent actually spent.
  `bin/agents` reads it back.
- **`prompt.py`** puts a one-line context warning in front of Claude above
  200k tokens (warm) and 350k (hot).
- **`diet.py`** refuses a subagent spawn whose prompt lacks the token diet.

## The status line is wired in by the project

Claude Code runs whatever `statusLine` in settings.json names. This package
ships a small host, `statusline/statusline.py`, that prints the directory,
branch, model and five-hour usage, then the segments from
`templates/statusline-extra.py` (gate verdicts and staleness, ports, live
subagents). `/init-workbench` copies both into `.claude/hooks/` and offers to
add the `statusLine` entry. The host also leaves the five-hour figure in
`.claude/.state/budget.json`, which is what the guard's rate-window brake reads;
without a status line that brake does nothing.

## The agents

Five, and only the ones that are genuinely project-independent: `gate`,
`digger`, `reviewer`, `planner`, `scribe`. Each is pinned to a model, and the
split is by whether judgement is the deliverable - a `gate` runs a script and
hands back a verdict, a `digger` hands back a root cause somebody then acts on.

There is no build or drive agent on purpose. Measured on my own projects, those
were most of what delegation cost, and every line that makes one good is a rule
about one product. Write them per project.

## Checking it

`bin/selftest` - the self-test checks over the runner, the guard, every hook and
the package's own manifests, each against a throwaway repository. It needs
nothing running. Run it before committing here and after installing anywhere
new.

## Using it

`/init-workbench` in a new repository. It reads the tree - and the CI workflow,
which is the best source there is - proposes the tiers, writes the file,
installs the runner, and proves it by running the gates once.
