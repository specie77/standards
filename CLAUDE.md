# Universal Development Standards

These rules apply to every project. Project-specific CLAUDE.md files import this file and add their own context below.

## About the Developer

Solo developer. Works methodically — prefers explicit step tracking and phased plans over sweeping changes. Calibrate communication accordingly: be direct and concise, confirm approach before large changes, don't over-explain.

---

## Session Start

Run `git fetch --prune origin` at the start of every session. If the remote is ahead, pull immediately without asking. The `--prune` flag removes any local remote-tracking refs for branches already deleted on GitHub — keeping the local branch list in sync without touching anything on the remote.

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

Full patterns and checklists are in `docs/security-protocols.md`. The rules below are the active constraints Claude enforces on every code change.

**Input validation**
- Validate all external inputs at system boundaries before acting on them using a **strict whitelist**, not a blacklist.
- Numeric inputs: use `isdecimal()` + range check. Never use `isdigit()` — it accepts Unicode superscripts that `int()` then raises on.
- String inputs: match against a regex whitelist of expected characters/format before use.
- Structured inputs (dicts, JSON): validate with `pydantic` or `jsonschema` against a fixed schema.
- Reject and raise on invalid input. Never silently strip or truncate security-sensitive fields.

**Injection prevention**
- **SQL**: parameterised queries only. Never interpolate user data into SQL strings.
- **Shell**: `subprocess` with a list of arguments only. Never `shell=True` with dynamic data, never `os.system()`.
- **Path traversal**: resolve paths with `pathlib.Path.resolve()` and assert they are `relative_to()` the allowed directory before use.
- **SSRF**: when making outbound HTTP calls to a user-supplied URL, whitelist the scheme (`https`) and reject private/loopback IP ranges before issuing the request.
- **Prompt injection**: see the dedicated section below.

**General**
- Never log secrets, tokens, or sensitive data.
- Catch specific exceptions; never swallow errors silently.
- Verify message/callback sender identity before processing any instruction. Use `hmac.compare_digest()` for HMAC checks — never `==`.

## Prompt Injection

Prompt injection is the AI-era equivalent of SQL injection: untrusted content in an LLM context attempts to redirect model behaviour.

- **Never interpolate untrusted content into a system prompt.** System prompts define behaviour; treat them as code, not templates.
- Pass untrusted content as a separate user message or tool result — not formatted into the system prompt or a prior assistant turn.
- Wrap externally-sourced content in a structural delimiter and instruct the model to treat it as untrusted:
  ```
  <untrusted_external_data>
  {external_content}
  </untrusted_external_data>
  ```
- Validate LLM outputs before acting on them. A model completion is untrusted input — apply the same schema/regex validation used for any external source.
- Grant agents only the tool permissions required for their stated purpose. Minimal privilege limits the blast radius of a successful injection.

## Agent Interface Documentation

Every agent directory must contain an `AGENT.md` declaring its complete interface. See `docs/security-protocols.md` §1 for the full template.

Required content:
- **Purpose** — one sentence.
- **Inputs table** — name, type, source, validation rule, trust level (untrusted / semi-trusted / trusted).
- **Outputs table** — name, type, destination, whether it is sanitised before output.
- **Trust boundary summary** — which boundaries are crossed and how.
- **Error behaviour** — what callers receive on failure (never raw stack traces or secrets).

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

After a PR is merged and its remote branch deleted on GitHub, run `git fetch --prune` to remove the stale `origin/*` tracking ref locally. Then delete the local branch with `git branch -d <branch>` (or `-D` if squash-merged). This keeps the local branch list in sync with GitHub.

## GitHub CLI (gh)

Never pass multiline content inline to `gh` commands. Write the body to a temp file and use `--body-file`:

```
# 1. Write tool → /tmp/gh_body.md
# 2. Bash:
gh pr create --title "..." --body-file /tmp/gh_body.md
rm /tmp/gh_body.md
```

Use the `Write` tool to create the temp file — not `cat` or `echo` in Bash (those are restricted). Multiline strings in `--body` break the `gh *` allowlist pattern match and trigger permission prompts.

## Documentation

- Feature requests and future enhancements → open a GitHub issue.
- Core build functionality, standards, architecture, operational runbooks → `.md` files in `docs/`.


## Dependabot

Every repo must have `.github/dependabot.yml` with an entry for each package ecosystem present:

- `github-actions` — always required
- `pip` — if the repo contains Python dependencies
- `docker` — if the repo contains a `Dockerfile`

Weekly schedule. Each project chooses its own day. Use `open-pull-requests-limit` of 5–10 per ecosystem.

Before merging a Dependabot PR, confirm CI passes. If a bump fails due to an incompatible transitive dependency (e.g., `redis>=7` vs `celery<6`), close the PR with a comment explaining the blocker rather than leaving it stale.

## GitHub Actions Pinning

Pin every third-party action to a full commit SHA, not a floating tag. Add the version as a comment:

```yaml
- uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2
```

Floating tags (`@v4`, `@main`) are mutable and expose the pipeline to supply-chain attacks. Dependabot keeps pinned SHAs up to date automatically.

## Dependency CVE Auditing

@docs/supply-chain.md

Every CI pipeline must include a `pip-audit` step that runs after dependency installation and before tests. Pin the pip-audit version itself:

```yaml
- name: Dependency CVE scan (pip-audit)
  run: pip install pip-audit==2.9.0 && pip-audit
```

This catches known CVEs before they reach production. Also run `pip audit` locally before merging any dependency-related PR.

## Docker Builds in CI

If the repo contains a `Dockerfile`, CI must validate that it builds.

**Pull requests**: run a fast, native-arch, no-push build to catch Dockerfile/dependency breakage early:

```yaml
- name: Build image (validation only)
  run: docker build -t app:${{ github.sha }} .
```

**Merge to `main`**: build and push the production image(s) to the registry. For multi-arch deployments (e.g. ARM64 for Orange Pi), use `docker/setup-qemu-action` and `docker/build-push-action` with the target `platforms`.

**Solo-developer / single-consumer projects**: do not run the registry build-and-push job on PR branches. It duplicates the main-branch build (often QEMU-emulated and multi-minute) on every merge, and branch-tagged images (`:<branch-name>`) have no consumer. Gate the push job with `if: github.event_name == 'push'` (or split PR validation and main build/push into separate jobs) to conserve the Actions minute budget.

## New Agent Checklist
When adding a new agent directory (e.g. `foo-trader/`) that contains a
`requirements.txt` or `Dockerfile`, you MUST add corresponding Dependabot
entries to `.github/dependabot.yml` in the consuming repo:

- `package-ecosystem: pip` with `directory: /foo-trader`
- `package-ecosystem: docker` with `directory: /foo-trader` (if a Dockerfile exists)

Missing entries mean dependency updates will not be tracked for that agent.

