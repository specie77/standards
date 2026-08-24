"""CI check: validate Claude Code subagent definition frontmatter.

`claude plugin validate` exits 0 on a bare agents directory regardless of its
contents — a space-bearing name, a nonexistent tool, a bogus model, or a file
with no frontmatter at all all pass (see docs/subagents.md). So nothing
validates these files today, and a typo ships to every project that vendors
this repo on the next submodule bump.

This checks the things that silently break a subagent at load time. Stdlib
only, so CI needs no dependencies.

The definitions live in agents/ at the repo root, not under docs/: consuming
projects symlink that directory into .claude/agents/, which Claude Code scans
recursively, so it must contain agent definitions and nothing else.

Usage:

    python tools/lint_agents.py agents/
"""

import argparse
import re
import sys
from pathlib import Path

REQUIRED_KEYS = {"name", "description", "tools", "model"}
VALID_MODELS = {"opus", "sonnet", "haiku", "inherit"}

# `model` is required rather than allowed to default. An omitted model inherits
# the main session's, which changes behaviour silently on a model migration —
# the same argument CLAUDE.md § Claude API makes for never omitting `thinking`.

# Observed accepted values. Not authoritative — Claude Code's own list is not
# documented — so this catches a typo, not an exhaustive set. Widen it if a
# legitimate colour is rejected.
VALID_COLORS = {
    "blue",
    "cyan",
    "green",
    "orange",
    "pink",
    "purple",
    "red",
    "yellow",
}

# `memory:` is prohibited outright, so there is no set of valid values.
# docs/subagents.md § "`memory:` — not enabled, deliberately" is the rationale:
# the first ~200 lines of MEMORY.md are injected into the subagent's SYSTEM
# prompt at startup, the subagent can write that file itself, and `project`
# scope is committed to git. Any untrusted text a subagent ever writes there is
# re-injected into a system prompt on every later run, and in every clone —
# CLAUDE.md § Prompt Injection rule 1 violated persistently rather than once.
MEMORY_PROHIBITED = (
    "`memory:` is prohibited on every subagent in this set. MEMORY.md is "
    "injected into the SYSTEM prompt at startup and the subagent can write it, "
    "so untrusted content it ingests becomes permanent system-prompt content "
    "(CLAUDE.md § Prompt Injection rule 1). See docs/subagents.md."
)

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

# The artifact map in docs/delivery-artifacts.md: | `path` | owner | format |
MAP_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*([^|]+?)\s*\|")
# Backticked docs/delivery/... paths inside a prompt's owned-paths rule.
OWNED_PATH_RE = re.compile(r"`(docs/delivery/[^`]+)`")
OWNED_RULE_MARKER = "Stay inside your owned paths"


def normalise_artifact_path(path: str) -> str:
    """Collapse a templated filename to its directory so the map and a prompt
    agree: `docs/delivery/adr/ADR-NNNN-<slug>.md` and `docs/delivery/adr/*`
    both mean "the adr directory"."""
    path = path.strip()
    name = path.rsplit("/", 1)[-1]
    if "<" in name or "NNNN" in name or "*" in name:
        return path.rsplit("/", 1)[0] + "/"
    return path


def parse_artifact_map(path: Path) -> dict[str, str]:
    """Return {normalised artifact path: owner} from the artifact map table."""
    owners = {}
    for line in path.read_text().splitlines():
        match = MAP_ROW_RE.match(line)
        if not match:
            continue
        artifact, owner = match.group(1), match.group(2).strip()
        if artifact.startswith("docs/delivery/"):
            owners[normalise_artifact_path(artifact)] = owner
    return owners


def check_owned_paths(text: str, name: str, owners: dict[str, str]) -> list[str]:
    """Cross-check the prompt's owned-paths rule against the artifact map.

    The map is the single source of truth (docs/delivery-artifacts.md); a prompt
    restating it is a copy that can drift. This makes the two disagree loudly
    instead of silently — a subagent quietly claiming another's artifact is the
    failure that removes the review boundary the split exists to create.
    """
    rule = next(
        (line for line in text.splitlines() if OWNED_RULE_MARKER in line), None
    )
    if rule is None:
        return [
            f"no owned-paths rule found (expected a line containing "
            f"{OWNED_RULE_MARKER!r}) — cannot cross-check the artifact map"
        ]

    claimed = {normalise_artifact_path(p) for p in OWNED_PATH_RE.findall(rule)}
    assigned = {p for p, owner in owners.items() if owner == name}

    problems = []
    for path in sorted(claimed - assigned):
        actual = owners.get(path)
        problems.append(
            f"claims {path!r}, which the artifact map assigns to "
            f"{actual!r}" if actual else f"claims {path!r}, which is not in the artifact map"
        )
    for path in sorted(assigned - claimed):
        problems.append(
            f"artifact map assigns {path!r} to this subagent, but its "
            f"owned-paths rule does not list it"
        )
    return problems


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


def check_file(
    path: Path,
    known_agents: set[str] | None = None,
    owners: dict[str, str] | None = None,
) -> list[str]:
    problems = []
    text = path.read_text()
    front, error = parse_frontmatter(text)
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

    if "memory" in front:
        problems.append(MEMORY_PROHIBITED)

    color = front.get("color")
    if color and color not in VALID_COLORS:
        problems.append(f"color {color!r} is not one of {sorted(VALID_COLORS)}")

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
        # A typo'd scope is not a safe failure: the grant names an agent that
        # does not exist, so the restriction it looks like it expresses is not
        # the one in force.
        if tool == "Agent" and scope and known_agents is not None:
            for target in (t.strip() for t in scope.split(",")):
                if target and target not in known_agents:
                    problems.append(
                        f"Agent({target}) names no subagent in this directory; "
                        f"known: {sorted(known_agents)}"
                    )

    if owners is not None and name:
        problems.extend(check_owned_paths(text, name, owners))

    return problems


def main_argv(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--artifact-map",
        type=Path,
        help="docs/delivery-artifacts.md — cross-check each prompt's "
        "owned-paths rule against the artifact map it points at. Omit to skip.",
    )
    args = parser.parse_args(argv)

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

    known_agents = {f.stem for f in files}

    owners = None
    if args.artifact_map:
        if not args.artifact_map.exists():
            print(f"artifact map {args.artifact_map} not found", file=sys.stderr)
            return 1
        owners = parse_artifact_map(args.artifact_map)
        if not owners:
            print(
                f"no artifact map rows parsed from {args.artifact_map} — the "
                "table format changed, and this check is silently passing",
                file=sys.stderr,
            )
            return 1

    failed = False
    for path in files:
        problems = check_file(path, known_agents=known_agents, owners=owners)
        if problems:
            failed = True
            print(f"{path}:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
        else:
            print(f"{path}: ok")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main_argv())
