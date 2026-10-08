"""PreToolUse on Task/Agent: no subagent launches without the token diet.

The rule is that the diet binds every agent "including ad-hoc ones". That was
a claim with no mechanism behind it. A named agent carries the rule in its own
definition file; an ad-hoc one carries whatever the spawning session happened to
type, and that once meant hand-writing the discipline into six
prompts, three of which still ran out of turns and one of which reported page
bytes as if they were extracted body characters.

So this refuses a spawn whose prompt does not carry the rule, and hands back the
text to paste. One block, once, per prompt that forgot - which is what mandatory
has to mean if it is going to mean anything.

**Why a block and not an append.** Rewriting tool input from a hook is not a
contract this codebase has verified, and a guard built on an unverified API is a
guard that silently stops guarding. Exit 2 with stderr is the same idiom
`guard.py` already uses and is known to reach the model. If input mutation is
ever confirmed, this becomes an append and the block goes away.

Matched on Task|Agent only. SendMessage is deliberately not matched: it resumes
an agent whose first prompt already passed through here, and blocking a
follow-up on a rule the agent has had since it started is noise.
"""

import json
import sys

# The marker. Case-insensitive, and deliberately just the two words: the point
# is that the discipline is IN the prompt, not that it was copied verbatim.
MARKER = "token diet"

# Agent types that carry the rule in their own definition file and do not need
# it repeated in every prompt. Keep this list short - it is an exemption, and
# every entry is a place the rule is only as current as that file.
EXEMPT = {"gate", "forge", "edge", "workbench:gate"}

RULE = """## TOKEN DIET (mandatory)

Context is the scarce resource here, not time and not cleverness. Most of what
fills a window is material thrown away the moment the answer is known.

- Read to decide, not to survey. The one function, the one decision, the one
  section. `sed -n` on the part you need beats reading the file; never read a
  directory to get oriented.
- Never paste or summarise a PASSING log. A green step is one line: the verdict.
  For a FAILURE quote the file, the line and the message verbatim, and nothing
  around it.
- Batch your commands. Many probes in one call, not one call per probe. Running
  out of turns halfway is a wasted agent and the work comes back as nothing.
- Report in numbers and verdicts. Say what you measured, in what unit, and what
  it means. Do not narrate the route you took and do not restate the task.
- Name the unit or do not give the number. "224 kB of page bytes" and "3,953
  chars of extracted body" are different measurements and only one of them
  answers a question about body length.
- Say "not measured" rather than inferring. An unmeasured claim stated briefly
  is still worthless. If you could not measure it, that is the finding."""


def main() -> int:
    payload = json.load(sys.stdin)
    if payload.get("tool_name") not in ("Task", "Agent"):
        return 0

    args = payload.get("tool_input") or {}
    if args.get("subagent_type") in EXEMPT:
        return 0

    prompt = args.get("prompt") or ""
    if MARKER in prompt.lower():
        return 0

    print(
        "This spawn has no token diet in its prompt, and an ad-hoc agent "
        "inherits no discipline of its own. Add the block below to the prompt "
        "(trim it to what this agent will actually hit) and call again.\n\n" + RULE,
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    # Session hygiene must never be the thing that stops the work. Anything
    # unexpected exits clean and says so - a hook that fails without a word is
    # a hook nobody knows has stopped working.
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see above
        print(f"diet.py: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        sys.exit(0)
