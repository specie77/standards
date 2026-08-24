"""Tests for tools/check_agent_settings.py.

This script is executed by every project that vendors this repo as a
.standards submodule, and it is the only thing verifying those projects
actually applied the permission rules the subagent set depends on. A regression
here fails open — it would report "ok" on an unprotected project, everywhere at
once, with nothing failing anywhere.

So each test asserts a specific requirement *fires* on a settings file that
omits it, not merely that a good file passes.
"""

import json

import check_agent_settings as cas
import pytest

GOOD_SETTINGS = {
    "permissions": {
        "deny": [
            "Read(./.env)",
            "Read(./**/.env)",
            "Edit(./.standards/**)",
            "Edit(./.github/**)",
            "Edit(./CLAUDE.md)",
            "Edit(./.claude/**)",
            "Agent(general-purpose)",
            "Agent(claude)",
        ]
    },
    "sandbox": {"enabled": True},
    "hooks": {
        "SubagentStop": [
            {
                "matcher": "qa-tester",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/qa_report_check.py --check qa-report",
                    }
                ],
            }
        ]
    },
}


def write(tmp_path, settings, name="settings.json"):
    path = tmp_path / name
    path.write_text(
        settings if isinstance(settings, str) else json.dumps(settings, indent=2)
    )
    return path


def test_complete_settings_pass():
    assert cas.check_settings(GOOD_SETTINGS) == []


@pytest.mark.parametrize("rule", cas.REQUIRED_DENIES)
def test_each_required_deny_is_enforced(rule):
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["permissions"]["deny"] = [
        r for r in settings["permissions"]["deny"] if cas.normalise_rule(r) != rule
    ]
    problems = cas.check_settings(settings)
    assert any(rule in p for p in problems), f"removing {rule} was not caught"


def test_missing_claude_deny_names_itself_as_critical():
    """Edit(./.claude/**) is the one whose absence undoes the others — the
    failure message has to say so, or it reads as one more path in a list."""
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["permissions"]["deny"].remove("Edit(./.claude/**)")
    problems = cas.check_settings(settings)
    assert any("CRITICAL" in p for p in problems)


def test_sandbox_required():
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    del settings["sandbox"]
    assert any("sandbox" in p for p in cas.check_settings(settings))


@pytest.mark.parametrize("value", [False, "true", None, {}])
def test_sandbox_must_be_literally_true(value):
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["sandbox"] = {"enabled": value}
    assert any("sandbox" in p for p in cas.check_settings(settings))


def test_empty_settings_reports_everything():
    problems = cas.check_settings({})
    assert len(problems) == len(cas.REQUIRED_DENIES) + 2  # + sandbox, + hook


def test_allow_entry_never_satisfies_a_deny():
    """An allow entry auto-approves; it restricts nothing. Listing the required
    rules under allow must not pass."""
    settings = {
        "permissions": {"allow": GOOD_SETTINGS["permissions"]["deny"]},
        "sandbox": {"enabled": True},
    }
    problems = cas.check_settings(settings)
    assert len(problems) == len(cas.REQUIRED_DENIES) + 1  # + hook


def test_webfetch_allow_is_flagged_as_not_a_restriction():
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["permissions"]["allow"] = ["WebFetch(domain:docs.python.org)"]
    problems = cas.check_settings(settings)
    assert any("restricts nothing" in p for p in problems)


def test_malformed_permissions_block_is_reported():
    assert cas.check_settings({"permissions": []}) == ["`permissions` is not an object"]
    assert cas.check_settings({"permissions": {"deny": "everything"}}) == [
        "`permissions.deny` is not a list"
    ]


# --- rule normalisation ----------------------------------------------------


@pytest.mark.parametrize(
    "written,normalised",
    [
        ("Edit(./docs/**)", "Edit(docs/**)"),
        ("Edit(docs/**)", "Edit(docs/**)"),
        ("  Read(./.env)  ", "Read(.env)"),
    ],
)
def test_leading_dot_slash_is_equivalent(written, normalised):
    assert cas.normalise_rule(written) == normalised


def test_a_weaker_glob_is_not_accepted_as_the_required_rule():
    """Only `./` is collapsed. Guessing at glob equivalence would let a weaker
    rule pass as a stronger one."""
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["permissions"]["deny"].remove("Edit(./.claude/**)")
    settings["permissions"]["deny"].append("Edit(./.claude/settings.json)")
    assert any("Edit(.claude/**)" in p for p in cas.check_settings(settings))


# --- file loading ----------------------------------------------------------


def test_jsonc_comments_are_tolerated(tmp_path):
    """docs/subagents.md presents the block as jsonc, so a project may well
    have copied the comments with it."""
    text = """{
      "permissions": {
        "deny": [
          "Read(./.env)",
          "Read(./**/.env)",
          "Edit(./.standards/**)",   // upstream standards
          "Edit(./.github/**)",      // CI config
          "Edit(./CLAUDE.md)",
          "Edit(./.claude/**)",      // the enforcement layer itself
          "Agent(general-purpose)",
          "Agent(claude)"
        ]
      },
      "sandbox": { "enabled": true },       // OS-level
      "hooks": {
        "SubagentStop": [
          { "matcher": "qa-tester",
            "hooks": [{ "type": "command",
                        "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/qa_report_check.py" }] }
        ]
      }
    }"""
    settings, error = cas.load_settings(write(tmp_path, text))
    assert error is None
    assert cas.check_settings(settings) == []


def test_a_double_slash_inside_a_string_survives_comment_stripping():
    text = '{"url": "https://example.com", "sandbox": {"enabled": true}}'
    assert json.loads(cas.strip_jsonc(text))["url"] == "https://example.com"


def test_invalid_json_is_reported(tmp_path):
    settings, error = cas.load_settings(write(tmp_path, "{not json"))
    assert settings is None and "not valid JSON" in error


# --- the SubagentStop hook -------------------------------------------------


def test_missing_subagent_stop_hook_is_caught():
    """Wiring the hook is a manual per-project step, so it needs the same
    treatment as the deny rules — otherwise the two report promises it checks
    stay promises on the one subagent holding Bash."""
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    del settings["hooks"]
    problems = cas.check_settings(settings)
    assert any("SubagentStop" in p for p in problems)


def test_hook_for_another_subagent_does_not_satisfy_it():
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["hooks"]["SubagentStop"][0]["matcher"] = "business-analyst"
    assert any("SubagentStop" in p for p in cas.check_settings(settings))


def test_wildcard_matcher_satisfies_it():
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["hooks"]["SubagentStop"][0]["matcher"] = "*"
    assert cas.check_settings(settings) == []


def test_a_different_script_does_not_satisfy_it():
    """A hook that runs something else is not this check, however plausible
    the filename."""
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["hooks"]["SubagentStop"][0]["hooks"][0]["command"] = (
        ".claude/hooks/qa-report-check.sh"
    )
    assert any("SubagentStop" in p for p in cas.check_settings(settings))


def test_extra_flags_on_the_hook_command_are_allowed():
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["hooks"]["SubagentStop"][0]["hooks"][0]["command"] += " --strict"
    assert cas.check_settings(settings) == []


@pytest.mark.parametrize("hooks", [None, [], "nonsense", {"SubagentStop": "x"}])
def test_malformed_hooks_block_is_caught_not_crashed(hooks):
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["hooks"] = hooks
    assert any("SubagentStop" in p for p in cas.check_settings(settings))


# --- main() ----------------------------------------------------------------


def test_main_passes_on_good_settings(tmp_path):
    path = write(tmp_path, GOOD_SETTINGS)
    assert cas.main_argv(["--settings", str(path)]) == 0


def test_success_output_says_sandbox_is_not_a_verified_boundary(tmp_path, capsys):
    """An `ok` here means the file declares the right things. It cannot mean the
    sandbox boundary exists — this script reads a file, and enforcement happens
    somewhere it cannot see. Printing that on every green run stops the check
    implying a protection it never verified."""
    path = write(tmp_path, GOOD_SETTINGS)
    cas.main_argv(["--settings", str(path)])
    out = capsys.readouterr().out
    assert "not a verified" in out
    assert "VS Code" in out


def test_main_fails_on_incomplete_settings(tmp_path, capsys):
    settings = json.loads(json.dumps(GOOD_SETTINGS))
    settings["permissions"]["deny"].remove("Edit(./.claude/**)")
    path = write(tmp_path, settings)
    assert cas.main_argv(["--settings", str(path)]) == 1
    assert "Edit(.claude/**)" in capsys.readouterr().err


def test_main_fails_when_settings_absent(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert cas.main_argv(["--settings", str(missing)]) == 1
    assert "does not exist" in capsys.readouterr().err
