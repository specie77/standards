"""Tests for tools/check_sbom.py.

This script is executed by every project that vendors this repo as a
`.standards` submodule, so a silent regression here disables the SBOM
freshness gate everywhere at once. Tests run offline: `pip-audit` is never
invoked, only faked at the `subprocess.run` boundary.
"""

import json
import subprocess

import pytest

import check_sbom


def component(name, version, ref=None):
    return {"bom-ref": ref or f"ref-{name}-{version}", "name": name, "version": version}


def sbom(components, dependencies=None, **extra):
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "serialNumber": "urn:uuid:11111111-1111-1111-1111-111111111111",
        "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
        "components": list(components),
        "dependencies": list(dependencies if dependencies is not None else []),
        **extra,
    }


# --------------------------------------------------------------------------
# _normalize_name — PEP 503
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Flask", "flask"),
        ("zope.interface", "zope-interface"),
        ("ruamel_yaml", "ruamel-yaml"),
        ("Typing_Extensions", "typing-extensions"),
        ("a--b__c..d", "a-b-c-d"),
        ("already-normal", "already-normal"),
    ],
)
def test_normalize_name(raw, expected):
    assert check_sbom._normalize_name(raw) == expected


# --------------------------------------------------------------------------
# _pinned_names — what counts as an explicit `==` pin
# --------------------------------------------------------------------------


def test_pinned_names_reads_plain_pins(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("flask==3.0.0\nrequests==2.31.0\n")
    assert check_sbom._pinned_names(req) == {"flask", "requests"}


def test_pinned_names_handles_extras_markers_and_hashes(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# a comment\n"
        "\n"
        "celery[redis]==5.3.6 \\\n"
        "    --hash=sha256:abc123\n"
        'backports.zoneinfo==0.2.1; python_version < "3.9"\n'
        "-r other-requirements.txt\n"
        "--index-url https://example.invalid/simple\n"
        "  Zope.Interface==6.1  \n"
    )
    assert check_sbom._pinned_names(req) == {
        "celery",
        "backports-zoneinfo",
        "zope-interface",
    }


def test_pinned_names_ignores_unpinned_and_noise(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text(
        "flask>=3.0.0\n"
        "requests~=2.31\n"
        "# pydantic==2.0.0\n"
        "--hash=sha256:deadbeef\n"
        "\n"
        "urllib3==2.2.1\n"
    )
    assert check_sbom._pinned_names(req) == {"urllib3"}


# --------------------------------------------------------------------------
# _filter_to_pinned — drop resolution artifacts (specie77/standards#3)
# --------------------------------------------------------------------------


def test_filter_drops_components_not_pinned_in_the_lockfile():
    doc = sbom([component("flask", "3.0.0"), component("setuptools", "69.0.0")])
    filtered = check_sbom._filter_to_pinned(doc, {"flask"})
    assert [c["name"] for c in filtered["components"]] == ["flask"]


def test_filter_matches_names_not_versions():
    """A version mismatch on an already-pinned package must still be compared."""
    doc = sbom([component("flask", "9.9.9")])
    filtered = check_sbom._filter_to_pinned(doc, {"flask"})
    assert filtered["components"][0]["version"] == "9.9.9"


def test_filter_normalizes_names_when_matching():
    doc = sbom([component("Zope.Interface", "6.1")])
    filtered = check_sbom._filter_to_pinned(doc, {"zope-interface"})
    assert len(filtered["components"]) == 1


def test_filter_prunes_dependencies_and_dependson_edges():
    doc = sbom(
        [component("flask", "3.0.0", ref="A"), component("setuptools", "69.0.0", ref="B")],
        dependencies=[{"ref": "A", "dependsOn": ["B"]}, {"ref": "B", "dependsOn": []}],
    )
    filtered = check_sbom._filter_to_pinned(doc, {"flask"})
    assert filtered["dependencies"] == [{"ref": "A", "dependsOn": []}]


def test_filter_preserves_unrelated_top_level_keys():
    doc = sbom([component("flask", "3.0.0")], bomFormat="CycloneDX")
    filtered = check_sbom._filter_to_pinned(doc, {"flask"})
    assert filtered["bomFormat"] == "CycloneDX"
    assert filtered["specVersion"] == "1.4"


# --------------------------------------------------------------------------
# _normalize — strip per-run non-determinism
# --------------------------------------------------------------------------


def test_normalize_strips_volatile_keys():
    normalized = check_sbom._normalize(sbom([component("flask", "3.0.0")]))
    assert "serialNumber" not in normalized
    assert "metadata" not in normalized


def test_normalize_remaps_random_bom_refs_to_name_at_version():
    a = check_sbom._normalize(sbom([component("flask", "3.0.0", ref="random-1")]))
    b = check_sbom._normalize(sbom([component("flask", "3.0.0", ref="random-2")]))
    assert a == b
    assert a["components"][0]["bom-ref"] == "flask@3.0.0"


def test_normalize_is_insensitive_to_component_order():
    one = sbom([component("flask", "3.0.0"), component("requests", "2.31.0")])
    two = sbom([component("requests", "2.31.0"), component("flask", "3.0.0")])
    assert check_sbom._normalize(one) == check_sbom._normalize(two)


def test_normalize_still_detects_a_version_change():
    old = check_sbom._normalize(sbom([component("flask", "3.0.0")]))
    new = check_sbom._normalize(sbom([component("flask", "3.0.1")]))
    assert old != new


def test_normalize_still_detects_an_added_component():
    old = check_sbom._normalize(sbom([component("flask", "3.0.0")]))
    new = check_sbom._normalize(sbom([component("flask", "3.0.0"), component("idna", "3.6")]))
    assert old != new


# --------------------------------------------------------------------------
# main() — pip-audit faked at the subprocess boundary
# --------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A package directory with a lockfile and a committed SBOM."""

    class Project:
        def __init__(self):
            self.requirements = tmp_path / "requirements.txt"
            self.sbom_path = tmp_path / "sbom.json"
            self.requirements.write_text("flask==3.0.0\n")
            self.generated = sbom([component("flask", "3.0.0", ref="fresh-random")])

        def commit(self, doc):
            self.sbom_path.write_text(json.dumps(doc, indent=2) + "\n")

        def run(self, *extra):
            monkeypatch.setattr(
                check_sbom.subprocess,
                "run",
                lambda *a, **k: subprocess.CompletedProcess(
                    a[0], 0, stdout=json.dumps(self.generated), stderr=""
                ),
            )
            monkeypatch.setattr(
                "sys.argv",
                [
                    "check_sbom.py",
                    "--requirements",
                    str(self.requirements),
                    "--sbom",
                    str(self.sbom_path),
                    *extra,
                ],
            )
            return check_sbom.main()

    return Project()


def test_main_passes_when_sbom_matches(project, capsys):
    project.commit(sbom([component("flask", "3.0.0", ref="committed-random")]))
    assert project.run() == 0
    assert "up to date" in capsys.readouterr().out


def test_main_fails_when_a_version_drifted(project, capsys):
    project.commit(sbom([component("flask", "2.0.0", ref="committed-random")]))
    assert project.run() == 1
    assert "out of date" in capsys.readouterr().err


def test_main_fails_when_a_component_is_missing(project):
    project.commit(sbom([]))
    assert project.run() == 1


def test_fix_rewrites_the_sbom_and_succeeds(project, capsys):
    project.commit(sbom([component("flask", "2.0.0", ref="committed-random")]))
    assert project.run("--fix") == 0
    assert "regenerated" in capsys.readouterr().out
    written = json.loads(project.sbom_path.read_text())
    assert written["components"][0]["version"] == "3.0.0"


def test_fix_output_passes_a_subsequent_check(project):
    """--fix must be idempotent: what it writes has to satisfy the check."""
    project.commit(sbom([component("flask", "2.0.0")]))
    assert project.run("--fix") == 0
    assert project.run() == 0


def test_committed_sbom_with_unpinned_build_tool_does_not_fail(project):
    """specie77/standards#3, from the committed side.

    A base image's bundled setuptools can land in the committed SBOM. It is
    not `==`-pinned in the lockfile, so it is a resolution artifact and must
    be filtered out of BOTH sides before comparing — otherwise the check
    fails with zero real dependency drift.
    """
    project.commit(
        sbom([component("flask", "3.0.0"), component("setuptools", "69.0.0")])
    )
    assert project.run() == 0


def test_committed_sbom_with_a_root_dependency_ref_is_handled(project):
    """CycloneDX documents routinely carry a dependencies entry for the root
    metadata.component, whose ref is not present in components."""
    project.generated = sbom(
        [component("flask", "3.0.0", ref="gen-A")],
        dependencies=[{"ref": "gen-A"}],
    )
    project.commit(
        sbom(
            [component("flask", "3.0.0", ref="A")],
            dependencies=[{"ref": "root-app", "dependsOn": ["A"]}, {"ref": "A"}],
        )
    )
    assert project.run() == 0


def test_missing_sbom_file_reports_cleanly(project, capsys):
    """A first run before any SBOM exists must not raise a raw traceback."""
    assert project.run() == 1
    assert "does not exist" in capsys.readouterr().err


def test_missing_sbom_file_can_be_created_with_fix(project):
    assert project.run("--fix") == 0
    assert json.loads(project.sbom_path.read_text())["components"][0]["name"] == "flask"


def test_invalid_committed_sbom_reports_cleanly(project, capsys):
    project.sbom_path.write_text("{not json")
    assert project.run() == 1
    assert "not valid JSON" in capsys.readouterr().err
