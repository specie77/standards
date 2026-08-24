"""Tests for tools/check_local_install.py.

This script is executed by every project that vendors this repo as a
.standards submodule, and it is a security check: it asserts that internally-
named packages — names that are unregistered on PyPI and therefore claimable by
anyone — came from a local path rather than from an index.

Its failure mode is the bad one. A regression that makes it pass
unconditionally would report success on a project that had started pulling a
squatted package from PyPI, in every consuming project at once, with nothing
failing anywhere. So every test here asserts a rule *fires* on a bad install,
not merely that a good one passes; a suite that only tested the happy path
would go green on a check that had stopped checking.

The PEP 610 contract under test: pip writes `direct_url.json` into a
distribution's `.dist-info` ONLY for a direct URL or local path install. Its
absence is positive evidence of an index install, which is why "no file" must
fail rather than be skipped.
"""

from types import SimpleNamespace

import check_local_install as cli
import pytest


class FakeDist:
    """The slice of importlib.metadata.Distribution the check actually uses."""

    def __init__(self, version="1.0.0", direct_url=None):
        self.version = version
        self._direct_url = direct_url

    def read_text(self, filename):
        if filename == "direct_url.json":
            return self._direct_url
        return None


class NotFound(Exception):
    pass


@pytest.fixture
def installed(monkeypatch):
    """Install a fake environment: {name: FakeDist}. Anything not in the map
    raises PackageNotFoundError, as an uninstalled package would.

    The module's `metadata` reference is replaced wholesale rather than
    patching importlib.metadata.distribution, which would be a global change
    for the whole test session.
    """

    def _install(packages):
        def distribution(name):
            try:
                return packages[name]
            except KeyError:
                raise NotFound(name) from None

        monkeypatch.setattr(
            cli,
            "metadata",
            SimpleNamespace(distribution=distribution, PackageNotFoundError=NotFound),
        )

    return _install


# --- the provenance rule ------------------------------------------------


def test_local_path_install_passes(installed):
    installed({"my-core": FakeDist(direct_url='{"url": "file:///repo/packages/core"}')})
    ok, detail = cli._origin("my-core")
    assert ok
    assert "local path" in detail


def test_index_install_fails(installed):
    """No direct_url.json is exactly what an index install looks like. This is
    the failure the whole check exists for."""
    installed({"my-core": FakeDist(direct_url=None)})
    ok, detail = cli._origin("my-core")
    assert not ok
    assert "INDEX" in detail


def test_index_install_detail_names_the_version(installed):
    """The version is what tells you which package you actually got — a
    squatted release will not match the local one."""
    installed({"my-core": FakeDist(version="9.9.9", direct_url=None)})
    _, detail = cli._origin("my-core")
    assert "9.9.9" in detail


def test_package_not_installed_fails(installed):
    """Must fail, not silently pass. A typo'd package name in the CI step
    would otherwise turn the check into a no-op that reports ok."""
    installed({})
    ok, detail = cli._origin("my-core")
    assert not ok
    assert "not installed" in detail


def test_malformed_direct_url_json_fails(installed):
    """A file that is present but unparseable proves nothing about provenance,
    so it must fail rather than be skipped as 'no evidence either way'."""
    installed({"my-core": FakeDist(direct_url="{not json")})
    ok, detail = cli._origin("my-core")
    assert not ok
    assert "unparseable" in detail


@pytest.mark.parametrize(
    "url",
    [
        "https://pypi.org/simple/my-core/my_core-1.0.0.tar.gz",
        "git+https://github.com/someone/my-core@main",
        "http://internal-mirror.example/my-core.whl",
    ],
)
def test_non_local_direct_url_fails(installed, url):
    """direct_url.json exists for any direct URL install, not just a local
    path. Treating its mere presence as proof would accept a package fetched
    over the network — the thing being ruled out."""
    installed({"my-core": FakeDist(direct_url=f'{{"url": "{url}"}}')})
    ok, detail = cli._origin("my-core")
    assert not ok
    assert url in detail


def test_direct_url_json_without_a_url_key_fails(installed):
    installed({"my-core": FakeDist(direct_url="{}")})
    assert cli._origin("my-core")[0] is False


# --- the CLI ------------------------------------------------------------


def test_main_exits_zero_when_every_package_is_local(installed, capsys):
    local = FakeDist(direct_url='{"url": "file:///repo/packages/core"}')
    installed({"my-core": local, "my-app": local})
    assert cli.main(["check_local_install.py", "my-core", "my-app"]) == 0
    assert "FAIL" not in capsys.readouterr().out


def test_main_exits_nonzero_and_names_the_offending_package(installed, capsys):
    installed(
        {
            "my-core": FakeDist(direct_url='{"url": "file:///repo/packages/core"}'),
            "my-app": FakeDist(direct_url=None),
        }
    )
    assert cli.main(["check_local_install.py", "my-core", "my-app"]) == 1
    captured = capsys.readouterr()
    assert "my-app" in captured.err
    assert "my-core" not in captured.err


def test_main_reports_every_failure_not_just_the_first(installed, capsys):
    """Fixing one bad install and re-running CI to discover the next is a slow
    way to find out; the check reports all of them in one pass."""
    installed({"my-core": FakeDist(direct_url=None), "my-app": FakeDist(direct_url=None)})
    assert cli.main(["check_local_install.py", "my-core", "my-app"]) == 1
    err = capsys.readouterr().err
    assert "my-core" in err and "my-app" in err


def test_main_with_no_package_names_is_an_error(capsys):
    """Zero names would otherwise 'pass' — an empty check reporting success is
    how a CI step silently stops protecting anything."""
    assert cli.main(["check_local_install.py"]) == 2


def test_failure_message_explains_the_exposure(installed, capsys):
    """The message has to say why this matters, or a future reader deletes the
    step as a packaging nuisance."""
    installed({"my-core": FakeDist(direct_url=None)})
    cli.main(["check_local_install.py", "my-core"])
    err = capsys.readouterr().err
    assert "UNREGISTERED" in err
    assert "--no-deps" in err
