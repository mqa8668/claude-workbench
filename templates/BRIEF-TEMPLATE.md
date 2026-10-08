# The brief - one page, written before the first agent

Copy this into `scratchpad/jobs/<slug>/BRIEF.md` and fill it in **before**
spawning anything. It is not a record of the job; it is the job's first
artefact, and every agent after the first reads it instead of rediscovering
what it holds.

## Why it exists

On one of my projects four separate agents each re-derived the same layout
constants - a column width, a minimum label size, a maximum page width -
because the one file that holds those numbers was written at the end of the
day. Each of them was correct and each of them cost a cold start. A fact
worked out once and written down once is the cheapest thing in this whole
setup; a fact worked out four times is the most expensive.

So: **never fan out to discover a shared fact.** Discover it once, write it
here, then fan out. And because no brief is complete on the first pass, the
brief is **cumulative** - but **the main session is the only writer.** Agents
end their report with `DERIVED:` lines and the coordinator appends them under
`## Derived`. Some agents are denied `Write` and `Edit` on
purpose, and a fan-out is a dozen agents at once: telling them all to append to
one file would either route around that tool policy or lose writes silently,
and "two agents writing one file" is what this same brief forbids six lines
lower.

## The template

```markdown
# <job> - brief

**Outcome.** One sentence. What exists at the end that does not exist now, and
who looks at it.

**Done looks like.** The testable version of the line above. A path that
exists, a gate that is green, a PDF with N sheets, a row that is PASS.

**Out of scope.** The things a reasonable agent would otherwise wander into.

## What is already worked out

Constants, geometry, paths, commands, names. Anything with a number in it.
Every line says where it came from, so a later agent can check it rather than
re-derive it.

- `<constant> = <value>` - from `<file or D-number>`
- The build line, verbatim, if there is one.

## Which rules bite here

Name them. Two or three, not all twenty. `CLAUDE.md` is 31 KB and every agent
told to "read the law" pays about 8k tokens for it; naming the rules that
actually apply to this job is what makes that read cheap instead of ritual.
**This section is the one that pays for the brief** - the agents are told that
if it is filled in, those rules plus their own file are enough to start on. Fill
it in badly and you have added a page to every spawn and saved nothing. Rules 1,
2, 4 and 10 apply whether or not you name them.

## The files

Who owns what. Another session may be in this tree, and two agents writing one
file is the failure this line prevents.

## Return

What each agent hands back, and how much of it.

## What it may spend

Left out of a brief this is the largest number in the job. An agent's cost goes
as the **square** of its turns, so name the ceiling here rather than hoping:

- **Turn budget** - **150 requests** for an agent that builds or drives, **80**
  for one that only reads, unless this job argues otherwise. Past it the agent
  writes `EVIDENCE.md` and hands back; the rest is a fresh spawn off this file.
  A turn is a request, not a tool call: two calls in one message is one turn -
  but measured on my own projects the two ran 1.00 to 1.07 on every run long
  enough to matter, so on a long unit they are the same number. **The ceiling
  is yours to set here, not the agent's to observe**: it has no request counter,
  27 of 311 runs went past 150, and the hook cannot count for it either
  (`guard.py`, "the turn budget"). If a unit cannot plausibly be done in the
  budget, it is two units - split it before spawning, not after.
- **Pictures** - which states actually need capturing, and which questions the
  DOM answers instead. An image is not expensive when taken (~1,900 tokens at
  desk width); it is expensive because it rides every turn after.
- **Batching** - name the reads that can go in one message. 93% of messages
  measured carried exactly one call, so nearly every call was paying for a turn
  of its own.

## Derived

*(Empty at the start. The main session appends the `DERIVED:` lines that come
back with each agent's report, so the next agent starts from them.)*
```

## The evidence file

`EVIDENCE.md` sits beside it, append-only, one row at a time as the work
happens. A build agent that does this loses nothing when it stops, which was not true
once when a stopped agent took its whole report with it; the folder just makes it available to everyone
else. A row is `PASS`, `FAIL` or `OPEN` with a reason, and it is written
**before** moving to the next step, not collected at the end.

## The ledger line

Every agent's last line is `NEW:` - what it hit that the brief did not contain,
or `NEW: none`. That is the only way to tell **scope the job discovered** from
**time lost to coordination**. Eight deliverables became fourteen
because framing the pictures found twelve real defects; that is not overhead,
and arguing about it as though it were means neither cost gets fixed.
