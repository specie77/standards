"""Tests for tools/qa_report_check.py.

This script runs as a SubagentStop hook in every project that vendors this repo
as a .standards submodule. A regression here fails open — the hook returns 0, the
subagent stops, and nothing anywhere reports that the check stopped working. So
each test asserts a specific rule *fires* on a report that breaks it, not merely
that a good report passes.

The fail-open behaviour is itself tested, in both directions: it is a deliberate
design choice (a hook that wedges the session gets deleted, which fails open
permanently), and --strict must actually invert it.
"""

import io
import json

import pytest
import qa_report_check as qrc

GOOD_REPORT = """
## Verdict
PASS WITH DEFECTS — two S3 defects, no blocker.

## Execution
Command: python -m pytest tests/ -q   Result: 41 passed, 2 failed, 0 skipped

## Files I changed
- tests/test_invoice_export.py — created — covers FR-001 boundaries

## Defects raised
- DEF-001 (S3): rounding on zero-total invoice — violates FR-004

## Open Questions
1. No staging credentials — blocks TC-018.
"""


def payload(**kwargs):
    return io.StringIO(json.dumps(kwargs))


def run(argv, **payload_kwargs):
    return qrc.main_argv(argv, stdin=payload(**payload_kwargs))


def transcript(tmp_path, *messages, name="transcript.jsonl"):
    """A JSONL transcript in the shape the hook payload points at."""
    path = tmp_path / name
    lines = []
    for role, text in messages:
        lines.append(
            json.dumps(
                {
                    "type": role,
                    "message": {
                        "role": role,
                        "content": [{"type": "text", "text": text}],
                    },
                }
            )
        )
    path.write_text("\n".join(lines) + "\n")
    return path


# --- the qa-report check ------------------------------------------------


def test_good_report_passes():
    assert qrc.check_qa_report(GOOD_REPORT) == []


def test_pass_without_a_command_is_rejected():
    """qa-tester.md rule 3: never summarize a suite you did not execute. A pass
    with no command recorded is the exact shape of that violation."""
    report = GOOD_REPORT.replace(
        "Command: python -m pytest tests/ -q   Result: 41 passed, 2 failed, 0 skipped",
        "Result: everything looks good",
    )
    problems = qrc.check_qa_report(report)
    assert any("Command:" in p for p in problems)


def test_plain_pass_without_a_command_is_rejected():
    """PASS must be matched as well as PASS WITH DEFECTS."""
    report = "## Verdict\nPASS\n\n## Files I changed\n- None\n"
    problems = qrc.check_qa_report(report)
    assert any("Command:" in p for p in problems)


@pytest.mark.parametrize("placeholder", ["<exact command>", "TBD", "n/a", "—", ""])
def test_template_placeholder_is_not_a_command(placeholder):
    """The report format ships with `Command: <exact command>`. Leaving the
    template in place must not satisfy the check."""
    report = f"## Verdict\nPASS\n\n## Execution\nCommand: {placeholder}\n\n## Files I changed\n- None\n"
    problems = qrc.check_qa_report(report)
    assert any("Command:" in p for p in problems)


@pytest.mark.parametrize("verdict", ["FAIL", "BLOCKED"])
def test_non_passing_verdicts_need_no_command(verdict):
    """A BLOCKED run is precisely the case where there is no command to record.
    Demanding one would push the subagent toward inventing a verdict."""
    report = f"## Verdict\n{verdict} — no test environment.\n\n## Files I changed\n- None\n"
    assert qrc.check_qa_report(report) == []


def test_missing_verdict_is_rejected():
    report = "## Execution\nCommand: pytest -q\n\n## Files I changed\n- None\n"
    problems = qrc.check_qa_report(report)
    assert any("Verdict" in p for p in problems)


def test_unrecognised_verdict_word_is_rejected():
    report = "## Verdict\nLooks fine to me\n\n## Files I changed\n- None\n"
    problems = qrc.check_qa_report(report)
    assert any("Verdict" in p for p in problems)


def test_missing_files_changed_section_is_rejected():
    """Rule 10. This is the one that makes the `git diff` review possible, so
    its absence has to block — it is the only control on a Bash-holding
    subagent quietly editing product source."""
    report = GOOD_REPORT.replace(
        "## Files I changed\n- tests/test_invoice_export.py — created — covers FR-001 boundaries\n",
        "",
    )
    problems = qrc.check_qa_report(report)
    assert any("Files I changed" in p for p in problems)
    assert any("git diff" in p for p in problems)


def test_empty_files_changed_section_is_rejected():
    report = "## Verdict\nFAIL\n\n## Files I changed\n\n## Open Questions\n1. none\n"
    problems = qrc.check_qa_report(report)
    assert any("empty" in p for p in problems)


def test_files_changed_none_is_accepted():
    report = "## Verdict\nFAIL — suite red on main.\n\n## Files I changed\n- None\n"
    assert qrc.check_qa_report(report) == []


def test_bold_verdict_is_recognised():
    """Subagents format headings and emphasis inconsistently; the check must not
    turn a cosmetic difference into a block."""
    report = "## Verdict\n**FAIL** — three S1 defects.\n\n### Files I changed\n- None\n"
    assert qrc.check_qa_report(report) == []


# --- the TBD check ------------------------------------------------------


def test_tbd_in_a_requirements_file_is_rejected(tmp_path):
    (tmp_path / "10-functional-requirements.md").write_text(
        "## FR-001\n**Requirement:** Retention period is TBD.\n"
    )
    problems = qrc.check_forbid_tbd(["*.md"], tmp_path)
    assert len(problems) == 1
    assert "line 2" in problems[0]
    assert "Open Questions" in problems[0]


def test_tbd_substring_is_not_a_hit(tmp_path):
    """Word boundaries: a word merely containing the letters must not fire."""
    (tmp_path / "spec.md").write_text("The TBDX identifier and tbdial are fine.\n")
    assert qrc.check_forbid_tbd(["*.md"], tmp_path) == []


def test_clean_requirements_file_passes(tmp_path):
    (tmp_path / "spec.md").write_text("## FR-001\n**Requirement:** 30 days.\n")
    assert qrc.check_forbid_tbd(["*.md"], tmp_path) == []


def test_glob_matching_no_files_is_not_a_failure(tmp_path):
    """A project that has not written requirements yet is not in violation."""
    assert qrc.check_forbid_tbd(["docs/delivery/*.md"], tmp_path) == []


def test_multiple_tbd_lines_are_summarised(tmp_path):
    (tmp_path / "spec.md").write_text("\n".join(f"line {i} TBD" for i in range(1, 9)))
    problems = qrc.check_forbid_tbd(["*.md"], tmp_path)
    assert "+3 more" in problems[0]


# --- exit codes and the hook payload ------------------------------------


def test_good_report_exits_zero(tmp_path):
    path = tmp_path / "report.md"
    path.write_text(GOOD_REPORT)
    assert run(["--report-file", str(path)]) == qrc.EXIT_OK


def test_bad_report_exits_two(tmp_path, capsys):
    """2 is the code claimed to block the subagent from stopping. If this ever
    returns 1, the hook reports an error and the stop proceeds anyway."""
    path = tmp_path / "report.md"
    path.write_text("## Verdict\nPASS\n")
    assert run(["--report-file", str(path)]) == qrc.EXIT_BLOCK
    assert "rejected" in capsys.readouterr().err


def test_failure_message_names_the_agent_from_the_payload(tmp_path, capsys):
    path = tmp_path / "report.md"
    path.write_text("## Verdict\nPASS\n")
    qrc.main_argv(
        ["--report-file", str(path)], stdin=payload(agent_type="qa-tester")
    )
    assert "qa-tester report rejected" in capsys.readouterr().err


def test_report_is_read_from_the_transcript(tmp_path):
    path = transcript(
        tmp_path,
        ("user", "run the suite"),
        ("assistant", "starting"),
        ("assistant", GOOD_REPORT),
    )
    assert run([], transcript_path=str(path)) == qrc.EXIT_OK


def test_last_assistant_message_wins(tmp_path):
    """The final report is the last assistant turn; an earlier draft that looked
    complete must not satisfy the check for a later one that does not."""
    path = transcript(tmp_path, ("assistant", GOOD_REPORT), ("assistant", "done!"))
    assert run([], transcript_path=str(path)) == qrc.EXIT_BLOCK


def test_user_messages_are_ignored(tmp_path):
    path = transcript(tmp_path, ("assistant", GOOD_REPORT), ("user", "thanks"))
    assert run([], transcript_path=str(path)) == qrc.EXIT_OK


def test_malformed_transcript_lines_are_skipped(tmp_path):
    path = transcript(tmp_path, ("assistant", GOOD_REPORT))
    path.write_text("not json\n\n" + path.read_text() + "{broken\n")
    assert run([], transcript_path=str(path)) == qrc.EXIT_OK


def test_string_content_is_understood(tmp_path):
    """Transcript shape is unverified, so both a bare string and a block list
    have to parse — a format difference must not silently skip the check."""
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": GOOD_REPORT}}) + "\n")
    assert run([], transcript_path=str(path)) == qrc.EXIT_OK


def test_forbid_tbd_runs_against_the_payload_cwd(tmp_path):
    (tmp_path / "spec.md").write_text("Retention: TBD\n")
    code = qrc.main_argv(
        ["--check", "none", "--forbid-tbd", "*.md"],
        stdin=payload(cwd=str(tmp_path)),
    )
    assert code == qrc.EXIT_BLOCK


def test_check_none_skips_the_report_check(tmp_path):
    """A business-analyst matcher has no QA report to assert a shape on."""
    code = qrc.main_argv(
        ["--check", "none", "--forbid-tbd", "*.md"], stdin=payload(cwd=str(tmp_path))
    )
    assert code == qrc.EXIT_OK


# --- fail-open behaviour ------------------------------------------------


def test_missing_transcript_path_fails_open(capsys):
    assert run([]) == qrc.EXIT_OK
    assert "check skipped" in capsys.readouterr().err


def test_unreadable_transcript_fails_open(tmp_path, capsys):
    assert run([], transcript_path=str(tmp_path / "nope.jsonl")) == qrc.EXIT_OK
    assert "no assistant message" in capsys.readouterr().err


def test_transcript_with_no_assistant_message_fails_open(tmp_path):
    path = transcript(tmp_path, ("user", "hello"))
    assert run([], transcript_path=str(path)) == qrc.EXIT_OK


def test_empty_stdin_fails_open():
    assert qrc.main_argv([], stdin=io.StringIO("")) == qrc.EXIT_OK


def test_unparseable_stdin_fails_open():
    assert qrc.main_argv([], stdin=io.StringIO("{not json")) == qrc.EXIT_OK


def test_strict_blocks_where_default_fails_open():
    assert qrc.main_argv(["--strict"], stdin=io.StringIO("")) == qrc.EXIT_BLOCK


def test_stop_hook_active_never_blocks(tmp_path):
    """Guard against an infinite loop: the hook fires on the stop it blocked."""
    path = tmp_path / "report.md"
    path.write_text("## Verdict\nPASS\n")
    code = qrc.main_argv(
        ["--report-file", str(path)], stdin=payload(stop_hook_active=True)
    )
    assert code == qrc.EXIT_OK
