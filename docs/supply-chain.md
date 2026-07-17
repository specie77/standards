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
  **Use the canonical shared script, `tools/check_sbom.py` in this
  standards repo, rather than copy-pasting an implementation per project** —
  see "Shared tooling scripts" below for why and how. It already handles the
  normalization this check needs:
  - SBOM generators (e.g. `pip-audit --format=cyclonedx-json`) emit a random
    `bom-ref` per component and a unique `metadata.timestamp` / `serialNumber`
    on every run — remapped/stripped before comparing, or every run reports
    drift with no real dependency change.
  - `pip-audit`'s own resolution can also surface build-time packages (`pip`,
    `setuptools`, `wheel`, ...) that a Docker base image bundles but that
    aren't themselves pinned in the lockfile. Their bundled versions drift
    over time independent of the project's actual dependencies, which would
    otherwise fail the freshness check with zero real drift (observed:
    `python:3.11-slim`'s bundled `setuptools` moved between two runs with no
    lockfile change — specie77/standards#3). Fixed by restricting the
    comparison to components whose *name* (not version — a genuine version
    mismatch on an already-pinned package must still fail) appears as an
    explicit `==` pin somewhere in the lockfile.

## Shared tooling scripts

`.standards` is vendored as a git submodule into every project (the same
mechanism that shares `CLAUDE.md` via `@.standards/CLAUDE.md`). Any script
whose *logic*, not just its guidance, should be identical across projects
belongs in `tools/` in this repo — invoked directly from the submodule path,
not copied into each project.

**Why not copy-paste a "reference implementation":** a copied script has no
mechanism keeping copies in sync. A fix applied to one project's copy has to
be manually re-applied to every other copy, and nothing catches silent
drift between them if that's missed — the opposite of the guarantee a
single shared source of truth provides. (`check_sbom.py` existed as three
near-identical per-package copies before this section was written; they
happened to be identical, but nothing enforced it.)

**Convention:** projects invoke the script directly from the submodule path,
parameterized via CLI flags for whatever varies per call site (file paths,
package name, etc.) rather than hardcoding project-specific values into a
per-project copy:

```yaml
# from a package directory, e.g. packages/mcp/
- name: SBOM freshness check
  run: python ../../.standards/tools/check_sbom.py
```

Bumping the `.standards` submodule pointer updates the logic for every
project that calls it — the same propagation model already used for docs.

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
  - Commit back with a **GitHub App token, never `GITHUB_TOKEN`** — commits
    pushed with `GITHUB_TOKEN` do not re-trigger workflows, so the freshness
    check would never re-run green and auto-merge would never fire. **A
    fine-grained PAT was observed not to re-trigger CI either** (the pushed
    commit received zero check-runs), so prefer a **GitHub App** installed on
    just the one repo (Contents: write): its tokens are repo-scoped, auto-expire
    in ~1h (nothing to rotate), and App-authenticated pushes reliably re-trigger.
    Use `actions/create-github-app-token`; a classic `repo`-scoped PAT also
    re-triggers but has a far broader blast radius (all your repos) — avoid it
    when an App will do.
  - **Name the secret with a repo/project identifier** (e.g.
    `VOICE_MEAL_PLANNER_CORE_SBOM_REFRESH_PAT`, not `SBOM_REFRESH_PAT`) —
    this pattern is meant to be reused across multiple projects, each with
    its own equivalently-scoped PAT. A generic name invites collision or
    ambiguity once more than one repo's secrets are being managed side by
    side (e.g. copy-pasting a workflow between repos, or a developer
    auditing PATs across their GitHub account). Apply the same convention
    to any other repo-scoped automation secret, not just this one.
  - **The auto-merge gate must allow the refresh bot's actor, not just
    `dependabot[bot]`.** Once the refresh workflow pushes its fix commit, the CI
    run it re-triggers has that bot as its actor — so the *green* run is authored
    by the App/PAT identity, **not** `dependabot[bot]`. An auto-merge condition
    gated on `workflow_run.actor.login == 'dependabot[bot]'` will skip that green
    run and the PR never merges (observed: all checks green, auto-merge silently
    skipped). Gate on the branch prefix (`startsWith(head_branch, 'dependabot/')`
    — the real safety boundary, since only Dependabot opens those branches) and
    allow **both** actors:

    ```yaml
    if: >
      github.event.workflow_run.event == 'pull_request' &&
      github.event.workflow_run.conclusion == 'success' &&
      startsWith(github.event.workflow_run.head_branch, 'dependabot/') &&
      (github.event.workflow_run.actor.login == 'dependabot[bot]' ||
       github.event.workflow_run.actor.login == '<refresh-app-slug>[bot]')
    ```

Either way, do not auto-merge without a required CI status check gating the merge
(see `CLAUDE.md`, Dependabot) — otherwise a stale SBOM lands on the default branch.

## Dependabot on hash-locked lockfiles: freeze exact-pinned pairs

Dependabot edits a hash-locked lockfile **entry by entry** — it does not
re-resolve the dependency graph. Its `pip-compile` re-resolution only engages
when the lockfile is generated from a `requirements.in` source; a lockfile
compiled straight from `pyproject.toml` (or by `uv`, which Dependabot does not
support at all) gets plain entry-editing. When a package **exact-pins** another
(`foo` depends on `foo-core==<exact>`), Dependabot bumping either one of the pair
alone produces an **uninstallable** lockfile. Observed in practice: `pydantic`
exact-pins `pydantic-core==<version>`; Dependabot bumped `pydantic-core` to
`2.47.0` while `pydantic 2.13.4` pins `==2.46.4`, and every affected PR failed at
`pip install` (`ResolutionImpossible`) before any SBOM/test step. Grouped updates
make it worse by bundling several such bumps.

**`dependency-type: direct` does NOT fix this** — do not reach for it. A flat,
fully-pinned lockfile (pip-compile/uv output) lists *every* package explicitly,
so Dependabot classifies them all as "direct" and the filter is a no-op. This
was confirmed empirically: after adding `allow: [{dependency-type: direct}]`,
a clean `@dependabot recreate` against the live config still produced the broken
`pydantic-core` bump. (The filter only distinguishes direct/transitive when the
manifest lists only direct deps — e.g. a `requirements.in` with resolved
transitives elsewhere — which a flat lockfile does not.)

**What actually works:** `ignore` both members of each exact-pinned pair on
every pip entry, so the pair moves **only** via a consistent recompile:

```yaml
updates:
  - package-ecosystem: pip
    directory: /packages/foo
    ignore:
      - dependency-name: "pydantic"
      - dependency-name: "pydantic-core"
```

Freeze **both** names, not just the one you saw break — the conflict occurs in
either direction (the child bumped ahead of the parent, or the parent bumped
ahead when it releases). `pydantic`/`pydantic-core` is the common offender;
most packages use ranges and are fine. Add a new pair to the ignore list only
when a grouped PR actually fails at `pip install` on a version conflict —
don't pre-emptively freeze deps that use ranges. Everything else Dependabot may
still bump and auto-merge. The frozen pair's freshness (and CVEs) are covered:

- **Security**: `pip-audit` in CI fails the build on a CVE in *any* dependency,
  including an ignored one; you fix it with a lockfile recompile.
- **Routine freshness**: periodically (e.g. monthly) recompile every package's
  lockfile with `--upgrade` and regenerate the SBOM — one PR, one CI run — which
  moves the frozen pair together consistently and sweeps up other transitives.
  Same batch recompile used to consolidate a large Dependabot backlog.

This does **not** apply to `docker` or `github-actions` ecosystems (no
lockfile to make inconsistent) — leave those unrestricted.

### Automating the periodic-recompile reminder

The "recompile monthly" step above is easy to forget once it's not gated by a
failing check. Don't automate the recompile itself (re-resolving executes the
bumped packages' build backends — the same supply-chain reason the SBOM-refresh
workflow above is deliberately SBOM-only) — but a **reminder** carries no such
risk, since it runs no package code at all. Add a small scheduled workflow that
opens a labeled GitHub issue on a monthly cron, with a checklist body listing
each package's recompile command and which exact-pinned pairs must move:

```yaml
name: Monthly recompile reminder
on:
  schedule:
    - cron: "0 9 1 * *"      # 1st of the month
  workflow_dispatch: {}
permissions:
  contents: read   # needed for actions/checkout, even to read a local file
  issues: write
jobs:
  remind:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<pinned-sha>
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          existing=$(gh issue list --repo "$GITHUB_REPOSITORY" \
            --label recompile --state open --json number --jq 'length')
          if [ "$existing" -gt 0 ]; then exit 0; fi
          gh issue create --repo "$GITHUB_REPOSITORY" \
            --label recompile \
            --title "Monthly lockfile recompile ($(date +%Y-%m))" \
            --body-file .github/recompile-checklist.md
```

**Dedup on the label, not the date.** Check for an already-open issue with the
marker label before creating a new one. This makes a skipped month self-healing
(last month's issue is still open, so nothing new fires) instead of piling up
duplicate reminders — the only required discipline is closing the issue after
you actually recompile, which re-arms next month's check.

The built-in `GITHUB_TOKEN` is sufficient (`issues: write` on a same-repo
issue-create) — no App/PAT needed, unlike the SBOM-refresh push-back above.

**A `permissions:` block replaces the default token scopes, it doesn't add to
them.** Listing only `issues: write` (because that's the only *action* the job
takes) silently revokes the otherwise-implicit `contents: read`, and
`actions/checkout` then fails with a confusing `remote: Repository not found`
— indistinguishable at a glance from an actual auth/visibility problem.
Observed in practice on this exact workflow. Any job with an explicit
`permissions:` block that also runs `actions/checkout` needs `contents: read`
listed alongside whatever scopes the job's real work requires, even when
checkout is only there to read a local file (e.g. an issue-body template).

### Consolidating a Dependabot backlog

When many Dependabot PRs have piled up (or all fail a shared check like SBOM
freshness), do **not** re-run/merge them individually — that burns one CI run per
PR. Instead consolidate: on one branch, recompile each package's lockfile with
`--upgrade` (in the CI-matching container/Python version), regenerate the SBOMs,
apply any `github-actions`/`docker` bumps by hand, and open a single PR. One CI
run clears the whole backlog, and — because a recompile re-resolves the graph —
the result is internally consistent even where the individual Dependabot PRs were
not. Close the superseded PRs with a pointer to the consolidated one.

## CI integration checklist

When touching CI config, confirm it includes:

- [ ] Lockfile/hash verification step
- [ ] `pip-audit` step (fails build on high/critical)
- [ ] Build fails if `--require-hashes` install fails
- [ ] SBOM freshness check via `.standards/tools/check_sbom.py` (not a
      per-project copy) — fails the build if out of date
- [ ] Dependabot PRs refresh generated artifacts (SBOM, and lockfile hashes if
      transitively affected) — manually before merge, or via an SBOM-only
      auto-regeneration workflow; auto-merge gated on a required CI check
- [ ] Hash-locked pip lockfiles compiled from `pyproject.toml`/`uv`: any
      exact-pinned dependency pair (e.g. `pydantic`/`pydantic-core`) is `ignore`d
      on each pip Dependabot entry so it moves only via recompile (NOT
      `dependency-type: direct`, which is a no-op on flat pinned lockfiles)
- [ ] If any pair is frozen per the above, a scheduled reminder workflow opens
      a labeled issue monthly prompting the recompile (dedup on an open label,
      not the date) — the recompile itself stays manual/unautomated

## Scope

This covers dependency and build-pipeline hardening only — do not use these
standards as justification for unrelated application logic changes.