# Subagent Remediation Plan

**Created:** 2026-08-23 · **Branch:** `claude/subagents-standards-review-3rqz69`
**Scope:** the subagent definitions in `docs/subagent/`, `tools/lint_agents.py`, and the CI jobs that gate them.

> **This is a working document, not a standard. Delete it when Phase 4 completes.**
> It is a point-in-time plan, and this repo is vendored as `.standards` into every
> project — anything left here propagates to all of them on the next submodule bump.
> `CLAUDE.md` § Documentation has no slot for a dated review; that is finding F14
> below, and this file is subject to it. Deleting `docs/subagent-review.md` (Phase 1)
> and this file (end of Phase 4) are both part of the work.

---

## 0. Context for a fresh session

### What this is

A review of the four Claude Code **subagent** definitions in `docs/subagent/`
(`business-analyst`, `project-coordinator`, `qa-tester`, `solutions-architect`) plus
`README-agents.md`, judged against this repo's own standards. Findings are in § 2;
the plan is in § 4.

An earlier review, `docs/subagent-review.md`, produced fixes that were already
applied. It was largely right; it was wrong or incomplete on F3, F4, F5, and F7.
Treat it as history, not as ground truth — it is scheduled for deletion in Phase 1.

### Terminology (do not blur these)

- **agent** — in this repo, a deployable service in its own directory with an
  `AGENT.md`, a `requirements.txt`, a Dockerfile, and Dependabot entries.
- **subagent** — a Claude Code prompt configuration. The four files under review.

### Ground rules while implementing

From `CLAUDE.md`, and non-negotiable:

- `git fetch --prune origin` at session start.
- Always `git -C /Users/dan/VSCode_Projects/standards/standards ...`, never `cd && git`.
- **Never commit to `main`.** Work on `claude/subagents-standards-review-3rqz69`
  (or a new `claude/<description>` branch); merge to `main` via PR only.
- **Never use `sed` to edit files.** Use `Edit` / `Write` / `Read`. For one-off shell
  transformations use `python3 -c "..."`.
- Commit messages via file: `Write` → `/private/tmp/commit_msg.txt`, then
  `git commit -F /private/tmp/commit_msg.txt`, then `rm`. Never inline multiline `-m`.
- `gh` bodies via `--body-file` on a temp file, written with `Write`. Never inline
  multiline `--body`.
- Run the relevant checks and confirm they pass **before** merging a PR.

### Verification commands

```bash
python3 tools/lint_agents.py docs/subagent/     # becomes agents/ after Phase 1
python3 tools/check_links.py .
python3 -m pytest tools/tests/ -v
```

`bandit -r tools/ -ll --exclude tools/tests` and `gitleaks` run in CI; see
`.github/workflows/ci.yml`.

### Environment caveat

The `claude` CLI was **not available** in the environment where this review was
written, so none of the empirical claims in `README-agents.md` could be re-verified
(see F13). Anything in this plan that depends on Claude Code's runtime behaviour —
permission-rule semantics, sandbox coverage, symlink traversal during subagent
discovery — must be re-tested before being relied on. Do not treat this document's
restatements of those claims as verified.

### Prerequisite

`origin/main` was 2 commits ahead of the branch at review time (`c6786f7`
"Document the self-validation gotcha in path-filtered CI", `1186408`
`check_local_install.py`). Rebase before starting — that is Phase 0.

---

## 1. Decision — RESOLVED 2026-08-23: the coordinator goes

**`project-coordinator` is removed.** Decided by the developer on 2026-08-23; the
removal half of Phase 2a is **done** (see § 4, Phase 2). Variant 2b is dead — kept
below only to explain what was rejected and why.

The reasoning that decided it, for anyone re-opening the question later:

Removal argument: it is the weakest fit by `README-agents.md`'s own admission, it is
the only reason subagent nesting is in the threat model at all, and without `Bash` it
cannot file issues — it emits text for the main session to paste, which the main
session could compose itself with full conversation context rather than from a blank
window. Its durable value is four templates and an artifact map, none of which need
to be an agent.

Keep-it argument: the handoff packet is a genuinely good artifact and chaining is
convenient. The cost is that the `Agent(...)` deny rules stay mandatory in every
consuming project's `settings.json` forever, and the settings verifier (Phase 3) has
to check them.

---

## 2. Findings

Severity: **Blocking** = fix before the set is installed anywhere ·
**High** = fix before relying on it unattended · **Medium** / **Low** as marked.

| ID | Severity | Finding | Primary location |
|---|---|---|---|
| F1 | Blocking | Security model is an unenforced "remember to configure `settings.json`" | `docs/subagent/README-agents.md:66-103` |
| F2 | Blocking | Install instructions point at `.standards/agents`, which does not exist | `docs/subagent/README-agents.md:24` |
| F3 | High | `memory:` prohibition unenforced; linter accepts `memory: project` | `tools/lint_agents.py:24` |
| F4 | High | Deny list omits `.claude/**` — settings and the enforcing hook are writable | `docs/subagent/README-agents.md:73-84` |
| F5 | High | `WebFetch(domain:...)` in `allow` is not an egress restriction | `docs/subagent/README-agents.md:82-84` |
| F6 | High | Architect's web grant contradicts the analyst's own stated reasoning | `business-analyst.md:18` vs `solutions-architect.md:19` |
| F7 | High | `Bash` defeats path scoping for **writes**, not just secrets — undocumented | `docs/subagent/qa-tester.md:21` |
| F8 | Medium | Linter does not validate that `Agent(x)` targets exist | `tools/lint_agents.py:108-112` |
| F9 | Medium | `lint_agents.py` has no tests, while `check_sbom.py` has 291 lines of them | `tools/tests/` |
| F10 | Medium | Artifact ownership duplicated in five places, unenforced | `project-coordinator.md:30-43` + each prompt |
| F11 | Medium | Coordinator emits `gh` issue bodies without citing the `--body-file` rule | `project-coordinator.md:58` |
| F12 | Medium | No §1-style inputs/outputs/trust-level declaration for the subagents | all four prompts |
| F13 | Medium | Empirical claims unversioned except the symlink table; unverifiable | `README-agents.md` throughout |
| F14 | Low | `docs/subagent-review.md` ships to every project and is already stale | `docs/subagent-review.md:416-424` |
| F15 | Low | `docs/subagent/` singular; `README-agents.md` won't render as folder index | — |
| F16 | Low | Linter requires `model`; README documents omission as valid | `lint_agents.py:22` vs `README-agents.md:115` |

### Detail on the findings whose fix is non-obvious

**F1 — the headline.** `README-agents.md:66-103` makes `.claude/settings.json`
load-bearing for the `Agent` spawn backstop, `.env` protection, path scoping, and the
sandbox that closes the subprocess gap. Nothing verifies a consuming project applied
any of it. `README-agents.md:103` names the standard it is violating —
"Same move this repo made when it replaced 'remember to regenerate the SBOM' with a
CI freshness check" — and then makes that move for the hook but not for the
configuration the hook depends on. `docs/supply-chain.md` § "Shared tooling scripts"
already establishes the pattern (`check_sbom.py`, invoked from the submodule path).

**F2 — and why the obvious fix is wrong.** All eight `.standards/agents` references
in the repo are wrong; the files are in `docs/subagent/`. `tools/check_links.py`
cannot catch this — they are code-fence strings, and `strip_code()` blanks fenced
blocks by design. Two consequences:

- The "verified on Claude Code 2.1.239" evidence table describes a layout that does
  not exist. The mechanism is presumably still true; the specific commands were never
  run against the real tree.
- **Do not fix this by re-pointing the symlink at `docs/subagent/`.** Claude Code
  scans `.claude/agents/` recursively, so that would drag `README-agents.md` — 130
  lines of markdown with no frontmatter — into the agents scan path. And
  `lint_agents.py:127` skips `README*`, so the one file guaranteed to be malformed as
  an agent definition is the one file exempt from the check. Correct fix: a real
  `agents/` directory at the repo root, README moved out of it.

**F3 — verified, not theoretical.** `README-agents.md:117-121` forbids `memory:` on
any subagent holding `WebFetch`/`WebSearch` (the first ~200 lines of `MEMORY.md` are
injected into the **system prompt**, the subagent can write that file, and `project`
scope is committed to git — a persistent violation of `CLAUDE.md` § Prompt Injection
rule 1, in every clone). `lint_agents.py:24` accepts all three memory values.
Confirmed against a synthetic file:

```
tools: Read, Agent(does-not-exist), Edit
memory: project
color: chartreuse
→ probe.md: ok
```

So the exact configuration the README forbids by name passes CI silently.

**F4.** The deny list covers `.env`, `.standards/**`, `.github/**`, `CLAUDE.md`. It
does not cover `.claude/**`, leaving inside the agents' write surface:
`.claude/settings.json` (every deny rule scoping them, including the `Agent(...)`
backstop the README calls "a genuine second layer" at line 101) and
`.claude/hooks/qa-report-check.sh` (the `SubagentStop` hook whose job is to reject a
`qa-tester` report claiming a pass with no recorded command). `qa-tester` holds
`Bash` and is the agent that hook constrains. Whether Claude Code independently
special-cases writes to its own settings was **not verified** — the recommended
configuration should not depend on it either way.

**F5.** An `allow` entry auto-approves; it does not deny anything else. Without a
corresponding `WebFetch` deny or a default-deny permission mode, the architect's
egress is unconstrained and the entry only removes a prompt for one domain. Carried
over verbatim from `subagent-review.md:344` without being questioned. This also makes
`subagent-review.md:312-314` wrong: `WebFetch` **is** the egress leg (read the repo,
exfiltrate by URL construction), so removing `Bash` did not break the
fetch-decide-act-egress chain.

**F7.** `README-agents.md:102` correctly documents that `Read`/`Edit` denies do not
cover a subprocess opening `.env` itself, and prescribes the sandbox. The same gap
applies to **writes** and is nowhere acknowledged. `qa-tester.md:21` claims "these
path limits are what enforce it" — false for the one agent holding `Bash`, since
denies don't reach `python -c "open('src/x.py','w')..."`. The OS sandbox does not
help: it permits writes inside the project directory, which is where product source
lives. "Fix nothing" is also the rule whose violation is hardest to detect, because a
QA agent that quietly fixed the code will report a pass.

---

## 3. Recommendation the plan implements

Cut to three subagents and mechanize what remains.

- **Remove `project-coordinator`** as a subagent (pending § 1). Move its artifact
  map, ID scheme, handoff-packet format, and standing definition-of-done items into
  `docs/delivery-artifacts.md` — that *is* a standard and belongs in this repo, and
  it becomes the single source of truth that fixes F10.
- **Strip `WebSearch`/`WebFetch` from `solutions-architect`**, keep the agent and
  keep rule 7's text. Its stated need (a service's SLA, a library's limits, a
  compliance control) is satisfiable by the remedy `business-analyst.md:18` already
  uses: route to `## Open Questions`.
- **Keep `business-analyst` and `qa-tester`** unchanged in scope.

Why this is the whole argument: with the coordinator gone and web tools stripped, **no
subagent holds `Agent` and none holds `WebFetch`.** The required per-project
`settings.json` collapses from a 25-line block (sandbox + hooks + `Agent` denies + a
`WebFetch` allow that does not work) to `.env` denies, `.claude/**` denies, and
`sandbox.enabled` for `qa-tester`. That is small enough for a
`tools/check_agent_settings.py` — invoked from the submodule exactly as
`check_sbom.py` is — to verify in a consuming project's CI, which converts F1 from a
README paragraph into a check. Four agents needing manual hardening you cannot verify
is worse than three that do not.

---

## 4. Phases

Phases 1–2 are the ones that matter. Phase 3 is what makes the set defensible as a
shared submodule. Phase 4 is cleanup. Each phase should be its own commit; the whole
set can be one PR.

### Phase 0 — rebase

```bash
git -C /Users/dan/VSCode_Projects/standards/standards fetch --prune origin
git -C /Users/dan/VSCode_Projects/standards/standards rebase origin/main
```

Two commits: `c6786f7` (CI self-validation gotcha) and `1186408`
(`check_local_install.py`). This repo's own `ci.yml` already satisfies the
self-validation guidance — every paths-filter output includes
`.github/workflows/ci.yml`. No change needed there; confirm it still holds after any
`ci.yml` edit in Phase 1.

**Done when:** branch is on top of `origin/main`, all three verification commands pass.

### Phase 1 — make it installable · fixes F2, F14, F15 — **DONE 2026-08-23**

`docs/subagent/` → `agents/` at the repo root; `README-agents.md` → `docs/subagents.md`;
`docs/subagent-review.md` deleted; `ci.yml` filters and the `lint_agents.py` docstring
and invocation updated. The `.standards/agents` references in the install block were
made correct by the move rather than rewritten — the layout now matches what the
evidence table describes. Steps as originally written, for reference:

1. `git mv docs/subagent agents` — a real `agents/` directory at the repo root, so
   the documented symlink target is correct and the scan path contains **only** agent
   definitions.
2. `git mv agents/README-agents.md docs/subagents.md` — out of the scan path
   entirely; it is documentation, not an agent definition.
3. Delete `docs/subagent-review.md` (F14). Its durable content is already in the
   README; its § 9 is stale (it reports this repo has no `dependabot.yml` and no CI,
   both of which now exist); it duplicates the wrong `.standards/agents` path; and
   its `SEC-*` IDs are referenced by nothing.
4. Update `.github/workflows/ci.yml`: the `agents` filter paths
   (`docs/subagent/**` → `agents/**`, and add `docs/subagents.md`) and the
   `lint-agents` invocation (`python tools/lint_agents.py docs/subagent/` →
   `agents/`).
5. Update `tools/lint_agents.py` docstring (lines 5 and 14) to the new paths.
6. In `docs/subagents.md`, correct every `.standards/agents` reference so it matches
   reality — the install block, the evidence table, and the surrounding prose. Mark
   the evidence table as **describing a layout that has since changed**, or re-run the
   probe against the real tree and re-pin it (see the environment caveat in § 0).

**Done when:** `python3 tools/lint_agents.py agents/` passes, `check_links.py` passes,
no `.standards/agents` string remains anywhere:

```bash
grep -rn "standards/agents" /Users/dan/VSCode_Projects/standards/standards --include="*.md" --include="*.py" --include="*.yml"
```

### Phase 2 — cut and consolidate · fixes F6, F10, F11

**Status: DONE 2026-08-23 (all five steps).**

Steps 4–5 completed after Phase 1: `WebSearch`/`WebFetch` stripped from
`solutions-architect`; its rule 6 no longer says "search and cite", rule 7 rewritten to
forbid stating an external fact from recall and route it to `## Open Questions`, and a
new rule 8 covers content pasted into its context by the main session. The
business-analyst's rule 6 no longer routes external facts to the architect (it no
longer holds the tools) — they go to the main session. The required-configuration
block gained `Edit(./.claude/**)` (F4) and lost the `WebFetch` allow entry, with a note
explaining that an `allow` entry restricts nothing (F5). The `memory:` section was
rewritten: the injection chain no longer runs through the architect's web access, but
it is not closed — a subagent reading repo files still ingests content it did not
author — so the prohibition is now unconditional for this set.

Original steps:

Done: `docs/delivery-artifacts.md` created as the single source of truth (artifact
map, ID scheme, terminology, charter/work-item/RAID templates, handoff packet,
standing DoD items, sequencing, and a "Who coordinates" section recording why there is
no coordinator subagent). `docs/subagent/project-coordinator.md` deleted. The three
remaining prompts point at the new page; their dangling "route it to the coordinator"
instructions now route to the main session. `README-agents.md` updated throughout
(four → three, the `Agent`-deny rationale no longer references a grant that no longer
exists, and the Scope section records the removal). F11 is fixed inside the new
page — its issue templates cite `CLAUDE.md` § GitHub CLI and the `--body-file` form.

Remaining: steps 4 and 5 below — stripping the architect's web tools and rewriting the
required-configuration section. Both were deferred as out of scope for the
coordinator decision and still need approval.

**2a — removal variant (chosen):**

1. Create `docs/delivery-artifacts.md` holding, as the single source of truth: the
   artifact map (`project-coordinator.md:30-43`), the ID scheme (line 47), the
   handoff-packet definition (line 156), the charter template (lines 79-109), the
   work-item and RAID issue templates (lines 111-141), and the standing
   definition-of-done items (lines 143-152). Keep the `docs/delivery/` rationale
   (line 45) and the "work items are GitHub Issues" rationale (line 51) — both are
   real standards derived from `CLAUDE.md` § Documentation.
2. Delete `agents/project-coordinator.md`.
3. In the three remaining prompts, replace the restated "owned paths" rule with a
   pointer to `docs/delivery-artifacts.md` (F10). Keep one line naming that
   subagent's own outputs; delete the duplicated terminology paragraph in favour of a
   pointer to the same file.
4. Strip `WebSearch, WebFetch` from `agents/solutions-architect.md` frontmatter
   (line 4). Keep operating rule 7's text — it still applies to anything pasted into
   its context — but reword its opening so it no longer implies the subagent holds
   those tools. Amend rule 6 ("search and cite rather than recall") to route external
   facts to `## Open Questions`, mirroring `business-analyst.md:18`.
5. Rewrite the required-configuration section of `docs/subagents.md` against the
   now-smaller surface: drop the `Agent(...)` denies and the `WebFetch` allow, add the
   `.claude/**` denies (F4), and fix the `allow`-is-not-a-deny error (F5) — state
   plainly that an `allow` entry auto-approves and restricts nothing.

**2b — keep-the-coordinator variant (REJECTED 2026-08-23, recorded for history):** do steps 1, 3, 4, 5 above, but keep
`agents/project-coordinator.md` and keep the `Agent(business-analyst)`,
`Agent(solutions-architect)`, `Agent(qa-tester)` denies in the documented
`settings.json`. Phase 3's settings verifier must then also assert
`Agent(general-purpose)` and `Agent(claude)` are denied. Step 1 still applies — the
artifact map moves out of the prompt and the coordinator points at it.

**Done when:** linter passes on the remaining agents; no subagent frontmatter contains
`WebFetch`, `WebSearch`, or (in 2a) `Agent`; ownership facts appear in exactly one file.

### Phase 3 — mechanize · fixes F1, F3, F8, F9, F16 — **DONE 2026-08-23**

`lint_agents.py` now rejects `memory:` outright (any value, not just an invalid
one), validates `Agent(x)` scopes against the definitions actually present,
validates `color`, and — given `--artifact-map docs/delivery-artifacts.md` —
cross-checks each prompt's owned-paths rule against the map in both directions.
It fails loudly if the map parses to zero rows, so a table-format change cannot
leave the check silently passing. `main()` became `main_argv(argv)` so it is
testable. `tools/tests/test_lint_agents.py` and
`tools/tests/test_check_agent_settings.py` added: 95 tests pass, bandit clean.

`tools/check_agent_settings.py` added (F1): a stdlib-only script a consuming
project runs in CI against its `.claude/settings.json`, asserting every required
deny plus `sandbox.enabled`, printing why each rule exists when it fails, and
flagging an `allow` entry written as though it restricted something. Documented
in `docs/subagents.md` and added to the CI integration checklist in
`docs/supply-chain.md`. F16 resolved by documenting in the linter why `model` is
required rather than allowed to default.

Note for whoever picks up Phase 4: `tools/check_local_install.py` (added on main
in `1186408`) has no tests either — the same F9 argument applies to it, and it is
also executed by consuming projects. Not in this plan's scope; worth its own pass.

Original steps:

1. **`tools/lint_agents.py`:**
   - Reject **any** `memory:` value outright (F3), with the README's reasoning in the
     error string. Replace `VALID_MEMORY` rather than extending it — the rule is "not
     enabled, deliberately", so the linter should encode the prohibition, not the
     field's valid values.
   - Validate that each `Agent(x)` scope resolves to a `<x>.md` in the same directory
     (F8). Verified gap: `Agent(does-not-exist)` currently passes.
   - Validate `color` against the accepted set; `chartreuse` currently passes.
   - Cross-check each prompt's declared owned paths against
     `docs/delivery-artifacts.md` (F10) so the two cannot drift.
   - Keep requiring `model` (F16) — explicit over inherited default is the right call,
     the same reasoning as `CLAUDE.md` § Claude API — Explicit `thinking`
     Configuration. Reconcile the wording in `docs/subagents.md` so both say so.
2. **`tools/tests/test_lint_agents.py`** (F9): one case per rule above, plus the
   existing rules (bare `Agent`, name/stem mismatch, missing keys, short description,
   unterminated frontmatter). Follow the style of `tools/tests/test_check_sbom.py`.
   `tools/tests/conftest.py` already exists.
3. **`tools/check_agent_settings.py`** (F1): a stdlib-only script a consuming project
   runs in CI against its `.claude/settings.json`, asserting the `.env` denies, the
   `.claude/**` denies, `sandbox.enabled`, and (2b only) the `Agent(...)` denies.
   Invoked from the submodule path, parameterized by CLI flags — follow the
   convention in `docs/supply-chain.md` § "Shared tooling scripts":

   ```yaml
   - name: Subagent permission check
     run: python .standards/tools/check_agent_settings.py --settings .claude/settings.json
   ```

   Document it in `docs/subagents.md` and add it to the CI integration checklist in
   `docs/supply-chain.md`.
4. **CI:** the `tools` paths filter already covers `tools/**`, so `test-tools` picks
   up the new tests with no workflow change. Confirm `bandit -r tools/ -ll` stays
   clean on the new script.

**Done when:** `pytest tools/tests/ -v` passes with the new suite; a synthetic agent
file carrying `memory: project`, `Agent(does-not-exist)`, or a bogus `color` **fails**
the linter.

### Phase 4 — honest caveats · fixes F7, F11, F12, F13

1. **F7:** add the write-side subprocess gap to `qa-tester`'s rule 9 and to
   `docs/subagents.md`. State plainly that "fix nothing" and the path limits are
   prompt-level only for the one subagent holding `Bash`, that the OS sandbox does not
   close it (it permits writes inside the project directory), and that reviewing
   `git diff` after a QA session is the actual control. Do not leave
   "these path limits are what enforce it" standing — it is false as written.
2. **F11:** wherever a subagent emits input for a `gh` command, cite `CLAUDE.md`
   § GitHub CLI (`--body-file` on a temp file written with the `Write` tool). Applies
   to the coordinator under 2b, and to `docs/delivery-artifacts.md`'s issue templates
   under either variant. Same for § Git Commit Messages if any prompt ever suggests a
   commit.
3. **F12:** add a compact inputs/outputs/trust-level table to each prompt, modelled on
   `docs/security-protocols.md` § 1 minus the deployable-specific rows. The architect
   is the case that matters: even without `WebFetch` it consumes repo content and
   emits artifacts that `qa-tester` and the main session act on.
4. **F13:** version-pin every remaining mechanical claim in `docs/subagents.md` the
   way the symlink table is pinned (`verified on Claude Code <version>, <platform>`),
   with a note to re-verify on a major bump. The unpinned claims carrying security
   weight: path rules consulted for `Edit`/`Read` only; a `Read` deny implying
   `Edit`/`Write` deny; `deny` beating `allow`; sandbox covering child processes;
   `SubagentStop` exit-2 semantics; `AskUserQuestion` always stripped; nesting depth 3.
   `CLAUDE.md` § Claude API — Explicit `thinking` Configuration is built on exactly
   this argument about undocumented defaults drifting across versions.
5. **Delete this file.**

**Done when:** all verification commands pass, no unpinned mechanical claim remains in
`docs/subagents.md`, and `docs/subagent-remediation-plan.md` no longer exists.

---

## 5. What this plan deliberately does not do

- It does not change the *doctrine* in the prompts. Testable-or-it-doesn't-ship,
  never-invent-a-fact, batch ambiguity into `## Open Questions`, permanent IDs with
  `[SUPERSEDED by X]`, separation of authorship, and "derive from the standards, cite
  the section, don't reinvent the number" are the best content in the set and should
  survive intact.
- It does not add a fifth subagent, and it does not expand any subagent's scope.
- It does not adopt the plugin-marketplace distribution alternative
  (`claude plugin install` with release-tag pinning). That remains the documented
  fallback if symlink traversal during subagent discovery ever breaks — it is
  undocumented behaviour, not a contract.
