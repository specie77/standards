# Delivery subagent set for Claude Code

Three Claude Code **subagents** that split a project into functional spec → quality attributes → verification, so each one's output is usable by the next. The shared artifact map, ID scheme, and templates they work from live in `docs/delivery-artifacts.md` — a standard in its own right, readable without loading any subagent.

The charter and the coordination between the three are the **main session's** job. There is no coordinator subagent; `docs/delivery-artifacts.md` § "Who coordinates" explains why, and carries the charter template and handoff-packet format it used to hold.

> **Naming.** In this repo an *agent* is a deployable service in its own directory with an `AGENT.md`, a `requirements.txt`, a Dockerfile, and Dependabot entries. These three are *subagents* — prompt configurations loaded by Claude Code. The two are not interchangeable; say which you mean. Full definition: `docs/delivery-artifacts.md` § Terminology.

**Where the files are.** The definitions live in `agents/` at the repo root; this page lives in `docs/`. That split is deliberate: consuming projects symlink `agents/` into `.claude/agents/`, which Claude Code scans **recursively**, so anything in that directory is treated as an agent definition. A README sitting beside them would be scanned as one. Keep `agents/` to definitions only.

## Install — symlink the submodule, don't copy

`docs/supply-chain.md` § "Shared tooling scripts" rules out copy-paste distribution: a copied file has no mechanism keeping copies in sync, a fix applied in one project has to be manually re-applied everywhere else, and nothing catches silent drift. Prompts get tweaked in place far more casually than code does, so the odds are worse here than for `check_sbom.py`.

Claude Code does not discover `.standards/agents/`. It scans `.claude/agents/` (recursively) and `~/.claude/agents/`. A symlink bridges the two — verified on Claude Code `2.1.239`, Linux:

| Layout | Discovered? |
|---|---|
| `.claude/agents/business-analyst.md` (real file — control) | Yes |
| `.claude/agents/standards -> ../../.standards/agents` (symlinked **directory**) | **Yes** |
| `.claude/agents/business-analyst.md -> ../../.standards/agents/business-analyst.md` (symlinked **file**) | **Yes** |
| `.standards/agents/business-analyst.md`, no symlink (negative control) | **No** |

Use one symlinked directory per project, so adding a fourth subagent upstream needs no per-project change:

```bash
mkdir -p .claude/agents
ln -s ../../.standards/agents .claude/agents/standards
git add .claude/agents/standards
```

`git submodule update --remote .standards` then propagates prompt fixes exactly as it already propagates `CLAUDE.md` and `tools/check_sbom.py`. Project-local subagents live beside the symlink in `.claude/agents/` and are unaffected.

If the `agents` directory didn't exist when the session started, restart once; otherwise Claude Code picks up edits within a few seconds.

**Caveats, accepted knowingly:**

- Symlink traversal during subagent discovery is **not documented**. It works today; it is not a contract. Pin it with the probe below rather than trusting it silently — same reasoning as the SBOM freshness check.
- Git stores symlinks natively, but Windows checkouts need `core.symlinks=true` plus developer mode or admin rights.
- A symlinked directory means the *upstream* prompt is what loads: an upstream change silently alters behaviour in every consuming project on the next submodule bump. Same trade-off already accepted for `CLAUDE.md`.
- The documented alternative is publishing this repo as a plugin marketplace (`claude plugin install`) with release-tag version pinning. It adds real version control at the cost of a second distribution system alongside the submodule. Revisit if the symlink ever breaks.

## Verify they loaded

**`claude plugin validate .claude/agents` is not a load check.** Pointed at a bare `.claude/agents` directory it exits 0 on garbage — a space-bearing `name`, a nonexistent tool, a bogus `model`, an invalid `memory` value, even a file with no frontmatter at all all pass. Pointed at a real plugin root it fails for the opposite reason (`No manifest found`). Treat "validation passed" as "the directory exists".

Ask a session what it can actually see instead, and assert the three names appear:

```bash
claude --print "List every subagent type available via the Agent tool."
```

## Use

Automatic delegation works off the `description` field. To force a specific subagent, @-mention it or name it:

```
Use the business-analyst subagent to write requirements for the invoice export feature
Have the solutions-architect derive NFRs from docs/delivery/10-functional-requirements.md
Use the qa-tester subagent to run the suite and triage the failures
```

Chained, which is the normal path — you sequence them, one dispatch at a time, because you are the only participant who has the whole conversation in context:

```
Read docs/delivery-artifacts.md, then dispatch the business-analyst with a handoff packet
for the invoice export feature. When it returns, review its Open Questions before
dispatching the solutions-architect.
```

Write a **handoff packet** for each dispatch — goal, files to read, files to write, constraints, definition of done, out of scope. A subagent starts with a blank context window, so a vague delegation prompt is the single biggest cause of thin output. The six-part format is in `docs/delivery-artifacts.md` § "The handoff packet".

## Required project configuration

The frontmatter alone is not a security boundary. Add this to `.claude/settings.json` before using the set unattended — and verify it with `.standards/tools/check_agent_settings.py` in CI (below) rather than trusting that you did:

```jsonc
{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./**/.env)",
      "Edit(./.standards/**)",       // upstream standards are not project-editable
      "Edit(./.github/**)",          // CI and Dependabot config
      "Edit(./CLAUDE.md)",
      "Edit(./.claude/**)",          // the settings and hooks that enforce all of the above
      "Agent(general-purpose)",      // backstop, independent of frontmatter
      "Agent(claude)"
    ]
  },
  "sandbox": { "enabled": true },          // OS-level; covers Bash child processes
  "hooks": {
    "SubagentStop": [
      { "matcher": "qa-tester",
        "hooks": [{ "type": "command",
                    "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/qa_report_check.py --check qa-report" }] },
      { "matcher": "business-analyst",
        "hooks": [{ "type": "command",
                    "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/qa_report_check.py --check none --forbid-tbd 'docs/delivery/1*.md' --forbid-tbd 'docs/delivery/30-*.md'" }] }
    ]
  }
}
```

Notes on each piece:

- **Path scoping is checked against `Edit(path)` and `Read(path)` rules only.** A path rule written for `Write`, `NotebookEdit`, or `Glob` is accepted, never consulted, and warned about at startup. Use `Edit(docs/**)`, not `Write(docs/**)`; use `Read(docs/**)`, not `Glob(docs/**)`. A `Read` deny rule also blocks `Edit`/`Write` on the same path.
- **`deny` beats `allow` unconditionally** — a broad deny cannot carry allowlist exceptions. Write a narrow deny only when you mean it absolutely.
- **`Edit(./.claude/**)` protects the enforcement layer itself.** Without it, the deny list above and the `SubagentStop` hook below both sit inside the subagents' write surface — including for `qa-tester`, the subagent that hook exists to constrain. A control a subagent can edit is not a control. This is the one deny whose absence undoes the others.
- **An `allow` entry is not a restriction.** It auto-approves a call so it runs without prompting; it does not deny anything left off the list. There is no `allow`-implies-default-deny behaviour, so an entry like `WebFetch(domain:docs.python.org)` constrains nothing — it only removes a prompt for that one domain. To actually restrict a capability, deny it, or don't grant the tool in the frontmatter at all. (This set takes the second route: no subagent holds a web tool.)
- **The `Agent(...)` denies are a genuine second layer**, evaluated by the permission system rather than by frontmatter, so they hold even if a prompt is edited. No subagent in this set holds an `Agent` grant at all — none of them can spawn another — so these denies are pure backstop: they keep that true if a prompt is ever edited to add one. `general-purpose` and `claude` are named because both hold every tool in the session.
- **`sandbox.enabled` is what closes the secrets gap for `qa-tester`.** `Read`/`Edit` deny rules cover Claude's file tools and the file commands Claude Code recognises inside Bash (`cat`, `head`, `tail`, `sed`) — they do **not** cover a Python or Node script that opens `.env` itself. The sandbox is enforced for every Bash command *and its child processes*. Pair it with a `PreToolUse` hook allowlisting the project's test runner.
- **The sandbox does not close the equivalent gap for *writes*, and nothing else does either.** The same subprocess hole applies in the other direction: an `Edit` deny on a path does not stop `python -c "open('src/x.py','w')..."`, and the sandbox permits writes *inside* the project directory — which is where product source lives. So for `qa-tester`, the one subagent holding `Bash`, "fix nothing" and its owned-paths rule are **prompt-level promises, not enforced boundaries**. Do not read the artifact map or `qa-tester.md` rule 9 as a control; they are a contract the subagent is asked to keep. The actual control is **reading `git diff` after a QA session** — the prompt requires the subagent to list every file it touched in a `## Files I changed` section precisely so the diff can be checked against the claim. A QA agent that quietly fixed the code will report a pass, which makes this the hardest violation in the set to notice and the one worth spending the two minutes on. The other two subagents hold no `Bash`, so their path scoping *is* enforced by the deny rules.
- **Verify the configuration in CI, don't trust that it was applied.** Everything above is a per-project manual step, and a manual step nothing checks is not a control — the same argument that replaced "remember to regenerate the SBOM" with a freshness check. Run the shared checker from the submodule path, per `docs/supply-chain.md` § "Shared tooling scripts":

  ```yaml
  - name: Subagent permission check
    run: python .standards/tools/check_agent_settings.py
  ```

  It asserts every deny rule above, `sandbox.enabled`, and that a `SubagentStop` hook for `qa-tester` runs `qa_report_check.py`; explains why each one exists when it fails; and flags an `allow` entry written as though it were a restriction. It reads the settings file only — no Claude Code invocation, no network. The hook is matched by script filename, not by the exact command, so a project may add its own flags.
- **The `SubagentStop` hook** turns three prompt-level promises into checks, using the shared `.standards/tools/qa_report_check.py` — invoked from the submodule path, not copied per project, per `docs/supply-chain.md` § "Shared tooling scripts". Exit code 2 blocks the subagent from stopping and returns the message to it; the matcher filters on `agent_type`. Same move this repo made when it replaced "remember to regenerate the SBOM" with a CI freshness check. What it asserts:

  - a QA report claiming `PASS` carries a `Command:` line recording what was actually run — `qa-tester.md` rule 3 (the template's own `<exact command>` placeholder does not count);
  - the report has a non-empty `## Files I changed` section — rule 10, which is what makes the `git diff` review above possible;
  - no file matching the `--forbid-tbd` globs contains `TBD` — `business-analyst.md` rules 1 and 2, checked against the files on disk rather than against what the report claims.

  Its limit, stated plainly: it cannot verify a recorded command was really run, and nothing at this layer can. What it removes is the silent omission — a pass with no command, or a session with no declared writes, now has to be an explicit false statement rather than a blank space. It also **fails open** on its own failure (no payload, unreadable transcript, no assistant message found), loudly on stderr, because a hook that wedges a session on its own bug gets deleted, and a deleted hook fails open permanently instead of once. `--strict` inverts that where a project would rather block.

Every mechanical claim in these notes — what a path rule is consulted for, `deny` over `allow`, what the sandbox does and does not cover, the hook's exit-code semantics — is listed in § "Mechanical claims — verification status" below with the Claude Code version it was last checked against. Most are currently marked **Not verified**. Read them as this design's assumptions, and re-check them on a major bump.

## Mechanical claims — verification status

Everything above rests on how Claude Code behaves, and most of that behaviour is **undocumented**: it is observed, not contracted, so it can change on any release without a note. `CLAUDE.md` § "Claude API — Explicit `thinking` Configuration" is built on exactly this argument — a default that silently moved between model versions — and the same discipline applies here. A claim with no version against it is a claim nobody can re-check.

This table is where verification is recorded. **Re-run the checks on every major Claude Code bump** and update the "Last verified" column; a row that has drifted is a security finding, not a docs nit.

| Claim | Where it is used | Last verified |
|---|---|---|
| Symlinked directory and symlinked file under `.claude/agents/` are both discovered; a bare `.standards/agents/` is not | § Install — the whole distribution mechanism | `2.1.239`, Linux |
| `claude plugin validate` on a bare agents directory exits 0 regardless of contents | § Verify they loaded — why `lint_agents.py` exists | `2.1.239`, Linux |
| Path scoping is consulted for `Edit(path)` / `Read(path)` rules only; a path rule written for `Write`, `NotebookEdit`, or `Glob` is accepted, never consulted, and warned about at startup | § Required project configuration — every deny rule in the block | **Not verified** — issue #9 |
| A `Read` deny also blocks `Edit`/`Write` on the same path | § Required project configuration — the `.env` denies | **Not verified** — issue #9 |
| `deny` beats `allow` unconditionally, with no allowlist exceptions | § Required project configuration | **Not verified** — issue #9 |
| An `allow` entry auto-approves and denies nothing; there is no allow-implies-default-deny | § Required project configuration — why the old `WebFetch` allow was removed | **Not verified** — issue #9 |
| The OS sandbox covers Bash **child processes**, closing the `.env` read gap | § Required project configuration — `sandbox.enabled` | **Not verified** — issue #9 |
| The sandbox **permits writes inside the project directory**, so it does not close the equivalent write gap | § Required project configuration — the write-gap note; `qa-tester.md` rule 9 | **Not verified** — issue #9 |
| `SubagentStop` exit code 2 blocks the subagent from stopping and returns stderr to it; the matcher filters on `agent_type` | § Required project configuration — the hook; `tools/qa_report_check.py` | **Not verified** — issue #9 |
| The hook payload on stdin carries `transcript_path`, `cwd`, `agent_type`, and `stop_hook_active` | `tools/qa_report_check.py` — how it finds the report and avoids a stop loop | **Not verified** — issue #9 |
| The transcript is JSONL, one entry per turn, assistant text in `message.content[].text` | `tools/qa_report_check.py` — reading the final report | **Not verified** — issue #9 |
| `AskUserQuestion` is always stripped from subagents | § Design notes — why all three batch into `## Open Questions` | **Not verified** — issue #9 |
| Subagent nesting is on by default up to 3 levels; only `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` disables it | § Design notes — why *not granting* `Agent` is the control | **Not verified** — issue #9 |
| The first ~200 lines of `MEMORY.md` are injected into the subagent's **system prompt** at startup | § `memory:` — the reason for the prohibition | **Not verified** — issue #9 |
| `model:` omitted inherits the main session's model | § Design notes — Models; why `lint_agents.py` requires the field | **Not verified** — issue #9 |

**"Not verified" means not verified, not "probably fine".** Every row so marked was written in a session where the `claude` CLI was unavailable, so none of it could be re-tested against a real installation. The claims are carried over from the source they were originally read from and are believed accurate; nothing here confirms them. Issue #9 tracks working the list with the CLI in hand and pinning each row to a version. Until then, treat the security-bearing rows — the path-rule semantics, `deny` over `allow`, and the sandbox's two halves — as the design's assumptions rather than its guarantees.

## Design notes

- **Handoff packets, not conversation.** Each subagent starts with an empty context window and sees none of your session, so every dispatch names the exact files to read and write. This is also why the coordinator subagent was removed rather than hardened: it would have been writing those packets while knowing strictly less about the project than the session dispatching it, and it could not file the issues it produced. See `docs/delivery-artifacts.md` § "Who coordinates".
- **`## Open Questions` instead of asking.** Subagents can't prompt you — `AskUserQuestion` is always stripped from them. All three batch ambiguities into a final section with a recommended default, so nothing silently stalls and nothing gets invented. This is a necessary design, not a stylistic one.
- **Nesting is on by default**, up to 3 levels; only `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` disables it. That is why *not granting* `Agent` matters: the restriction is structural, not a setting a new project has to remember. Nothing here can spawn anything.
- **Separation of authorship.** The analyst doesn't set numeric targets, the architect doesn't write test cases, and QA doesn't touch product code or rewrite the requirement it just failed. Collapsing any of those removes the review boundary that makes the artifact set worth trusting. The permission denies above enforce it for the analyst and the architect, which hold no `Bash`. For `qa-tester` they do not — see the write-gap note above — so there it stays a promise, backed by a `git diff` review rather than by the permission system.
- **Derive from the standards, don't restate them.** The architect and QA subagents read `.standards/CLAUDE.md`, `.standards/docs/security-protocols.md`, and `.standards/docs/supply-chain.md` and cite sections rather than reinventing security, privacy, and compliance targets in different words with different numbers.
- **The process map is HTML, and self-contained.** `business-analyst` writes `docs/delivery/12-process-map.html` — swimlanes by actor, every node carrying its `FR-###`/`BR-###`/`US-###`, unhappy paths drawn alongside the happy one, plus a step-index table so the map is greppable and diffable. Inline CSS and inline SVG only: no CDN script, no Mermaid library, no remote assets, so it opens correctly from disk with no network.
- **Artifacts live under `docs/delivery/`**, not `docs/` — a dozen numbered files would bury `security-protocols.md`, `supply-chain.md`, and `security-cadence.md`. The map of which subagent owns which path is in `docs/delivery-artifacts.md`, held in one place so three prompts can't drift apart on it.
- **Work items and RAID entries are GitHub Issues**, per `CLAUDE.md` § Documentation. Only the charter stays as markdown: it is a scope contract, and its "Explicitly out of scope" section is the highest-value part of the set. Two backlogs cannot both be honest.
- **Models.** The architect runs `opus` (judgment-heavy), analyst and QA run `sonnet`. Change the `model:` field to `inherit` to follow your main session (`inherit` is also the default when `model:` is omitted), or `haiku` to cut cost on the QA pass.

## `memory:` — not enabled, deliberately

`memory: project` looks like a free win (`.claude/agent-memory/<name>/`, shareable via git) and is a persistent prompt-injection vector. The first ~200 lines of `MEMORY.md` are injected into the subagent's **system prompt** at startup, the subagent can write that file itself, and `project` scope is committed to git. So any untrusted text a subagent ever writes into that file — an excerpt you pasted into its context, a hostile string in a dependency's README it read while grepping — is re-injected into a **system prompt** on every later run, and once committed, in every clone. That is `CLAUDE.md` § Prompt Injection rule 1 ("never interpolate untrusted content into a system prompt") violated persistently rather than once.

Removing the web tools from this set narrowed that channel but did not close it: a subagent that reads repo files still ingests content it did not author.

**Do not enable `memory:` on any subagent in this set.** Do not enable it on any subagent holding `WebFetch`/`WebSearch` under any circumstances. If it is ever enabled at all, treat `.claude/agent-memory/**` as reviewed content on every diff, never as trusted context. There is also an open report that `memory:` does not function when a `tools:` allowlist is present — the configuration all three use — so confirm it works before designing around it.

The system-prompt injection mechanism above is itself an unverified claim; it is listed in § "Mechanical claims — verification status". Note that the prohibition does not depend on it holding: `memory:` buys this set nothing it needs, so the cost of keeping it off is zero either way.

## Scope — what this set is and isn't worth

- `business-analyst` and `qa-tester` earn their place on any project: turning a vague idea into numbered, testable requirements, and having something adversarial that will not soften a failure or fix its own test, are real gaps in a solo workflow where the author and the reviewer are the same person. The traceability matrix — every `Must` requirement with no test case listed as a finding — is the highest-value artifact here.
- `solutions-architect` earns its place in a new project's first week and at each significant technology decision. The ADR format, especially "**Revisit if**", is worth adopting on its own; ongoing value drops once the shape of the system is settled.
- `project-coordinator` **was removed.** It was the weakest fit and the only subagent that needed permission to spawn others — a grant every consuming project would have had to scope correctly, forever, with nothing able to verify it had. Its real contribution was paperwork, not behaviour: the charter template, the handoff packet, the artifact map, the ID scheme. All of that is now in `docs/delivery-artifacts.md`, where you and all three subagents can read it without loading anything. Coordination is the main session's job, which is the only participant that has your whole conversation in context.

This is enterprise delivery ceremony applied to a one-person shop where the business user, the engineer, and the tester are the same person. Adopt the artifacts that produce a decision or catch a defect; drop the ones whose only function is to be handed to a stakeholder who does not exist.
