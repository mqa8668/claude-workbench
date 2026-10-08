# Regenerate: vhs docs/media/demo.tape  (needs vhs and pytest on PATH).
# Run from a throwaway sample project at /tmp/acme-api: a tiny package with three tests,
# .claude/gates.json (one "api" tier running pytest -q), bin/gate and bin/agents copied from
# this repo, hooks/ copied to plugin/hooks, pretool.json holding a PreToolUse payload for a bare
# "pytest", and a few spawn rows in .claude/.state/agents.jsonl written by hooks/agents.py.
Output docs/media/demo.gif
Set Shell "bash"
Set FontSize 22
Set Width 1400
Set Height 780
Set Padding 24
Set Theme "Catppuccin Mocha"
Set TypingSpeed 28ms
Set Framerate 24

Hide
Type "export PS1='$ ' && cd /tmp/acme-api && clear"
Enter
Show

Type "cat .claude/gates.json"
Enter
Sleep 2s
Type "bin/gate"
Enter
Sleep 1.8s
Hide
Type "sed -i.bak 's/(1 - pct/(1 + pct/' acme/__init__.py"
Enter
Show
Type "bin/gate | head -2"
Enter
Sleep 2.2s
Hide
Type "mv acme/__init__.py.bak acme/__init__.py && clear"
Enter
Show

Type "python3 plugin/hooks/guard.py < pretool.json 2>&1 | fold -s -w 88"
Enter
Sleep 3.2s
Hide
Type "clear"
Enter
Show
Type "bin/agents"
Enter
Sleep 4s
