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
- Add a CI step that regenerates the SBOM from the locked requirements and
  fails the build if it differs from the committed copy ("freshness check").
  Since SBOM generators (e.g. `pip-audit --format=cyclonedx-json`) emit a
  random `bom-ref` per component and a unique `metadata.timestamp` /
  `serialNumber` on every run, the check must normalize those fields (e.g.
  remap `bom-ref` to `name@version`, strip `metadata`/`serialNumber`) before
  comparing — otherwise every run will report drift even with no dependency
  changes. See `voice-meal-planner-core`'s `packages/mcp/tools/check_sbom.py`
  (or `packages/comms/tools/check_sbom.py`) for a reference implementation.

## Dependabot and generated artifacts

Dependabot edits `requirements.txt` (and its `--hash` entries) directly. It does
**not** run `pip-compile` and does **not** regenerate the SBOM. In a hash-locked
repo with an SBOM freshness check this means **every** Dependabot PR fails CI
until the generated artifacts are refreshed — the version bump is correct, but
the committed SBOM (and any transitively-affected hashes) are stale. Resolve it
one of two ways:

- **Manual**: before merging, re-resolve the lockfile with
  `pip-compile --generate-hashes` and regenerate the SBOM, committing both.
- **Automated**: add a workflow that regenerates the SBOM on patch/minor
  Dependabot PRs and commits it back to the PR branch. Constraints:
  - Keep it **SBOM-only**. `pip-audit` reads the already-pinned requirements and
    runs no package build code, so it is safe in a privileged, PR-triggered job.
    Do **not** auto-run `pip-compile --generate-hashes` there — resolving
    dependencies executes the bumped (untrusted) package's build backend. If
    lockfile recompilation must be automated, isolate it in a two-workflow
    `pull_request` (unprivileged, uploads an artifact) → `workflow_run`
    (privileged, commits the artifact as data only) split.
  - Commit back with a **PAT or GitHub App token, never `GITHUB_TOKEN`** —
    commits authored by `GITHUB_TOKEN` do not re-trigger workflows, so the
    freshness check would never re-run green.

Either way, do not auto-merge without a required CI status check gating the merge
(see `CLAUDE.md`, Dependabot) — otherwise a stale SBOM lands on the default branch.

## CI integration checklist

When touching CI config, confirm it includes:

- [ ] Lockfile/hash verification step
- [ ] `pip-audit` step (fails build on high/critical)
- [ ] Build fails if `--require-hashes` install fails
- [ ] SBOM freshness check (regenerate and diff against the committed SBOM,
      normalizing volatile fields) — fails the build if out of date
- [ ] Dependabot PRs refresh generated artifacts (SBOM, and lockfile hashes if
      transitively affected) — manually before merge, or via an SBOM-only
      auto-regeneration workflow; auto-merge gated on a required CI check

## Scope

This covers dependency and build-pipeline hardening only — do not use these
standards as justification for unrelated application logic changes.