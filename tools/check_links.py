"""CI check: verify intra-repo markdown links and heading anchors resolve.

This repo is vendored as a `.standards` submodule and its docs are consumed
by cross-reference: CLAUDE.md cites sections of docs/security-protocols.md,
and the subagent prompts tell agents to read specific paths. Rename a file or
renumber a heading and every pointer dies silently — no error is raised
anywhere, in this repo or in the projects that follow the pointer.

Checks relative markdown links (`[text](path)`), optionally with an `#anchor`,
and bare in-page anchors. External URLs are not fetched: this must stay
offline, fast, and free of false failures from someone else's downtime.

Stdlib only, so CI needs no dependencies.

Usage:

    python tools/check_links.py .
"""

import argparse
import re
import sys
from pathlib import Path

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "#!")


def headings_to_anchors(text: str) -> set[str]:
    """GitHub's slug algorithm: lowercase, drop punctuation, spaces to hyphens.
    Duplicate headings get -1, -2, ... suffixes."""
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if not match:
            continue
        title = match.group(2)
        title = re.sub(r"`([^`]*)`", r"\1", title)
        title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
        slug = re.sub(r"[^\w\s-]", "", title.lower()).strip()
        slug = re.sub(r"[\s_]+", "-", slug)
        seen = counts.get(slug, 0)
        counts[slug] = seen + 1
        anchors.add(slug if seen == 0 else f"{slug}-{seen}")
    return anchors


def strip_code(text: str) -> str:
    """Blank out fenced blocks so example paths inside them aren't checked."""
    out, in_fence = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else line)
    return "\n".join(out)


def check_file(path: Path, root: Path) -> list[str]:
    problems = []
    text = path.read_text()
    body = strip_code(text)
    own_anchors = headings_to_anchors(text)

    for target in LINK_RE.findall(body):
        if target.startswith(SKIP_SCHEMES):
            continue

        file_part, _, anchor = target.partition("#")

        if not file_part:
            if anchor and anchor.lower() not in own_anchors:
                problems.append(f"in-page anchor #{anchor} has no matching heading")
            continue

        resolved = (root / file_part[1:] if file_part.startswith("/") else path.parent / file_part)
        try:
            resolved = resolved.resolve()
        except OSError:
            problems.append(f"link target {target} could not be resolved")
            continue

        if not resolved.exists():
            problems.append(f"link target {file_part} does not exist")
            continue

        # A #Lnn line reference is a host-UI convention, not a heading anchor.
        if anchor and resolved.suffix == ".md" and not re.fullmatch(r"L\d+(-L?\d+)?", anchor):
            if anchor.lower() not in headings_to_anchors(resolved.read_text()):
                problems.append(f"{file_part} has no heading matching anchor #{anchor}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    files = sorted(p for p in root.rglob("*.md") if ".git" not in p.parts)

    failed = False
    for path in files:
        problems = check_file(path, root)
        if problems:
            failed = True
            print(f"{path.relative_to(root)}:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)

    print(f"checked {len(files)} markdown file(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
