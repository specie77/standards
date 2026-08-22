#!/usr/bin/env python3
"""Assert the named packages were installed from a LOCAL PATH, not an index.

Why this exists (#345).

`meal-planner-core` and `meal-planner-mcp` are not registered on PyPI — checked
2026-08-22, both 404 — so the names are claimable by anyone. That is the
dependency-confusion risk `.standards/docs/supply-chain.md` names under "New
dependency review".

Nothing is exposed today, because every install site reaches these packages by
local path with `--no-deps`, and the lockfiles around them are hash-locked. Two
independent mechanisms, both currently correct.

The problem is that the protection lives entirely in flags on install commands.
Drop `--no-deps` from one line — while tidying, while debugging, while adding a
call site — and pip becomes free to resolve the name from PyPI. If someone has
claimed it by then, a package with the right name installs and runs, and
**nothing anywhere would say so**. The build stays green. The tests still pass,
because the stub only has to expose the right module names to get that far.

Registering placeholder names on PyPI was the other option, and was rejected:
it makes a permanent public artifact for a deliberately private project, and it
would not even catch this failure — a squatted name is a different problem from
an install that reaches an index it should never reach. This check catches the
thing that would actually go wrong.

## How it works

PEP 610: pip writes a `direct_url.json` into a distribution's `.dist-info`
**only** when it was installed from a direct URL or local path. A package pulled
from an index has no such file. So the presence of `direct_url.json` with a
`file://` URL is positive proof of a local install, and its absence is proof of
the opposite — this asserts provenance rather than inferring it from the
command line, which is what makes it worth having.

Usage:
    python tools/check_local_install.py meal-planner-core
    python tools/check_local_install.py meal-planner-core meal-planner-mcp
"""
from __future__ import annotations

import json
import sys
from importlib import metadata


def _origin(name: str) -> tuple[bool, str]:
    """(ok, human-readable detail) for one distribution."""
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False, "not installed at all"

    raw = dist.read_text("direct_url.json")
    if raw is None:
        # No direct_url.json => resolved from an index. This is the failure the
        # check exists for.
        return False, (
            f"installed from an INDEX (version {dist.version}, no "
            "direct_url.json). Expected a local path install."
        )

    try:
        url = json.loads(raw).get("url", "")
    except json.JSONDecodeError:
        return False, "direct_url.json is present but unparseable"

    if not url.startswith("file://"):
        return False, f"installed from a direct URL that is not a local path: {url}"

    return True, f"local path ({url})"


def main(argv: list[str]) -> int:
    names = argv[1:]
    if not names:
        print(__doc__)
        return 2

    failures: list[str] = []
    for name in names:
        ok, detail = _origin(name)
        print(f"{'ok  ' if ok else 'FAIL'}  {name}: {detail}")
        if not ok:
            failures.append(f"{name}: {detail}")

    if failures:
        print(
            "\nERROR: a package that must come from this repo did not.\n\n"
            + "\n".join(f"  - {f}" for f in failures)
            + "\n\nThese names are UNREGISTERED on PyPI and claimable by anyone "
            "(#345), so an\ninstall that reaches an index is a supply-chain "
            "exposure, not a packaging\ndetail. Check that the install command "
            "still uses a local path with --no-deps;\nthose flags are "
            "load-bearing, not incidental.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
