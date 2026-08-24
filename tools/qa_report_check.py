#!/usr/bin/env python3
"""SubagentStop hook: reject a subagent's final report that breaks the two
promises its prompt makes but cannot keep on its own.

Why this exists.

`docs/subagents.md` § "Required project configuration" documents a
`SubagentStop` hook and credits it with turning two prompt-level promises into
checks — the same move this repo made when it replaced "remember to regenerate
the SBOM" with a CI freshness check. The script it named never existed, so both
promises stayed prompt-level (issue #8). This is that script, shared from
`tools/` and invoked from the submodule path rather than copied per project,
per `docs/supply-chain.md` § "Shared tooling scripts".

The two checks, and why each is worth a hook rather than a sentence in a prompt:

  qa-tester's verdict (--check qa-report)
      `qa-tester.md` rule 3 forbids reporting a pass it did not observe, and
      rule 10 requires declaring every file it wrote. Both are unenforceable
      from inside the prompt: a subagent that skipped the suite and a subagent
      that ran it produce identical-looking reports, and the one that quietly
      fixed product source to make a test go green is the one least likely to
      mention it. This asserts the report carries the shape those rules
      require — a verdict, an exact command behind any pass, and a
      `## Files I changed` section.

      It cannot verify the command was really run. Nothing at this layer can.
      What it removes is the silent omission: a pass with no command, or a
      session with no declared writes, now has to be an explicit lie rather
      than a blank space. Pair it with the `git diff` review that
      `docs/subagents.md` names as the actual control for writes.

  business-analyst's TBD (--forbid-tbd)
      `business-analyst.md` rule 1 bans placeholder language; a requirement
      reading "retention: TBD" is exactly the untestable requirement the role
      exists to prevent, and rule 2 says it belongs in `## Open Questions`
      instead. Checked against the files on disk, so it holds regardless of
      what the report claims.

Failure mode, deliberately chosen: this **fails open** on anything that is not
a genuine check failure — no payload on stdin, an unreadable transcript, no
assistant message found. A hook that blocks a subagent from stopping because of
its own bug wedges the session, and a wedged session gets the hook deleted,
which fails open permanently and silently. Failing open loudly (a warning on
stderr) keeps the check installed. Pass --strict to invert this where a
consuming project would rather block than proceed unchecked.

UNVERIFIED CONTRACT. Every mechanical claim this script is built on is listed
in `docs/subagents.md` § "Mechanical claims — verification status" and is
currently marked Not verified, because the `claude` CLI was unavailable in the
sessions that wrote it (issue #9): that exit code 2 blocks the subagent from
stopping and returns stderr to it, that the matcher filters on `agent_type`,
that the payload carries `transcript_path` and `stop_hook_active`, and the
shape of the transcript JSONL. The parsing here is deliberately tolerant of all
of that, and every unmet assumption lands in the fail-open path rather than
blocking. Re-verify before relying on it unattended.

Stdlib only, so a consuming project needs no dependencies.

Usage, in a project that vendors this repo at .standards/:

    {
      "hooks": {
        "SubagentStop": [
          { "matcher": "qa-tester",
            "hooks": [{ "type": "command",
                        "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/qa_report_check.py --check qa-report" }] },
          { "matcher": "business-analyst",
            "hooks": [{ "type": "command",
                        "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/qa_report_check.py --check none --forbid-tbd 'docs/delivery/1*.md' --forbid-tbd 'docs/delivery/30-*.md'" }] }
        ]
      }
    }
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Claimed semantics: 2 blocks the subagent from stopping and feeds stderr back
# to it so it can correct the report. Unverified — see the module docstring.
EXIT_BLOCK = 2
EXIT_OK = 0

VERDICTS = ("PASS WITH DEFECTS", "PASS", "FAIL", "BLOCKED")
PASSING_VERDICTS = ("PASS", "PASS WITH DEFECTS")

VERDICT_HEADING_RE = re.compile(r"^\s*#{1,6}\s*Verdict\s*$", re.MULTILINE)
# Same line only — `[^\S\n]*`, never `\s*`, which would cross the newline and
# capture the next heading as if it were the command.
COMMAND_RE = re.compile(
    r"^[^\S\n]*(?:\*\*)?Command:?(?:\*\*)?[^\S\n]*(?P<cmd>.*)$", re.MULTILINE
)
FILES_HEADING_RE = re.compile(r"^\s*#{1,6}\s*Files I changed\s*$", re.MULTILINE)
HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S", re.MULTILINE)

# A value that is still the template rather than a real answer: <exact command>,
# TBD, N/A, a bare dash, or nothing at all.
PLACEHOLDER_RE = re.compile(r"^(?:<[^>]*>|tbd|n/?a|none|-{1,3}|—|\.{3}|)$", re.IGNORECASE)

TBD_RE = re.compile(r"\bTBD\b")


def _text_blocks(content) -> list[str]:
    """Pull text out of a message `content`, which may be a string or a list of
    typed blocks. Unknown shapes yield nothing rather than raising."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if isinstance(block, str):
            out.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                out.append(text)
    return out


def last_assistant_text(transcript: Path) -> str | None:
    """Return the last non-empty assistant message in a JSONL transcript.

    On a SubagentStop that is the subagent's final report. Malformed lines are
    skipped rather than fatal: a transcript format change must not turn this
    hook into a session-wedging error (see the docstring's failure mode).
    """
    found = None
    try:
        with transcript.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                message = entry.get("message")
                message = message if isinstance(message, dict) else entry
                role = message.get("role") or entry.get("type")
                if role != "assistant":
                    continue
                text = "\n".join(_text_blocks(message.get("content"))).strip()
                if text:
                    found = text
    except OSError:
        return None
    return found


def section_body(report: str, heading_match: re.Match) -> str:
    """The text between a heading and the next heading."""
    start = heading_match.end()
    nxt = HEADING_RE.search(report, start)
    return report[start : nxt.start() if nxt else len(report)].strip()


def check_qa_report(report: str) -> list[str]:
    """Assert the report has the shape qa-tester.md rules 3 and 10 require."""
    problems = []

    verdict_match = VERDICT_HEADING_RE.search(report)
    verdict = None
    if verdict_match:
        body = section_body(report, verdict_match)
        first = body.splitlines()[0].strip().lstrip("*_ ") if body else ""
        # Longest-first, so "PASS WITH DEFECTS" is not read as "PASS".
        verdict = next((v for v in VERDICTS if first.upper().startswith(v)), None)

    if verdict is None:
        problems.append(
            "no `## Verdict` section with one of "
            f"{' | '.join(VERDICTS)} — qa-tester.md's final report format "
            "requires it, and a report with no verdict cannot be acted on"
        )

    if verdict in PASSING_VERDICTS:
        commands = [
            m.group("cmd").strip()
            for m in COMMAND_RE.finditer(report)
            if not PLACEHOLDER_RE.match(m.group("cmd").strip().strip("`"))
        ]
        if not commands:
            problems.append(
                f"verdict is {verdict} but no `Command:` line records what was "
                "actually run. qa-tester.md rule 3: never mark a test passed you "
                "did not run, never summarize a suite you did not execute. If you "
                "could not run it, the verdict is BLOCKED and the reason goes in "
                "the report"
            )

    files_match = FILES_HEADING_RE.search(report)
    if not files_match:
        problems.append(
            "no `## Files I changed` section — qa-tester.md rule 10 requires "
            "every created or modified path, including test files and fixtures. "
            "It is what makes the `git diff` review possible, which is the only "
            "actual control on a subagent that holds Bash. Write 'None' if you "
            "wrote nothing"
        )
    elif not section_body(report, files_match):
        problems.append(
            "`## Files I changed` is empty — list every path, or write 'None' "
            "explicitly (qa-tester.md rule 10)"
        )

    return problems


def check_forbid_tbd(patterns: list[str], root: Path) -> list[str]:
    """Assert no matched file contains a TBD placeholder."""
    problems = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                problems.append(f"could not read {path}: {exc}")
                continue
            hits = [
                lineno
                for lineno, line in enumerate(text.splitlines(), start=1)
                if TBD_RE.search(line)
            ]
            if hits:
                where = ", ".join(f"line {n}" for n in hits[:5])
                more = f" (+{len(hits) - 5} more)" if len(hits) > 5 else ""
                problems.append(
                    f"{path}: contains TBD at {where}{more} — "
                    "business-analyst.md rule 1 bans placeholder language and "
                    "rule 2 puts an unknown in `## Open Questions` with a "
                    "labelled proposed default, not in the requirement"
                )
    return problems


def read_payload(stream) -> dict:
    """The hook payload on stdin. Anything unparseable is an empty payload,
    which routes to the fail-open path rather than raising."""
    try:
        raw = stream.read()
    except OSError:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def fail_open(message: str, strict: bool) -> int:
    """Report a problem with the check itself. See the docstring: blocking on
    our own failure wedges the session, and a wedged session loses the hook."""
    print(
        f"qa_report_check: {message} — check skipped"
        f"{'' if strict else ' (fail-open; pass --strict to block instead)'}",
        file=sys.stderr,
    )
    return EXIT_BLOCK if strict else EXIT_OK


def main_argv(argv: list[str] | None = None, stdin=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        choices=("qa-report", "none"),
        default="qa-report",
        help="report check to run (default: qa-report). `none` runs only "
        "--forbid-tbd, for a matcher that has no report shape to assert.",
    )
    parser.add_argument(
        "--forbid-tbd",
        action="append",
        default=[],
        metavar="GLOB",
        help="fail if any file matching this glob contains TBD. Repeatable.",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        help="read the report from a file instead of the hook transcript. For "
        "testing the check without a live session.",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        help="root for --forbid-tbd globs (default: the payload's cwd, else .)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="block when the check itself cannot run, instead of failing open",
    )
    args = parser.parse_args(argv)

    payload = read_payload(stdin if stdin is not None else sys.stdin)

    # A hook that fires again on the stop it just blocked would loop forever.
    if payload.get("stop_hook_active") is True:
        return EXIT_OK

    problems = []

    if args.forbid_tbd:
        root = args.project_dir or Path(str(payload.get("cwd") or "."))
        problems.extend(check_forbid_tbd(args.forbid_tbd, root))

    if args.check == "qa-report":
        if args.report_file:
            try:
                report = args.report_file.read_text(encoding="utf-8")
            except OSError as exc:
                return fail_open(f"could not read {args.report_file}: {exc}", args.strict)
        else:
            transcript = payload.get("transcript_path")
            if not transcript:
                return fail_open(
                    "no transcript_path in the hook payload", args.strict
                )
            report = last_assistant_text(Path(str(transcript)))
            if report is None:
                return fail_open(
                    f"no assistant message found in {transcript}", args.strict
                )
        problems.extend(check_qa_report(report))

    if problems:
        agent = payload.get("agent_type") or "subagent"
        print(f"{agent} report rejected:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\nFix the report and stop again. This check is "
            ".standards/tools/qa_report_check.py; see .standards/docs/"
            "subagents.md § 'Required project configuration'.",
            file=sys.stderr,
        )
        return EXIT_BLOCK

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main_argv())
