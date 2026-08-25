"""Tests for tools/lint_agents.py.

This linter is the only thing validating the subagent definitions in agents/ —
`claude plugin validate` exits 0 on a bare agents directory whatever it
contains. Those definitions ship to every project that vendors this repo as a
.standards submodule, so a rule that silently stops firing takes the guarantee
with it in every project at once, with nothing failing anywhere.

Each test therefore asserts a specific rule *fires*, not merely that the real
files pass today. A check that passes because it stopped looking is the failure
mode worth catching.
"""

import textwrap

import lint_agents
import pytest

GOOD = """\
---
name: probe-agent
description: A probe subagent definition long enough to drive automatic delegation.
tools: Read, Write, Edit, Glob, Grep
model: sonnet
color: green
---

Body.

7. **Stay inside your owned paths.** You write only `docs/delivery/40-test-plan.md`.
"""


def write(tmp_path, text, name="probe-agent.md"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_clean_file_has_no_problems(tmp_path):
    assert lint_agents.check_file(write(tmp_path, GOOD)) == []


def test_real_definitions_pass(tmp_path):
    """The shipped agents/ directory must satisfy every rule, cross-checked
    against the artifact map they point at."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    agents = sorted((root / "agents").glob("*.md"))
    assert agents, "no agent definitions found — did agents/ move again?"

    owners = lint_agents.parse_artifact_map(root / "docs" / "delivery-artifacts.md")
    known = {a.stem for a in agents}
    for agent in agents:
        assert lint_agents.check_file(agent, known_agents=known, owners=owners) == [], (
            f"{agent.name} fails the linter"
        )


# --- frontmatter parsing ---------------------------------------------------


def test_missing_frontmatter_is_rejected(tmp_path):
    problems = lint_agents.check_file(write(tmp_path, "no frontmatter here\n"))
    assert any("no YAML frontmatter" in p for p in problems)


def test_unterminated_frontmatter_is_rejected(tmp_path):
    problems = lint_agents.check_file(write(tmp_path, "---\nname: probe-agent\n"))
    assert any("not terminated" in p for p in problems)


def test_non_key_value_line_is_rejected(tmp_path):
    text = GOOD.replace("model: sonnet", "just a bare line")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("not a `key: value` pair" in p for p in problems)


@pytest.mark.parametrize("key", sorted(lint_agents.REQUIRED_KEYS))
def test_each_required_key_is_enforced(tmp_path, key):
    text = "\n".join(
        line for line in GOOD.splitlines() if not line.startswith(f"{key}:")
    )
    problems = lint_agents.check_file(write(tmp_path, text + "\n"))
    assert any("missing required key" in p and key in p for p in problems)


# --- name ------------------------------------------------------------------


def test_name_must_be_kebab_case(tmp_path):
    text = GOOD.replace("name: probe-agent", "name: Probe Agent")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("kebab-case" in p for p in problems)


def test_name_must_match_filename_stem(tmp_path):
    problems = lint_agents.check_file(write(tmp_path, GOOD, name="other-name.md"))
    assert any("does not match filename stem" in p for p in problems)


# --- model, colour, description --------------------------------------------


def test_invalid_model_is_rejected(tmp_path):
    text = GOOD.replace("model: sonnet", "model: gpt-4")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("model 'gpt-4'" in p for p in problems)


@pytest.mark.parametrize("model", sorted(lint_agents.VALID_MODEL_ALIASES))
def test_every_alias_is_accepted(tmp_path, model):
    """`fable` was missing from this set, so the linter rejected a legitimate
    definition. Parametrising over the constant means a future alias is added
    in one place."""
    text = GOOD.replace("model: sonnet", f"model: {model}")
    assert lint_agents.check_file(write(tmp_path, text)) == []


@pytest.mark.parametrize(
    "model", ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"]
)
def test_full_model_ids_are_accepted(tmp_path, model):
    """The frontmatter accepts a pinned model ID, not only an alias. Rejecting
    one is the same failure as rejecting `fable`: a valid config that CI stops."""
    text = GOOD.replace("model: sonnet", f"model: {model}")
    assert lint_agents.check_file(write(tmp_path, text)) == []


@pytest.mark.parametrize(
    "model",
    [
        "sonnett",            # typo'd alias
        "claude_opus_5",      # underscores, not the documented shape
        "Claude-Opus-5",      # capitalised
        "opus-5",             # missing the claude- prefix
        "claude-",            # prefix alone
        "gpt-4",              # another provider
    ],
)
def test_model_shapes_that_are_not_valid_are_still_rejected(tmp_path, model):
    """Accepting full IDs by shape must not turn the check into a no-op — these
    are the realistic typos it still has to catch."""
    text = GOOD.replace("model: sonnet", f"model: {model}")
    assert any(
        "model" in p for p in lint_agents.check_file(write(tmp_path, text))
    ), f"{model!r} was accepted"


def test_invalid_color_is_rejected(tmp_path):
    text = GOOD.replace("color: green", "color: chartreuse")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("color 'chartreuse'" in p for p in problems)


def test_short_description_is_rejected(tmp_path):
    text = GOOD.replace(GOOD.split("\n")[2], "description: Too short.")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("description is too short" in p for p in problems)


# --- memory: prohibited outright -------------------------------------------


@pytest.mark.parametrize("value", ["project", "user", "local", "anything"])
def test_memory_is_prohibited_whatever_its_value(tmp_path, value):
    """Not "must be a valid value" — prohibited. MEMORY.md is injected into the
    SYSTEM prompt and the subagent can write it, so this is a persistent
    prompt-injection vector (docs/subagents.md). `project` additionally commits
    to git, reaching every clone."""
    text = GOOD.replace("color: green", f"color: green\nmemory: {value}")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("prohibited" in p for p in problems)


# --- tool grants -----------------------------------------------------------


def test_unknown_tool_is_rejected(tmp_path):
    text = GOOD.replace("tools: Read", "tools: Telepathy, Read")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("unknown tool 'Telepathy'" in p for p in problems)


def test_bare_agent_grant_is_rejected(tmp_path):
    text = GOOD.replace("tools: Read", "tools: Agent, Read")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("bare `Agent` grant" in p for p in problems)


def test_empty_tool_scope_is_rejected(tmp_path):
    text = GOOD.replace("tools: Read", "tools: Agent(), Read")
    problems = lint_agents.check_file(write(tmp_path, text))
    assert any("empty scope" in p for p in problems)


def test_agent_scope_naming_a_missing_subagent_is_rejected(tmp_path):
    """A typo'd scope is not a safe failure: it names an agent that does not
    exist, so the restriction it appears to express is not the one in force."""
    text = GOOD.replace("tools: Read", "tools: Agent(qa-testers), Read")
    problems = lint_agents.check_file(
        write(tmp_path, text), known_agents={"qa-tester"}
    )
    assert any("Agent(qa-testers) names no subagent" in p for p in problems)


def test_agent_scope_naming_a_real_subagent_passes(tmp_path):
    text = GOOD.replace("tools: Read", "tools: Agent(qa-tester), Read")
    problems = lint_agents.check_file(
        write(tmp_path, text), known_agents={"qa-tester", "probe-agent"}
    )
    assert problems == []


def test_agent_scope_unchecked_when_known_agents_absent(tmp_path):
    text = GOOD.replace("tools: Read", "tools: Agent(whoever), Read")
    assert lint_agents.check_file(write(tmp_path, text)) == []


# --- artifact map cross-check ----------------------------------------------

MAP = textwrap.dedent("""\
    | Path | Owner | Format |
    |---|---|---|
    | `docs/delivery/40-test-plan.md` | probe-agent | markdown |
    | `docs/delivery/21-architecture.md` | other-agent | markdown |
    | `docs/delivery/adr/ADR-NNNN-<slug>.md` | other-agent | markdown |
    | `README.md` | nobody | markdown |
    """)


@pytest.fixture
def owners(tmp_path):
    path = tmp_path / "delivery-artifacts.md"
    path.write_text(MAP)
    return lint_agents.parse_artifact_map(path)


def test_artifact_map_parses_only_delivery_paths(owners):
    assert owners == {
        "docs/delivery/40-test-plan.md": "probe-agent",
        "docs/delivery/21-architecture.md": "other-agent",
        "docs/delivery/adr/": "other-agent",
    }


def test_templated_filename_collapses_to_its_directory():
    assert (
        lint_agents.normalise_artifact_path("docs/delivery/adr/ADR-NNNN-<slug>.md")
        == "docs/delivery/adr/"
    )
    assert lint_agents.normalise_artifact_path("docs/delivery/adr/*") == (
        "docs/delivery/adr/"
    )


def test_owned_paths_matching_the_map_pass(tmp_path, owners):
    assert lint_agents.check_file(write(tmp_path, GOOD), owners=owners) == []


def test_claiming_another_subagents_artifact_is_rejected(tmp_path, owners):
    text = GOOD.replace(
        "docs/delivery/40-test-plan.md", "docs/delivery/21-architecture.md"
    )
    problems = lint_agents.check_file(write(tmp_path, text), owners=owners)
    assert any("assigns to 'other-agent'" in p for p in problems)


def test_not_listing_an_assigned_artifact_is_rejected(tmp_path, owners):
    text = GOOD.replace(
        "You write only `docs/delivery/40-test-plan.md`.", "You write nothing."
    )
    problems = lint_agents.check_file(write(tmp_path, text), owners=owners)
    assert any("does not list it" in p for p in problems)


def test_missing_owned_paths_rule_is_rejected(tmp_path, owners):
    text = "\n".join(
        line for line in GOOD.splitlines() if "owned paths" not in line
    )
    problems = lint_agents.check_file(write(tmp_path, text + "\n"), owners=owners)
    assert any("no owned-paths rule found" in p for p in problems)


def test_map_check_skipped_when_owners_absent(tmp_path):
    text = "\n".join(
        line for line in GOOD.splitlines() if "owned paths" not in line
    )
    assert lint_agents.check_file(write(tmp_path, text + "\n")) == []


# --- main() ----------------------------------------------------------------


def test_main_fails_when_a_file_is_bad(tmp_path, capsys):
    write(tmp_path, GOOD.replace("model: sonnet", "model: gpt-4"))
    assert lint_agents.main_argv([str(tmp_path)]) == 1


def test_main_passes_on_a_clean_directory(tmp_path):
    write(tmp_path, GOOD)
    assert lint_agents.main_argv([str(tmp_path)]) == 0


def test_main_skips_readme_files(tmp_path):
    """agents/ should hold definitions only, but a README landing there must not
    be linted as one — it has no frontmatter and would fail."""
    (tmp_path / "README-agents.md").write_text("# Not an agent\n")
    write(tmp_path, GOOD)
    assert lint_agents.main_argv([str(tmp_path)]) == 0


def test_main_fails_on_an_empty_directory(tmp_path, capsys):
    assert lint_agents.main_argv([str(tmp_path)]) == 1
    assert "no agent definitions found" in capsys.readouterr().err


def test_main_fails_when_the_artifact_map_is_missing(tmp_path, capsys):
    write(tmp_path, GOOD)
    code = lint_agents.main_argv(
        [str(tmp_path), "--artifact-map", str(tmp_path / "nope.md")]
    )
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_main_fails_when_the_artifact_map_parses_to_nothing(tmp_path, capsys):
    """A table-format change must fail loudly. Parsing zero rows and carrying on
    would leave the cross-check silently passing forever."""
    write(tmp_path, GOOD)
    empty = tmp_path / "empty-map.md"
    empty.write_text("# Delivery Artifacts\n\nNo table here.\n")
    code = lint_agents.main_argv([str(tmp_path), "--artifact-map", str(empty)])
    assert code == 1
    assert "no artifact map rows parsed" in capsys.readouterr().err
