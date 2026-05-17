# Universal Development Standards

These rules apply to every project. Project-specific CLAUDE.md files import this file and add their own context below.

## About the Developer

Solo developer. Works methodically — prefers explicit step tracking and phased plans over sweeping changes. Calibrate communication accordingly: be direct and concise, confirm approach before large changes, don't over-explain.

---

## Session Start

Run `git fetch origin` at the start of every session. If the remote is ahead, pull immediately without asking.

If the repo has git submodules, also run `git submodule update --remote --merge` to pull the latest from each submodule's remote. Do this every session without asking.

## Git Commands

Always use `git -C /path/to/repo` instead of `cd /path && git`. No exceptions.

## Git Branching Strategy

- `main` — stable code only. Never commit directly to `main` during active development.
- `feature/<description>` — planned steps; `fix/<description>` — bug-only; `claude/<description>` — AI-assisted sessions.
- Merge to `main` via pull request only when tested and stable.
- Keep commits atomic and descriptive.

## Libraries

Official, well-maintained packages only (e.g. PyPI verified). No experimental, unmaintained, or obscure community packages.

## Secrets

All credentials via environment variables. Never hardcode tokens, keys, or IDs. `.env` is never committed.

## Secure Coding

- Validate all external inputs at system boundaries before acting on them using a **strict whitelist**, not a blacklist.
- Numeric inputs: use `isdecimal()` + range check. Never use `isdigit()` — it accepts Unicode superscripts that `int()` then raises on.
- String inputs: match against a regex whitelist of expected characters/format before use.
- Never log secrets, tokens, or sensitive data.
- Catch specific exceptions; never swallow errors silently.
- Verify message/callback sender identity before processing any instruction.

## Atomic File Writes

Always write to a temp file first, then `os.replace()` to the target. Never write directly to a critical data file — a partial write corrupts it.

## Logging

Use `RotatingFileHandler` (1 MB / 10 files). DEBUG in test mode, INFO in live. Suppress noisy third-party loggers to WARNING.

## Background Threads

Any daemon thread providing a critical capability must have a retry loop with capped backoff. Pattern:

```python
while True:
    try:
        run()
    except Exception as e:
        sleep(min(60, 5 * attempt))
```

After 20 consecutive failures, send a personal alert; retries continue silently after.

## File Editing

Never use `sed` to edit files. It is error-prone (silent failures, regex escaping pitfalls, in-place behavior varies by platform) and requires user approval for each invocation.

Use the dedicated tools instead:
- **Edit a file**: `Edit` tool (exact string replacement, verified)
- **Write a new file**: `Write` tool
- **Read a file**: `Read` tool (not `cat`, `head`, or `tail`)

For one-off shell transformations where `sed` would normally be used (e.g. stripping a prefix, substituting a value in a generated string), use Python inline: `python3 -c "..."` or a short script.

## Pull Request Workflow

Always run the relevant tests (unit, integration, or live test mode) and confirm they pass *before* merging a PR to main.

## GitHub CLI (gh)

Never pass multiline content inline to `gh` commands. Write the body to a temp file and use `--body-file`:

```bash
cat > /tmp/gh_body.md << 'EOF'
content here
EOF
gh pr create --title "..." --body-file /tmp/gh_body.md
rm /tmp/gh_body.md
```

Multiline strings in `--body` break the `gh *` allowlist pattern match and trigger permission prompts.
## Documentation

- Feature requests and future enhancements → open a GitHub issue.
- Core build functionality, standards, architecture, operational runbooks → `.md` files in `docs/`.


## Dependabot

Every repo must have `.github/dependabot.yml` with an entry for each package ecosystem present:

- `github-actions` — always required
- `pip` — if the repo contains Python dependencies
- `docker` — if the repo contains a `Dockerfile`

Weekly schedule, Monday, with `open-pull-requests-limit` of 5–10 per ecosystem.

Before merging a Dependabot PR, confirm CI passes. If a bump fails due to an incompatible transitive dependency (e.g., `redis>=7` vs `celery<6`), close the PR with a comment explaining the blocker rather than leaving it stale.

## GitHub Actions Pinning

Pin every third-party action to a full commit SHA, not a floating tag. Add the version as a comment:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
```

Floating tags (`@v4`, `@main`) are mutable and expose the pipeline to supply-chain attacks. Dependabot keeps pinned SHAs up to date automatically.

## Dependency CVE Auditing

Every CI pipeline must include a `pip-audit` step that runs after dependency installation and before tests. Pin the pip-audit version itself:

```yaml
- name: Dependency CVE scan (pip-audit)
  run: pip install pip-audit==2.9.0 && pip-audit
```

This catches known CVEs before they reach production. Also run `pip audit` locally before merging any dependency-related PR.

## Docker Builds in CI

If the repo contains a `Dockerfile`, the CI pipeline must build it to validate image integrity on every PR:

```yaml
- name: Build image
  run: docker build -t app:${{ github.sha }} .
```

For production images, push to the container registry after tests pass. For multi-arch deployments (e.g., ARM64), use `docker/setup-qemu-action` and `docker/build-push-action` with `platforms: linux/amd64,linux/arm64`.

## New Agent Checklist
When adding a new agent directory (e.g. `foo-trader/`) that contains a
`requirements.txt` or `Dockerfile`, you MUST add corresponding Dependabot
entries to `.github/dependabot.yml` in the consuming repo:

- `package-ecosystem: pip` with `directory: /foo-trader`
- `package-ecosystem: docker` with `directory: /foo-trader` (if a Dockerfile exists)

Missing entries mean dependency updates will not be tracked for that agent.

