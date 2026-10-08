---
description: Set this repository up for the workbench - detect its gates, write .claude/gates.json, and install the runner and the status line.
---

Set up the workbench in the current repository. Do all of it yourself; ask
only where the answer cannot be read off the tree.

**1. Work out the tiers.** One tier per thing that can independently be green
or red. Read what is actually there rather than guessing:

- `package.json` - a `build`, `typecheck`, `lint` or `test` script
- `mix.exs` - a `precommit` alias, else `mix test`
- `pubspec.yaml` - analyze, test
- `pyproject.toml` / `requirements.txt` - ruff, pytest
- `Cargo.toml` - `cargo clippy`, `cargo test`
- `go.mod` - `go vet`, `go test ./...`
- a CI workflow under `.github/workflows/` - **this is the best source there
  is.** The local gate and the CI gate drifting apart is how a red build ships
  nothing while everyone believes it green, so take CI's commands verbatim.

For each tier write: `name`, `dir`, `cmd`, `watch` (the paths whose being
written since the last verdict make that verdict stale), and a `guard` regex
for the bare command it replaces. Add `env`, `requires_port` or `refuses_port`
only where the project genuinely has one - a required port is for a gate that
would otherwise run a quietly smaller suite than it claims.

**2. Write `.claude/gates.json`.** Start from
`${CLAUDE_PLUGIN_ROOT}/templates/gates.json` and keep its header comment - it
is what the next person reads. Parse it back to prove it is valid JSON.

**3. Install the runner and the status line.** Copy
`${CLAUDE_PLUGIN_ROOT}/bin/gate` to `bin/gate` (`chmod +x`),
`${CLAUDE_PLUGIN_ROOT}/statusline/statusline.py` to
`.claude/hooks/statusline.py`, and
`${CLAUDE_PLUGIN_ROOT}/templates/statusline-extra.py` to
`.claude/hooks/statusline-extra.py`. All three are copies rather than links on
purpose: a teammate who clones the repo gets a working gate without installing
anything. Re-run this command to refresh them.

Then offer to add this to `.claude/settings.json`, merging with the file if it
exists and asking first if a `statusLine` is already set:

```json
{ "statusLine": { "type": "command", "command": "python3 .claude/hooks/statusline.py" } }
```

Without it the status line shows nothing and the guard's five-hour brake has
no reading to act on.

**4. Ignore what should not be committed**: `.gate-logs/`, `.claude/.state/`,
`.claude/session.md`.

**5. Prove it.** Run `bin/gate` and report the verdict per tier. A tier that
fails on the first run is information, not a setup error - say which and why.
Then render the status line once to show the `gate` segment appears.

**6. Tell the user what is now true**, in five lines: the tiers, where the logs
go, that the hooks come from the plugin and need no per-project wiring, and
that `.claude/gates.json` is the one file to edit when a gate changes.

Do **not** copy this project's CLAUDE.md, agents or skills from anywhere. Those
are law, and law is paid for by a failure this repository has not had yet.
