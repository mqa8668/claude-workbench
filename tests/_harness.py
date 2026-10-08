"""(`from __future__` first: `dict | None` in a signature is evaluated at
definition time before 3.10, and one of the boxes this runs on is on 3.9.)

A throwaway repository, and the small amount of ceremony every test needs.

Nothing here touches a real project: each test builds a git repo in a temp
directory, writes the `gates.json` it wants, and installs the package's own
`bin/gate` into it the way `/init-workbench` would.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Fail(AssertionError):
    pass


def check(cond, why):
    if not cond:
        raise Fail(why)


def repo(gates: dict | None = None, install_gate: bool = False) -> str:
    """A git repository with one commit, optionally carrying a gates.json and
    the runner. The caller is responsible for removing it - `run_tests` does."""
    path = tempfile.mkdtemp(prefix="wb-test-")
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    with open(os.path.join(path, "README.md"), "w") as fh:
        fh.write("x\n")
    subprocess.run(["git", "add", "-A"], cwd=path, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"],
        cwd=path,
        capture_output=True,
    )
    os.makedirs(os.path.join(path, ".claude", "hooks"), exist_ok=True)
    if gates is not None:
        with open(os.path.join(path, ".claude", "gates.json"), "w") as fh:
            json.dump(gates, fh, indent=2)
    if install_gate:
        os.makedirs(os.path.join(path, "bin"), exist_ok=True)
        dst = os.path.join(path, "bin", "gate")
        shutil.copy(os.path.join(ROOT, "bin", "gate"), dst)
        os.chmod(dst, 0o755)
    return path


def gate(project: str, *args, env: dict | None = None):
    """Run the copy of the runner installed in `project`."""
    return subprocess.run(
        [sys.executable, os.path.join(project, "bin", "gate"), *args],
        cwd=project,
        capture_output=True,
        text=True,
        env=dict(os.environ, **(env or {})),
    )


def hook(name: str, payload: dict, project: str, env: dict | None = None):
    """Run one of the package's hooks the way Claude Code will: from the
    package directory, told where the project is."""
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "hooks", name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=project, CLAUDE_PLUGIN_ROOT=ROOT, **(env or {})),
    )


class Port:
    """A real listening socket, because the runner asks `lsof` rather than
    anything a test could stub."""

    def __enter__(self) -> int:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        return self.sock.getsockname()[1]

    def __exit__(self, *exc):
        self.sock.close()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def run_tests(module) -> int:
    """Every `test_*` function in the module, one line each."""
    names = sorted(n for n in dir(module) if n.startswith("test_"))
    bad, made = 0, []
    for name in names:
        fn = getattr(module, name)
        try:
            got = fn()
            if isinstance(got, str) and os.path.isdir(got):
                made.append(got)
            print(f"  ok    {name[5:].replace('_', ' ')}")
        except Fail as exc:
            bad += 1
            print(f"  FAIL  {name[5:].replace('_', ' ')}\n          {exc}")
        except Exception as exc:  # a crash is a failure, and its type matters
            bad += 1
            print(
                f"  ERROR {name[5:].replace('_', ' ')}\n          {exc.__class__.__name__}: {exc}"
            )
    for path in made:
        shutil.rmtree(path, ignore_errors=True)
    return bad
