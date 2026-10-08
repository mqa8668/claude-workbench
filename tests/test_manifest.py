"""The package's own shape: the two manifests, the hook wiring, the agents and
the template. These are the failures that install cleanly and do nothing."""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import ROOT, check, run_tests  # noqa: E402


def load(*parts):
    with open(os.path.join(ROOT, *parts)) as fh:
        return json.load(fh)


def test_the_plugin_manifest_is_complete():
    m = load(".claude-plugin", "plugin.json")
    for key in ("name", "version", "description"):
        check(m.get(key), f"plugin.json has no {key}")
    check(re.fullmatch(r"\d+\.\d+\.\d+", m["version"]), m["version"])
    return None


def test_the_marketplace_manifest_points_at_a_real_plugin():
    m = load(".claude-plugin", "marketplace.json")
    check(m.get("plugins"), "marketplace.json lists no plugins")
    plugin = load(".claude-plugin", "plugin.json")
    names = [p["name"] for p in m["plugins"]]
    check(plugin["name"] in names, f"{plugin['name']} is not listed in {names}")
    for entry in m["plugins"]:
        source = entry.get("source", "./")
        check(os.path.isdir(os.path.join(ROOT, source)), f"no such source: {source}")
    return None


def test_every_wired_hook_exists_and_is_addressed_through_the_plugin_root():
    wiring = load("hooks", "hooks.json")
    seen = 0
    for event, groups in wiring["hooks"].items():
        for group in groups:
            for entry in group["hooks"]:
                command = entry["command"]
                check(
                    "${CLAUDE_PLUGIN_ROOT}" in command,
                    f"{event}: {command} is not addressed through the plugin root",
                )
                match = re.search(r"hooks/(\w+\.py)", command)
                check(match, f"{event}: cannot tell which file {command} runs")
                path = os.path.join(ROOT, "hooks", match.group(1))
                check(os.path.exists(path), f"{event}: no such hook {match.group(1)}")
                seen += 1
    check(seen >= 7, f"only {seen} hooks wired")
    return None


def test_every_hook_file_compiles():
    import py_compile

    for name in sorted(os.listdir(os.path.join(ROOT, "hooks"))):
        if name.endswith(".py"):
            py_compile.compile(os.path.join(ROOT, "hooks", name), doraise=True)
    py_compile.compile(os.path.join(ROOT, "bin", "gate"), doraise=True)
    return None


def test_every_agent_declares_a_name_a_description_and_a_model():
    MODELS = {"haiku", "sonnet", "opus", "inherit"}
    files = [f for f in os.listdir(os.path.join(ROOT, "agents")) if f.endswith(".md")]
    check(files, "the package ships no agents")
    for name in sorted(files):
        with open(os.path.join(ROOT, "agents", name)) as fh:
            text = fh.read()
        head = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        check(head, f"{name}: no frontmatter")
        block = head.group(1)
        declared = re.search(r"^name: (\S+)$", block, re.M)
        check(declared, f"{name}: no name")
        check(declared.group(1) == name[:-3], f"{name}: declares itself {declared.group(1)}")
        check(re.search(r"^description: \S", block, re.M), f"{name}: no description")
        model = re.search(r"^model: (\S+)$", block, re.M)
        check(model, f"{name}: no model - it would inherit whatever spawned it")
        check(model.group(1) in MODELS, f"{name}: unknown model {model.group(1)}")
    return None


def test_the_template_config_is_usable_as_it_stands():
    template = load("templates", "gates.json")
    check(template.get("tiers"), "the template declares no tiers")
    for tier in template["tiers"]:
        check(tier.get("name") and tier.get("cmd"), f"incomplete tier: {tier}")
        for pattern in tier.get("guard", []):
            re.compile(pattern)
    for rule in template.get("deny", []):
        re.compile(rule["match"])
        check(rule.get("say"), "a deny rule with no explanation")
    return None


def test_the_command_and_the_documents_are_there():
    for path in (
        "commands/init-workbench.md",
        "SKILL.md",
        "README.md",
        "templates/statusline-extra.py",
        "templates/BRIEF-TEMPLATE.md",
        "statusline/statusline.py",
        "LICENSE",
        "CHANGELOG.md",
        "bin/gate",
        "bin/agents",
    ):
        check(os.path.exists(os.path.join(ROOT, path)), f"missing: {path}")
    check(os.access(os.path.join(ROOT, "bin", "gate"), os.X_OK), "bin/gate is not executable")
    return None


def test_the_statusline_template_reads_the_config():
    """The segments module a project copies rather than inherits. If it went back to a
    hard-coded tuple, a tier added to gates.json would show nothing."""
    import importlib.util
    from _harness import repo

    spec = importlib.util.spec_from_file_location(
        "extra_template", os.path.join(ROOT, "templates", "statusline-extra.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    project = repo(
        {
            "tiers": [{"name": "alpha", "cmd": "true", "watch": ["src/"]}],
            "checks": [{"name": "e2e", "watch": ["src/"]}],
            "ports": [[1234, "1234", "store"]],
        }
    )
    try:
        watched = module._watched(project)
        check([r[0] for r in watched] == ["alpha", "e2e"], f"watched: {watched}")
        check(watched[0][1] == "gate" and watched[1][1] == "check", f"kinds: {watched}")
        check(module._ports(project) == ((1234, "1234", "store"),), module._ports(project))
    finally:
        import shutil

        shutil.rmtree(project, ignore_errors=True)
    return None


def private_terms() -> list:
    """Words that must never ship, kept out of the tree on purpose: a leak test
    that spells the names it forbids is itself the leak. Read from the
    `WORKBENCH_PRIVATE_TERMS` environment variable (a regex) or from a
    gitignored `.private-terms` file (one regex per line). Neither set means
    this part of the check is skipped."""
    terms = []
    env = os.environ.get("WORKBENCH_PRIVATE_TERMS", "").strip()
    if env:
        terms.append(env)
    try:
        with open(os.path.join(ROOT, ".private-terms")) as fh:
            terms += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    except OSError:
        pass
    return terms


def test_the_package_carries_no_project_of_its_own():
    """A repo name or a hostname in here is a rule that travelled by accident."""
    leaked = []
    forbidden = [re.compile(t, re.I) for t in private_terms()]
    if not forbidden:
        print("        (no private-term list set; name search skipped)")
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "tests"}]
        for name in files:
            if not name.endswith((".py", ".md", ".json")) or name == ".private-terms":
                continue
            path = os.path.join(root, name)
            with open(path, errors="replace") as fh:
                text = fh.read().lower()
            for term in forbidden:
                if term.search(text):
                    leaked.append(f"{os.path.relpath(path, ROOT)}: matches a private term")
            # A bare "rule 14" is a citation of somebody else's law: it means
            # nothing here and reads as though it does. Caught one on the way
            # to publishing, which the name search above had walked past.
            for cite in re.findall(r"\brule \d+\b", text):
                leaked.append(f"{os.path.relpath(path, ROOT)}: {cite}")
            # An address of a machine, or of a person.
            for probe in re.findall(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b|\b\d+\.\d+\.\d+\.\d+\b", text):
                if probe in ("127.0.0.1", "0.0.0.0"):
                    continue  # a loopback address is not anybody's machine
                leaked.append(f"{os.path.relpath(path, ROOT)}: {probe}")
    check(not leaked, "the package names the project it came from: " + "; ".join(leaked))
    return None


def test_the_plugin_version_is_the_changelogs_latest():
    version = load(".claude-plugin", "plugin.json")["version"]
    with open(os.path.join(ROOT, "CHANGELOG.md")) as fh:
        headings = re.findall(r"^## \[([^\]]+)\]", fh.read(), re.M)
    check(headings and headings[0] == version, f"plugin {version}, changelog {headings[:1]}")
    return None


if __name__ == "__main__":
    print("the package")
    sys.exit(run_tests(sys.modules[__name__]))
