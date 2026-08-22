"""CI check: validate Claude Code subagent definition frontmatter.

`claude plugin validate` exits 0 on a bare agents directory regardless of its
contents — a space-bearing name, a nonexistent tool, a bogus model, or a file
with no frontmatter at all all pass (see docs/subagent/README-agents.md). So
nothing validates these files today, and a typo ships to every project that
vendors this repo on the next submodule bump.

This checks the things that silently break a subagent at load time. Stdlib
only, so CI needs no dependencies.

Usage:

    python tools/lint_agents.py docs/subagent/
"""

import argparse
import re
import sys
from pathlib import Path

REQUIRED_KEYS = {"name", "description", "tools", "model"}
VALID_MODELS = {"opus", "sonnet", "haiku", "inherit"}
VALID_MEMORY = {"user", "project", "local"}

# Tools grantable to a subagent. AskUserQuestion is deliberately absent: it is
# always stripped from subagents, so listing it signals a misunderstanding.
VALID_TOOLS = {
    "Agent",
    "Bash",
    "Edit",
    "Glob",
    "Grep",
    "NotebookEdit",
    "Read",
    "SlashCommand",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "Write",
}

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
TOOL_RE = re.compile(r"^([A-Za-z]+)(?:\(([^)]*)\))?$")


def parse_frontmatter(text: str):
    """Return (frontmatter dict, error). Deliberately not a full YAML parser —
    these files use flat `key: value` frontmatter and a dependency-free check
    is worth more here than generality."""
    if not text.startswith("---\n"):
        return None, "no YAML frontmatter (file must start with ---)"
    end = text.find("\n---", 4)
    if end == -1:
        return None, "frontmatter is not terminated by a closing ---"

    data = {}
    for lineno, line in enumerate(text[4:end].splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None, f"line {lineno}: not a `key: value` pair"
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data, None


def check_file(path: Path) -> list[str]:
    problems = []
    front, error = parse_frontmatter(path.read_text())
    if error:
        return [error]

    missing = REQUIRED_KEYS - front.keys()
    if missing:
        problems.append(f"missing required key(s): {', '.join(sorted(missing))}")

    name = front.get("name", "")
    if name and not NAME_RE.match(name):
        problems.append(f"name {name!r} is not lowercase-kebab-case")
    if name and name != path.stem:
        problems.append(f"name {name!r} does not match filename stem {path.stem!r}")

    model = front.get("model")
    if model and model not in VALID_MODELS:
        problems.append(f"model {model!r} is not one of {sorted(VALID_MODELS)}")

    memory = front.get("memory")
    if memory and memory not in VALID_MEMORY:
        problems.append(f"memory {memory!r} is not one of {sorted(VALID_MEMORY)}")

    description = front.get("description", "")
    if description and len(description) < 40:
        problems.append("description is too short to drive automatic delegation")

    for raw in (t.strip() for t in front.get("tools", "").split(",")):
        if not raw:
            continue
        match = TOOL_RE.match(raw)
        if not match:
            problems.append(f"tool {raw!r} is not a valid tool spec")
            continue
        tool, scope = match.group(1), match.group(2)
        if tool not in VALID_TOOLS:
            problems.append(f"unknown tool {tool!r}")
        if scope is not None and not scope.strip():
            problems.append(f"tool {raw!r} has an empty scope")
        if tool == "Agent" and scope is None:
            problems.append(
                "bare `Agent` grant lets this subagent spawn any agent type, "
                "including ones holding every tool — scope it, e.g. Agent(qa-tester)"
            )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()

    files = sorted(
        {
            f
            for p in args.paths
            for f in (p.rglob("*.md") if p.is_dir() else [p])
            if not f.name.startswith("README")
        }
    )
    if not files:
        print("no agent definitions found", file=sys.stderr)
        return 1

    failed = False
    for path in files:
        problems = check_file(path)
        if problems:
            failed = True
            print(f"{path}:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        else:
            print(f"{path}: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
