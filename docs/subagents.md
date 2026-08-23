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
                    "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/qa-report-check.sh" }] }
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
- **Verify the configuration in CI, don't trust that it was applied.** Everything above is a per-project manual step, and a manual step nothing checks is not a control — the same argument that replaced "remember to regenerate the SBOM" with a freshness check. Run the shared checker from the submodule path, per `docs/supply-chain.md` § "Shared tooling scripts":

  ```yaml
  - name: Subagent permission check
    run: python .standards/tools/check_agent_settings.py
  ```

  It asserts every deny rule above plus `sandbox.enabled`, explains why each one exists when it fails, and flags an `allow` entry written as though it were a restriction. It reads the settings file only — no Claude Code invocation, no network.
- **The `SubagentStop` hook** turns two prompt-level promises into checks: reject a QA report claiming a pass with no recorded command, and reject a requirements file containing `TBD`. Exit code 2 blocks the subagent from stopping; the matcher filters on `agent_type`. Same move this repo made when it replaced "remember to regenerate the SBOM" with a CI freshness check.

## Design notes

- **Handoff packets, not conversation.** Each subagent starts with an empty context window and sees none of your session, so every dispatch names the exact files to read and write. This is also why the coordinator subagent was removed rather than hardened: it would have been writing those packets while knowing strictly less about the project than the session dispatching it, and it could not file the issues it produced. See `docs/delivery-artifacts.md` § "Who coordinates".
- **`## Open Questions` instead of asking.** Subagents can't prompt you — `AskUserQuestion` is always stripped from them. All three batch ambiguities into a final section with a recommended default, so nothing silently stalls and nothing gets invented. This is a necessary design, not a stylistic one.
- **Nesting is on by default**, up to 3 levels; only `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` disables it. That is why *not granting* `Agent` matters: the restriction is structural, not a setting a new project has to remember. Nothing here can spawn anything.
- **Separation of authorship.** The analyst doesn't set numeric targets, the architect doesn't write test cases, and QA doesn't touch product code or rewrite the requirement it just failed. Collapsing any of those removes the review boundary that makes the artifact set worth trusting. The permission denies above are what enforce it; the prompts alone are promises.
- **Derive from the standards, don't restate them.** The architect and QA subagents read `.standards/CLAUDE.md`, `.standards/docs/security-protocols.md`, and `.standards/docs/supply-chain.md` and cite sections rather than reinventing security, privacy, and compliance targets in different words with different numbers.
- **The process map is HTML, and self-contained.** `business-analyst` writes `docs/delivery/12-process-map.html` — swimlanes by actor, every node carrying its `FR-###`/`BR-###`/`US-###`, unhappy paths drawn alongside the happy one, plus a step-index table so the map is greppable and diffable. Inline CSS and inline SVG only: no CDN script, no Mermaid library, no remote assets, so it opens correctly from disk with no network.
- **Artifacts live under `docs/delivery/`**, not `docs/` — a dozen numbered files would bury `security-protocols.md`, `supply-chain.md`, and `security-cadence.md`. The map of which subagent owns which path is in `docs/delivery-artifacts.md`, held in one place so three prompts can't drift apart on it.
- **Work items and RAID entries are GitHub Issues**, per `CLAUDE.md` § Documentation. Only the charter stays as markdown: it is a scope contract, and its "Explicitly out of scope" section is the highest-value part of the set. Two backlogs cannot both be honest.
- **Models.** The architect runs `opus` (judgment-heavy), analyst and QA run `sonnet`. Change the `model:` field to `inherit` to follow your main session (`inherit` is also the default when `model:` is omitted), or `haiku` to cut cost on the QA pass.

## `memory:` — not enabled, deliberately

`memory: project` looks like a free win (`.claude/agent-memory/<name>/`, shareable via git) and is a persistent prompt-injection vector. The first ~200 lines of `MEMORY.md` are injected into the subagent's **system prompt** at startup, the subagent can write that file itself, and `project` scope is committed to git. So any untrusted text a subagent ever writes into that file — an excerpt you pasted into its context, a hostile string in a dependency's README it read while grepping — is re-injected into a **system prompt** on every later run, and once committed, in every clone. That is `CLAUDE.md` § Prompt Injection rule 1 ("never interpolate untrusted content into a system prompt") violated persistently rather than once.

Removing the web tools from this set narrowed that channel but did not close it: a subagent that reads repo files still ingests content it did not author.

**Do not enable `memory:` on any subagent in this set.** Do not enable it on any subagent holding `WebFetch`/`WebSearch` under any circumstances. If it is ever enabled at all, treat `.claude/agent-memory/**` as reviewed content on every diff, never as trusted context. There is also an open report that `memory:` does not function when a `tools:` allowlist is present — the configuration all three use — so confirm it works before designing around it.

## Scope — what this set is and isn't worth

- `business-analyst` and `qa-tester` earn their place on any project: turning a vague idea into numbered, testable requirements, and having something adversarial that will not soften a failure or fix its own test, are real gaps in a solo workflow where the author and the reviewer are the same person. The traceability matrix — every `Must` requirement with no test case listed as a finding — is the highest-value artifact here.
- `solutions-architect` earns its place in a new project's first week and at each significant technology decision. The ADR format, especially "**Revisit if**", is worth adopting on its own; ongoing value drops once the shape of the system is settled.
- `project-coordinator` **was removed.** It was the weakest fit and the only subagent that needed permission to spawn others — a grant every consuming project would have had to scope correctly, forever, with nothing able to verify it had. Its real contribution was paperwork, not behaviour: the charter template, the handoff packet, the artifact map, the ID scheme. All of that is now in `docs/delivery-artifacts.md`, where you and all three subagents can read it without loading anything. Coordination is the main session's job, which is the only participant that has your whole conversation in context.

This is enterprise delivery ceremony applied to a one-person shop where the business user, the engineer, and the tester are the same person. Adopt the artifacts that produce a decision or catch a defect; drop the ones whose only function is to be handed to a stakeholder who does not exist.
