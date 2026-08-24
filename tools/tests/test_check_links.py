"""Tests for tools/check_links.py.

The docs in this repo are consumed by cross-reference from every project that
vendors it as a .standards submodule: CLAUDE.md cites sections of
security-protocols.md, and the subagent prompts tell subagents to read specific
paths. A renamed file or a renumbered heading breaks those pointers silently —
no error is raised here or in the projects that follow them — which is what
this check exists to make loud.

So the tests assert each rule *fires* on a broken link, not merely that a good
document passes. They also pin the two behaviours that are deliberate limits
rather than bugs, because both look like bugs to a future reader: fenced code
blocks are not checked, and #Lnn line references are not treated as anchors.
"""

import check_links as cl
import pytest


def write(tmp_path, name, text):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --- link targets -------------------------------------------------------


def test_valid_relative_link_passes(tmp_path):
    write(tmp_path, "target.md", "# Target\n")
    source = write(tmp_path, "source.md", "See [the target](target.md).\n")
    assert cl.check_file(source, tmp_path) == []


def test_missing_link_target_is_reported(tmp_path):
    source = write(tmp_path, "source.md", "See [gone](does-not-exist.md).\n")
    problems = cl.check_file(source, tmp_path)
    assert any("does not exist" in p for p in problems)


def test_link_into_a_subdirectory_resolves_relative_to_the_file(tmp_path):
    write(tmp_path, "docs/deep/target.md", "# Target\n")
    source = write(tmp_path, "docs/source.md", "[t](deep/target.md)\n")
    assert cl.check_file(source, tmp_path) == []


def test_root_absolute_link_resolves_against_the_repo_root(tmp_path):
    """`/docs/x.md` means repo-root-relative, not filesystem-absolute."""
    write(tmp_path, "docs/target.md", "# Target\n")
    source = write(tmp_path, "docs/deep/source.md", "[t](/docs/target.md)\n")
    assert cl.check_file(source, tmp_path) == []


def test_link_to_a_directory_passes(tmp_path):
    (tmp_path / "agents").mkdir()
    source = write(tmp_path, "source.md", "[the agents](agents/)\n")
    assert cl.check_file(source, tmp_path) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://pypi.org/project/pip-audit/",
        "http://example.com",
        "mailto:someone@example.com",
    ],
)
def test_external_urls_are_not_checked(tmp_path, url):
    """Offline by design: fetching would make CI fail on someone else's
    downtime, which trains people to ignore this check."""
    source = write(tmp_path, "source.md", f"[x]({url})\n")
    assert cl.check_file(source, tmp_path) == []


# --- anchors ------------------------------------------------------------


def test_anchor_matching_a_heading_passes(tmp_path):
    write(tmp_path, "target.md", "# Title\n\n## Shared Tooling Scripts\n")
    source = write(tmp_path, "source.md", "[x](target.md#shared-tooling-scripts)\n")
    assert cl.check_file(source, tmp_path) == []


def test_anchor_with_no_matching_heading_is_reported(tmp_path):
    write(tmp_path, "target.md", "# Title\n")
    source = write(tmp_path, "source.md", "[x](target.md#renamed-section)\n")
    problems = cl.check_file(source, tmp_path)
    assert any("no heading matching anchor" in p for p in problems)


def test_in_page_anchor_is_checked(tmp_path):
    source = write(tmp_path, "source.md", "## Real Heading\n\n[jump](#real-heading)\n")
    assert cl.check_file(source, tmp_path) == []


def test_broken_in_page_anchor_is_reported(tmp_path):
    source = write(tmp_path, "source.md", "## Real Heading\n\n[jump](#imaginary)\n")
    problems = cl.check_file(source, tmp_path)
    assert any("in-page anchor" in p for p in problems)


def test_line_reference_anchors_are_not_treated_as_headings(tmp_path):
    """`file.md#L42` is a host-UI convention. Checking it as an anchor would
    fail every code citation in the docs."""
    write(tmp_path, "target.md", "# Title\n")
    source = write(tmp_path, "source.md", "[a](target.md#L42) [b](target.md#L10-L20)\n")
    assert cl.check_file(source, tmp_path) == []


# --- slug generation ----------------------------------------------------


@pytest.mark.parametrize(
    "heading,slug",
    [
        ("## Simple Heading", "simple-heading"),
        ("## `memory:` — not enabled", "memory--not-enabled"),
        ("## Trailing punctuation!", "trailing-punctuation"),
        ("## 1. Agent Interface Documentation", "1-agent-interface-documentation"),
        ("## Dependabot & generated artifacts", "dependabot--generated-artifacts"),
        ("## Snake_case words", "snake_case-words"),
    ],
)
def test_slug_matches_githubs_algorithm(heading, slug):
    """These slugs are what a reader's browser will actually jump to; getting
    them wrong means either false failures or missed breakage."""
    assert slug in cl.headings_to_anchors(heading + "\n")


def test_duplicate_headings_get_numbered_suffixes(tmp_path):
    anchors = cl.headings_to_anchors("## Notes\n\n## Notes\n\n## Notes\n")
    assert {"notes", "notes-1", "notes-2"} <= anchors


def test_headings_inside_code_fences_are_not_anchors():
    """A `# comment` line in a shell example is not a heading, and treating it
    as one would let a genuinely broken anchor pass."""
    text = "# Real\n\n```bash\n# not a heading\n```\n"
    anchors = cl.headings_to_anchors(text)
    assert "real" in anchors
    assert "not-a-heading" not in anchors


# --- fenced code, a deliberate limit ------------------------------------


def test_links_inside_code_fences_are_not_checked(tmp_path):
    """Deliberate: fenced blocks hold illustrative paths that do not exist
    here. It is also a real blind spot — an install command inside a fence can
    point at a path that does not exist, and this will not catch it (the
    `.standards/agents` bug in the subagent review was exactly that). Pinned as
    a test so the limit is a known one rather than a surprise."""
    source = write(
        tmp_path,
        "source.md",
        "```bash\nln -s ../../.standards/agents .claude/agents/standards\n```\n\n"
        "```\n[example](nonexistent.md)\n```\n",
    )
    assert cl.check_file(source, tmp_path) == []


def test_a_link_after_a_closed_fence_is_still_checked(tmp_path):
    """Fence tracking must not swallow the rest of the file."""
    source = write(
        tmp_path, "source.md", "```\ncode\n```\n\n[x](nonexistent.md)\n"
    )
    assert any("does not exist" in p for p in cl.check_file(source, tmp_path))


# --- the CLI ------------------------------------------------------------


def test_main_passes_on_a_clean_tree(tmp_path, capsys):
    write(tmp_path, "target.md", "# Target\n")
    write(tmp_path, "source.md", "[t](target.md)\n")
    assert cl.main_argv([str(tmp_path)]) == 0
    assert "checked 2 markdown file(s)" in capsys.readouterr().out


def test_main_fails_and_names_the_file_and_problem(tmp_path, capsys):
    write(tmp_path, "docs/source.md", "[t](gone.md)\n")
    assert cl.main_argv([str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "docs/source.md" in err
    assert "does not exist" in err


def test_main_ignores_the_git_directory(tmp_path, capsys):
    write(tmp_path, ".git/hooks/notes.md", "[t](gone.md)\n")
    assert cl.main_argv([str(tmp_path)]) == 0
