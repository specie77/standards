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

**Inspecting environment variables in running containers**: never dump the full
environment (`docker compose exec <svc> env`, `printenv`, etc.) — this prints
secret values into the conversation transcript, which persists in Claude Code's
local session history. To check whether a variable is set, check presence/
emptiness without printing the value, e.g.:

```bash
docker compose exec <svc> python -c "import os; print(bool(os.environ.get('SOME_VAR')))"
```

If a specific non-secret value is needed (e.g. `MCP_PORT`), grep for that single
key by name rather than dumping everything. The same applies to reading
container logs that may echo secrets (tokens in HTTP request URLs, etc.) —
redact or avoid printing the secret-bearing portion.

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

## Claude API — Explicit `thinking` Configuration

Never omit the `thinking` parameter on a Claude API call and rely on the model's default — the default is not stable across model versions (e.g. `claude-sonnet-4-6` defaulted to thinking-off when omitted; `claude-sonnet-5` defaults to adaptive thinking when omitted). An omitted parameter that silently changes behavior on a model upgrade is exactly the kind of drift these standards exist to prevent.

**Set `thinking={"type": "disabled"}` explicitly by default.** Only enable it (`{"type": "adaptive"}`, or the model's supported equivalent) when the call actually benefits from extended reasoning — open-ended analysis, multi-step planning, ambiguous input. A call that forces a single tool result via `tool_choice`, does structured extraction, or sits on a latency-sensitive user-facing path almost never needs it.

Before enabling thinking on a given call site, confirm with the developer that reasoning is actually needed there — don't enable it speculatively "for better results." Extra reasoning adds latency and token cost, and — per the model's own migration notes — a `thinking`-omitted call can silently switch behavior on the next model upgrade in either direction. Explicit configuration makes intent durable across model migrations instead of inheriting whatever a new model's default happens to be.

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

**Secrets-dependent steps fail on Dependabot PRs by default.** GitHub withholds repository secrets from workflows triggered by Dependabot's `pull_request` event (a supply-chain safeguard, so a malicious dependency bump can't exfiltrate them). Any CI step that needs a secret — a registry login for an image CVE scan, a paid API key, a deploy credential — will fail on every Dependabot PR with an auth error, regardless of the bump's content. Guard those specific steps with `if: github.actor != 'dependabot[bot]'` rather than gating the whole job; keep the secret-free parts (e.g. `docker build` itself) running so the bump still gets real validation.

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

## Static Analysis & Secrets Scanning

`pip-audit` only catches known CVEs in dependencies — it does not catch vulnerabilities in your own code, or a credential accidentally committed. Every CI pipeline must also include:

- **SAST**: `bandit -r <package_dir> -ll` against every package's source directory, pinned version, after dependency install and before tests.
- **Secrets scanning**: `gitleaks detect` against the full git history (not just the working tree) on every push/PR.

Both fail the build on findings. See `docs/security-protocols.md` §11 for CI YAML and triage guidance (fix or a scoped `# nosec` justification — never a blanket rule disable).

## CI Concurrency (Cancel Superseded Runs)

Add a `concurrency` block to every workflow so that rapid successive pushes/merges don't each burn a full CI run to completion:

```yaml
concurrency:
  group: ci-build-${{ github.ref }}
  cancel-in-progress: true
```

Default `cancel-in-progress: true` for **all** refs, including `main`. If several PRs merge within seconds of each other, only the latest run per ref completes — earlier in-progress runs are cancelled rather than queuing and consuming minutes. Only set `cancel-in-progress: false` (or restrict it to non-default branches) if the workflow performs an automated deploy where a mid-run cancellation could leave a partial/inconsistent deployment — a project that deploys manually (or not at all) through CI has no reason to protect main-branch runs from cancellation.

## Docker Builds in CI

If the repo contains a `Dockerfile`, CI must validate that it builds.

**Pull requests**: run a fast, native-arch, no-push build to catch Dockerfile/dependency breakage early:

```yaml
- name: Build image (validation only)
  run: docker build -t app:${{ github.sha }} .
```

**Merge to `main`**: build and push the production image(s) to the registry. For multi-arch deployments (e.g. ARM64 for Orange Pi), use `docker/setup-qemu-action` and `docker/build-push-action` with the target `platforms`.

**Solo-developer / single-consumer projects**: do not run the registry build-and-push job on PR branches. It duplicates the main-branch build (often QEMU-emulated and multi-minute) on every merge, and branch-tagged images (`:<branch-name>`) have no consumer. Gate the push job with `if: github.event_name == 'push'` (or split PR validation and main build/push into separate jobs) to conserve the Actions minute budget.

## CI Minute Budget — Gate Everything on Changed Paths

GitHub Actions minutes are a shared, finite budget across all of a developer's repos (e.g. the free tier's 2,000 min/month). Docker builds — especially QEMU-emulated multi-arch pushes — are the most expensive line item and the first place to cut. **Default every new CI pipeline to path-filtered, change-gated jobs; do not build on every push.**

**Required pattern for any repo with more than one buildable/testable unit** (a monorepo of packages, or a single package plus a Docker image): add a `changes` job using `dorny/paths-filter` as the first job, and gate every downstream test/build/push job on its output. Tests can stay cheap and broad (`if: needs.changes.outputs.<pkg> == 'true'`); builds and pushes are the ones that must never run unconditionally.

```yaml
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      app: ${{ steps.filter.outputs.app }}
    steps:
      - uses: actions/checkout@<pinned-sha>
      - uses: dorny/paths-filter@<pinned-sha>
        id: filter
        with:
          filters: |
            app:
              - 'src/**'
              - 'Dockerfile'

  build-push:
    needs: changes
    if: needs.changes.outputs.app == 'true' && github.event_name == 'push'
    # ...
```

**The shared-dependency gotcha:** if a Dockerfile does `COPY` on a path outside its own package directory (a shared/core library, a common `lib/`, a vendored submodule), that copied content is baked into the image — so the build/push job's `if:` condition must also include that shared path's filter output, not just the package's own directory. A monorepo with `packages/core` consumed by `packages/api` and `packages/worker` needs each image's build-push gate to be `needs.changes.outputs.api == 'true' || needs.changes.outputs.core == 'true'` (and likewise for `worker`) — gating on `api` alone means a core-only change silently ships a stale image, passing CI with no rebuild. Trace every `COPY`/`ADD` line in each Dockerfile back to its filter path before finalizing the gate condition.

**When adding this pattern to an existing pipeline**, audit for the same gap: list every Dockerfile's `COPY`/`ADD` sources, cross-reference against the paths-filter definitions, and add any missing filter output to that image's build/push `if:` condition.

## New Agent Checklist
When adding a new agent directory (e.g. `foo-trader/`) that contains a
`requirements.txt` or `Dockerfile`, you MUST add corresponding Dependabot
entries to `.github/dependabot.yml` in the consuming repo:

- `package-ecosystem: pip` with `directory: /foo-trader`
- `package-ecosystem: docker` with `directory: /foo-trader` (if a Dockerfile exists)

Missing entries mean dependency updates will not be tracked for that agent.

## Self-Hosted / Home-Network Deployment Security

For any project running on hardware you own and administer (home server, NAS, Orange Pi/Raspberry Pi, etc.) rather than a managed cloud platform:

- **Host & network hardening** — SSH key-only auth, automatic OS security updates, default-deny host firewall, and (where the router supports it) network segmentation between the exposed box and personal devices. Full checklist: `docs/security-protocols.md` §12.
- **Cloudflare Tunnel exposure** — if a service is exposed via `cloudflared`, **Cloudflare Access (Zero Trust) is required** as a policy on that hostname, in addition to any application-level auth — defense-in-depth so an app-auth bug still fails closed at the edge. Also enable WAF managed rules and edge rate limiting. Full checklist + periodic external scan cadence: `docs/security-protocols.md` §13.
- **Browser/PWA-facing auth** — never gate backend access behind a secret embedded in client-side code; it is extractable by definition. Prefer passing through Cloudflare Access's signed JWT rather than issuing a bespoke token from a client-supplied static secret. Any HTML/JS-serving response sets `Content-Security-Policy`, `Strict-Transport-Security`, `X-Content-Type-Options`, `Referrer-Policy`. Full guidance: `docs/security-protocols.md` §14.
- **Secret rotation cadence** — Cloudflare tunnel tokens every 90 days; OAuth client secrets, LLM/API keys, and internal shared secrets every 180 days; anything suspected exposed, immediately. Record last-rotated dates in the project's `docs/security-cadence.md`. Full table: `docs/security-protocols.md` §5.1.

