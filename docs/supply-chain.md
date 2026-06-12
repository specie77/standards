# Supply Chain Security Standards

These standards apply to all Python dependency, Docker, and CI/CD work in this
project. Follow them automatically when adding, updating, or reviewing
dependencies — don't wait to be asked.

## Dependency pinning

- All dependencies must be hash-locked. Use `pip-compile --generate-hashes`
  (pip-tools) to generate `requirements.txt` from `requirements.in`, or use a
  Poetry/PDM lockfile if the project already uses one.
- Never introduce unpinned or range-pinned dependencies (`>=`, `~=`, `*`)
  into a locked requirements file. If a range is unavoidable, document why.
- When updating a dependency, regenerate the lockfile rather than hand-editing
  version numbers.

## Vulnerability scanning

- Run `pip-audit` against the locked requirements file before considering any
  dependency change complete.
- If `pip-audit` isn't already wired into CI, add it as a pipeline step that
  fails the build on high/critical findings.
- Treat new CVEs surfaced by `pip-audit` as a priority fix, not a backlog item.

## Install-time integrity

- CI and Docker builds must install with `pip install --require-hashes`.
- Docker base images must be pinned by digest (`FROM image@sha256:...`), not
  just by tag. When updating a base image, update the digest explicitly.

## New dependency review (typosquat / namespace risk)

Before adding any new package:

- Verify the package name, maintainer, and download count on PyPI match what
  you expect — watch for near-identical names to popular packages.
- Be suspicious of brand-new packages with very low adoption being pulled in
  as transitive dependencies.
- If this project has any internally-named packages, check that the name
  isn't claimable on public PyPI (dependency confusion risk). If it is,
  recommend namespace prefixing or a scoped private index.

## SBOM

- Maintain a CycloneDX (or SPDX) SBOM for the project's dependencies.
- Regenerate it whenever the lockfile changes and commit it alongside the
  lockfile update.

## CI integration checklist

When touching CI config, confirm it includes:

- [ ] Lockfile/hash verification step
- [ ] `pip-audit` step (fails build on high/critical)
- [ ] Build fails if `--require-hashes` install fails
- [ ] SBOM regeneration step (or a reminder if it's manual)

## Scope

This covers dependency and build-pipeline hardening only — do not use these
standards as justification for unrelated application logic changes.