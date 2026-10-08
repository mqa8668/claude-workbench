# Contributing

Issues and pull requests are welcome.

## Set up

There is nothing to install. The code is Python standard library only.

```
git clone https://github.com/mqa8668/claude-workbench
cd claude-workbench
bin/selftest
```

The tests build throwaway git repositories in a temp directory, so git needs a
user name and email configured. They use no network and touch nothing outside
that directory.

## Before you open a pull request

- `bin/selftest` passes.
- `ruff check .` and `ruff format --check .` pass.
- Every new brake or refusal comes with two checks: one that proves it fires,
  and one that proves it stays quiet when it should. A guard that fires too
  often gets switched off.
- A refusal always says what to do instead, in a form that runs.
- Keep it standard library only, and keep it working on Python 3.9.

## Private names

`tests/test_manifest.py` can search the tree for words that must not ship. Put
a regex in the `WORKBENCH_PRIVATE_TERMS` environment variable, or one regex per
line in a `.private-terms` file (gitignored). If neither exists the check is
skipped.

## Commits

Short imperative subject line, with the reason in the body when it is not
obvious.
