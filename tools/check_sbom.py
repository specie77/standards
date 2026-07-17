"""CI check: fail if a package's SBOM is out of date with its lockfile.

Canonical shared implementation (specie77/standards). Projects vendor this
repo as a `.standards` git submodule and invoke this script directly rather
than copy-pasting it — bumping the submodule pointer updates the logic
everywhere at once.

Regenerates a CycloneDX SBOM via `pip-audit -r <requirements>` and compares it
against the committed copy, after normalizing away two sources of
non-determinism:

1. pip-audit assigns a fresh random bom-ref to each component on every run,
   and metadata.timestamp/serialNumber are always unique — both stripped
   before comparing (remap bom-ref to name@version; drop metadata/serialNumber).
2. pip-audit's own resolution can surface build-time packages (pip,
   setuptools, wheel, ...) that a Docker base image bundles but that are not
   themselves pinned in the lockfile. Because the base image's bundled
   versions drift over time independent of any real dependency change, this
   would otherwise fail the freshness check with zero actual drift in the
   project's own dependencies (specie77/standards#3). Fixed by restricting
   both the generated and committed SBOMs to components whose *name* (not
   version — a real version mismatch on an already-pinned package should
   still fail the check) appears as an explicit `==` pin somewhere in the
   lockfile before comparing.

Pass --fix to overwrite the SBOM file with the freshly generated one instead
of failing — used both for local manual regeneration and by a Dependabot
SBOM-refresh workflow.

Usage (run with cwd = the package directory, e.g. packages/mcp):

    python ../../.standards/tools/check_sbom.py [--fix]
    python ../../.standards/tools/check_sbom.py --requirements requirements.txt --sbom docs/sbom.json
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

VOLATILE_KEYS = ("metadata", "serialNumber")

# PEP 503: package names are compared case-insensitively with runs of
# -_. treated as equivalent.
_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*?)(?:\[[^\]]*\])?==")


def _normalize_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pinned_names(requirements_path: Path) -> set[str]:
    """Names explicitly `==`-pinned in a hash-locked requirements file.

    Anything pip-audit reports that ISN'T in this set is a resolution
    artifact (e.g. a base-image-bundled build tool) rather than a real
    project dependency, and is excluded from the SBOM comparison.
    """
    names = set()
    for line in requirements_path.read_text().splitlines():
        match = _PIN_RE.match(line.strip())
        if match:
            names.add(_normalize_name(match.group(1)))
    return names


def _filter_to_pinned(sbom: dict, pinned_names: set[str]) -> dict:
    kept_refs = {
        c["bom-ref"] for c in sbom["components"] if _normalize_name(c["name"]) in pinned_names
    }
    components = [c for c in sbom["components"] if c["bom-ref"] in kept_refs]
    dependencies = [d for d in sbom.get("dependencies", []) if d["ref"] in kept_refs]
    for dep in dependencies:
        if "dependsOn" in dep:
            dep["dependsOn"] = [ref for ref in dep["dependsOn"] if ref in kept_refs]
    return {**sbom, "components": components, "dependencies": dependencies}


def _normalize(sbom: dict) -> dict:
    bom_ref_map = {c["bom-ref"]: f"{c['name']}@{c['version']}" for c in sbom["components"]}

    components = sorted(
        ({**c, "bom-ref": bom_ref_map[c["bom-ref"]]} for c in sbom["components"]),
        key=lambda c: c["bom-ref"],
    )
    dependencies = sorted(bom_ref_map[d["ref"]] for d in sbom["dependencies"])

    return {
        **{k: v for k, v in sbom.items() if k not in VOLATILE_KEYS and k not in ("components", "dependencies")},
        "components": components,
        "dependencies": dependencies,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", default="requirements-dev.txt", type=Path)
    parser.add_argument("--sbom", default="docs/sbom.json", type=Path)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    result = subprocess.run(
        [sys.executable, "-m", "pip_audit", "-r", str(args.requirements), "--format=cyclonedx-json"],
        capture_output=True,
        text=True,
        check=True,
    )
    pinned_names = _pinned_names(args.requirements)
    raw_generated = _filter_to_pinned(json.loads(result.stdout), pinned_names)
    generated = _normalize(raw_generated)
    committed = _normalize(json.loads(args.sbom.read_text()))

    if generated != committed:
        if args.fix:
            args.sbom.write_text(json.dumps(raw_generated, indent=2) + "\n")
            print(f"{args.sbom} was out of date — regenerated.")
            return 0
        print(
            f"{args.sbom} is out of date with {args.requirements}.\n"
            "Regenerate it: see your project's dependency-management docs (SBOM section).",
            file=sys.stderr,
        )
        return 1

    print(f"{args.sbom} is up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
