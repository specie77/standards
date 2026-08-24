#!/usr/bin/env python3
"""CI check: assert a project's .claude/settings.json actually applies the
permission rules the subagent set depends on.

Why this exists.

`docs/subagents.md` § "Required project configuration" says the frontmatter
alone is not a security boundary, and lists the deny rules and sandbox setting
that make up the rest of it. Nothing verified that any project applied them.
That is the "remember to do X" pattern `CLAUDE.md` and `docs/supply-chain.md`
attack everywhere else — the same reasoning that replaced "remember to
regenerate the SBOM" with a freshness check that fails the build.

The rules are not interchangeable and none is decorative:

  Read(./.env), Read(./**/.env)
      qa-tester holds Bash and runs suites that load .env. A deny keeps secret
      values out of the transcript, which persists in Claude Code's local
      session history (CLAUDE.md § Secrets). Note the limit: this covers
      Claude's file tools and the file commands Claude Code recognises inside
      Bash, NOT a Python or Node subprocess that opens the file itself. The
      sandbox is what closes that, which is why it is also required here.

  Edit(./.claude/**)
      The one whose absence undoes the others. Without it, this settings file
      and the SubagentStop hook that checks qa-tester's report both sit inside
      the subagents' write surface — including for the subagent that hook
      exists to constrain. A control a subagent can edit is not a control.

  Edit(./.standards/**), Edit(./.github/**), Edit(./CLAUDE.md)
      The upstream standards, the CI definition, and the project's own rules.
      Every control in the repo is defined in one of these.

  Agent(general-purpose), Agent(claude)
      Backstop. No subagent in the set holds an Agent grant, so nothing can
      spawn anything today; these keep that true if a prompt is ever edited to
      add one. Both named agents hold every tool in the session.

  sandbox.enabled
      OS-level, enforced for every Bash command AND its child processes. The
      only layer that closes the subprocess gap above.

  hooks.SubagentStop -> tools/qa_report_check.py
      The check on qa-tester's own report: a PASS carries the command that
      produced it, and every file written is declared. Wiring it is a manual
      per-project step like everything else here, so it is asserted here for
      the same reason the denies are. Checked by the script's filename, not by
      the exact command line, so a project may add its own flags.

An `allow` entry is deliberately not checked for, and never satisfies a
requirement here: allow auto-approves, it does not restrict. Only `deny` and
the sandbox are boundaries.

Stdlib only, so CI needs no dependencies.

Usage, from a consuming project that vendors this repo at .standards/:

    python .standards/tools/check_agent_settings.py
    python .standards/tools/check_agent_settings.py --settings .claude/settings.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_DENIES = [
    "Read(.env)",
    "Read(**/.env)",
    "Edit(.standards/**)",
    "Edit(.github/**)",
    "Edit(CLAUDE.md)",
    "Edit(.claude/**)",
    "Agent(general-purpose)",
    "Agent(claude)",
]

# Why each rule is required, printed alongside a failure so the fix is not
# cargo-culted. Keyed by the normalised rule.
RATIONALE = {
    "Read(.env)": "keeps secret values out of the transcript (CLAUDE.md § Secrets)",
    "Read(**/.env)": "same, for nested .env files",
    "Edit(.standards/**)": "upstream standards are not project-editable",
    "Edit(.github/**)": "CI and Dependabot config define the other controls",
    "Edit(CLAUDE.md)": "the project's own rules",
    "Edit(.claude/**)": (
        "THE CRITICAL ONE — without it, this settings file and the "
        "SubagentStop hook are writable by the subagents they constrain"
    ),
    "Agent(general-purpose)": "backstop: this agent type holds every tool",
    "Agent(claude)": "backstop: this agent type holds every tool",
}

LINE_COMMENT_RE = re.compile(r"//.*$")


def strip_jsonc(text: str) -> str:
    """Remove // line comments outside string literals.

    docs/subagents.md presents the settings block as jsonc, so a project may
    well have copied the comments along with it. Strings are respected so a
    value containing // (a URL, say) survives.
    """
    out = []
    for line in text.splitlines():
        in_string = False
        escaped = False
        cut = None
        for i, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
            elif char == '"':
                in_string = not in_string
            elif char == "/" and not in_string and line[i : i + 2] == "//":
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def normalise_rule(rule: str) -> str:
    """`Edit(./docs/**)` and `Edit(docs/**)` are the same rule written two ways.

    Only the leading `./` inside the parentheses is collapsed — nothing else is
    treated as equivalent, because guessing at glob equivalence would let a
    genuinely weaker rule pass as a stronger one.
    """
    rule = rule.strip()
    return re.sub(r"\((\./)+", "(", rule)


def load_settings(path: Path) -> tuple[dict | None, str | None]:
    try:
        text = path.read_text()
    except OSError as exc:
        return None, f"could not read {path}: {exc}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(strip_jsonc(text)), None
    except json.JSONDecodeError as exc:
        return None, f"{path} is not valid JSON: {exc}"


HOOK_SCRIPT = "qa_report_check.py"


def check_subagent_stop_hook(settings: dict) -> list[str]:
    """Assert a SubagentStop hook runs the shared report check for qa-tester.

    Matched on the script filename rather than the whole command, so a project
    is free to add flags or change how python is invoked. A hook wired to a
    per-project copy of the script instead of the submodule path still passes
    the filename test — that trade is deliberate: this is a check that the
    control exists, and docs/supply-chain.md § "Shared tooling scripts" is the
    argument for where it should live.
    """
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    matchers = hooks.get("SubagentStop")
    if not isinstance(matchers, list):
        matchers = []

    for matcher in matchers:
        if not isinstance(matcher, dict):
            continue
        if str(matcher.get("matcher", "")) not in ("qa-tester", "*", ""):
            continue
        for hook in matcher.get("hooks") or []:
            if isinstance(hook, dict) and HOOK_SCRIPT in str(hook.get("command", "")):
                return []

    return [
        f"no SubagentStop hook for `qa-tester` running {HOOK_SCRIPT} — without "
        "it, 'never report a pass you did not run' and 'declare every file you "
        "wrote' stay prompt-level promises on the one subagent holding Bash. "
        "See .standards/docs/subagents.md § 'Required project configuration'"
    ]


def check_settings(settings: dict) -> list[str]:
    problems = []

    # Check the raw value's type before coercing: `[] or {}` is `{}`, which
    # would let a malformed block pass as an empty-but-valid one.
    permissions = settings.get("permissions", {})
    if permissions is None:
        permissions = {}
    if not isinstance(permissions, dict):
        return ["`permissions` is not an object"]

    raw_deny = permissions.get("deny", [])
    if raw_deny is None:
        raw_deny = []
    if not isinstance(raw_deny, list):
        return ["`permissions.deny` is not a list"]
    deny = {normalise_rule(str(rule)) for rule in raw_deny}

    for rule in REQUIRED_DENIES:
        if rule not in deny:
            problems.append(f"missing deny rule {rule!r} — {RATIONALE[rule]}")

    # An allow entry never substitutes for a deny. Flag the specific mistake
    # docs/subagents.md calls out, since it reads like a restriction.
    allow = {normalise_rule(str(rule)) for rule in (permissions.get("allow") or [])}
    for rule in allow:
        if rule.startswith(("WebFetch(", "WebSearch(")):
            problems.append(
                f"allow rule {rule!r} looks like an egress allowlist and is not "
                "one — an allow entry auto-approves and restricts nothing. To "
                "restrict, deny it or do not grant the tool in the frontmatter."
            )

    problems.extend(check_subagent_stop_hook(settings))

    sandbox = settings.get("sandbox")
    enabled = isinstance(sandbox, dict) and sandbox.get("enabled") is True
    if not enabled:
        problems.append(
            'missing `"sandbox": {"enabled": true}` — the only layer enforced '
            "for Bash child processes, so the only one that stops a test "
            "subprocess reading .env itself"
        )

    return problems


def main_argv(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path(".claude/settings.json"),
        help="path to the project's settings file (default: .claude/settings.json)",
    )
    args = parser.parse_args(argv)

    if not args.settings.exists():
        print(
            f"{args.settings} does not exist. The subagent set in .standards/agents/ "
            "requires it — see .standards/docs/subagents.md "
            "§ 'Required project configuration'.",
            file=sys.stderr,
        )
        return 1

    settings, error = load_settings(args.settings)
    if error:
        print(error, file=sys.stderr)
        return 1

    problems = check_settings(settings)
    if problems:
        print(f"{args.settings}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nSee .standards/docs/subagents.md § 'Required project "
            "configuration' for the full block.",
            file=sys.stderr,
        )
        return 1

    print(f"{args.settings}: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_argv())
