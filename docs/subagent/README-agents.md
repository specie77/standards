# Delivery subagent set for Claude Code

Four Claude Code **subagents** that split a project into charter → functional spec → quality attributes → verification, with a shared artifact map and ID scheme so each one's output is usable by the next.

> **Naming.** In this repo an *agent* is a deployable service in its own directory with an `AGENT.md`, a `requirements.txt`, a Dockerfile, and Dependabot entries. These four are *subagents* — prompt configurations loaded by Claude Code. The two are not interchangeable; say which you mean.

## Install — symlink the submodule, don't copy

`docs/supply-chain.md` § "Shared tooling scripts" rules out copy-paste distribution: a copied file has no mechanism keeping copies in sync, a fix applied in one project has to be manually re-applied everywhere else, and nothing catches silent drift. Prompts get tweaked in place far more casually than code does, so the odds are worse here than for `check_sbom.py`.

Claude Code does not discover `.standards/agents/`. It scans `.claude/agents/` (recursively) and `~/.claude/agents/`. A symlink bridges the two — verified on Claude Code `2.1.239`, Linux:

| Layout | Discovered? |
|---|---|
| `.claude/agents/business-analyst.md` (real file — control) | Yes |
| `.claude/agents/standards -> ../../.standards/agents` (symlinked **directory**) | **Yes** |
| `.claude/agents/business-analyst.md -> ../../.standards/agents/business-analyst.md` (symlinked **file**) | **Yes** |
| `.standards/agents/business-analyst.md`, no symlink (negative control) | **No** |

Use one symlinked directory per project, so adding a fifth subagent upstream needs no per-project change:

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

Ask a session what it can actually see instead, and assert the four names appear:

```bash
claude --print "List every subagent type available via the Agent tool."
```

## Use

Automatic delegation works off the `description` field. To force a specific subagent, @-mention it or name it:

```
@"project-coordinator (agent)" kick off the project from the README and set up the docs tree
Use the business-analyst subagent to write requirements for the invoice export feature
Have the solutions-architect derive NFRs from docs/delivery/10-functional-requirements.md
Use the qa-tester subagent to run the suite and triage the failures
```

Chained, which is the normal path:

```
Use the project-coordinator to plan the next feature, then dispatch its handoff packets
```

## Required project configuration

The frontmatter alone is not a security boundary. Add this to `.claude/settings.json` before using the set unattended:

```jsonc
{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./**/.env)",
      "Edit(./.standards/**)",       // upstream standards are not project-editable
      "Edit(./.github/**)",          // CI and Dependabot config
      "Edit(./CLAUDE.md)",
      "Agent(general-purpose)",      // backstop, independent of frontmatter
      "Agent(claude)"
    ],
    "allow": [
      "WebFetch(domain:docs.python.org)"   // architect egress allowlist — extend deliberately
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
- **The `Agent(...)` denies are a genuine second layer**, evaluated by the permission system rather than by frontmatter, so they hold even if a prompt is edited. The coordinator's grant is already scoped to the three specialists; a bare `Agent` grant would let it spawn `general-purpose` or `claude`, both of which hold every tool in the session.
- **`sandbox.enabled` is what closes the secrets gap for `qa-tester`.** `Read`/`Edit` deny rules cover Claude's file tools and the file commands Claude Code recognises inside Bash (`cat`, `head`, `tail`, `sed`) — they do **not** cover a Python or Node script that opens `.env` itself. The sandbox is enforced for every Bash command *and its child processes*. Pair it with a `PreToolUse` hook allowlisting the project's test runner.
- **The `SubagentStop` hook** turns two prompt-level promises into checks: reject a QA report claiming a pass with no recorded command, and reject a requirements file containing `TBD`. Exit code 2 blocks the subagent from stopping; the matcher filters on `agent_type`. Same move this repo made when it replaced "remember to regenerate the SBOM" with a CI freshness check.

## Design notes

- **Handoff packets, not conversation.** Each subagent starts with an empty context window and sees none of your session. The coordinator's report ends in packets that name the exact files to read and write, because a vague delegation prompt is the single biggest cause of thin subagent output.
- **`## Open Questions` instead of asking.** Subagents can't prompt you — `AskUserQuestion` is always stripped from them. All four batch ambiguities into a final section with a recommended default, so nothing silently stalls and nothing gets invented. This is a necessary design, not a stylistic one.
- **Nesting is on by default**, up to 3 levels; only `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` disables it. The coordinator's `Agent` grant is live, not a maybe — which is why it is scoped to `Agent(business-analyst), Agent(solutions-architect), Agent(qa-tester)` rather than bare.
- **Separation of authorship.** The coordinator doesn't write requirements, the analyst doesn't set numbers, the architect doesn't write test cases, and QA doesn't touch product code. Collapsing any of those removes the review boundary that makes the artifact set worth trusting. The permission denies above are what enforce it; the prompts alone are promises.
- **Derive from the standards, don't restate them.** The architect and QA subagents read `.standards/CLAUDE.md`, `.standards/docs/security-protocols.md`, and `.standards/docs/supply-chain.md` and cite sections rather than reinventing security, privacy, and compliance targets in different words with different numbers.
- **The process map is HTML, and self-contained.** `business-analyst` writes `docs/delivery/12-process-map.html` — swimlanes by actor, every node carrying its `FR-###`/`BR-###`/`US-###`, unhappy paths drawn alongside the happy one, plus a step-index table so the map is greppable and diffable. Inline CSS and inline SVG only: no CDN script, no Mermaid library, no remote assets, so it opens correctly from disk with no network.
- **Artifacts live under `docs/delivery/`**, not `docs/` — thirteen numbered files would bury `security-protocols.md`, `supply-chain.md`, and `security-cadence.md`.
- **Work items and RAID entries are GitHub Issues**, per `CLAUDE.md` § Documentation. Only the charter stays as markdown: it is a scope contract, and its "Explicitly out of scope" section is the highest-value part of the set. Two backlogs cannot both be honest.
- **Models.** Coordinator and architect run `opus` (judgment-heavy), analyst and QA run `sonnet`. Change the `model:` field to `inherit` to follow your main session (`inherit` is also the default when `model:` is omitted), or `haiku` to cut cost on the QA pass.

## `memory:` — not enabled, deliberately

`memory: project` looks like a free win (`.claude/agent-memory/<name>/`, shareable via git) and is a persistent prompt-injection vector. The first ~200 lines of `MEMORY.md` are injected into the subagent's **system prompt** at startup, the subagent can write that file itself, and `project` scope is committed to git. Chain it with web access — the architect fetches a hostile page, writes a "finding" to `MEMORY.md` — and `CLAUDE.md` § Prompt Injection rule 1 ("never interpolate untrusted content into a system prompt") is violated persistently rather than once, in every clone.

Do not enable it on any subagent holding `WebFetch`/`WebSearch`. If enabled at all, restrict it to `qa-tester`, and treat `.claude/agent-memory/**` as reviewed content on every diff, never as trusted context. There is also an open report that `memory:` does not function when a `tools:` allowlist is present — the configuration all four use — so confirm it works before designing around it.

## Scope — what this set is and isn't worth

- `business-analyst` and `qa-tester` earn their place on any project: turning a vague idea into numbered, testable requirements, and having something adversarial that will not soften a failure or fix its own test, are real gaps in a solo workflow where the author and the reviewer are the same person. The traceability matrix — every `Must` requirement with no test case listed as a finding — is the highest-value artifact here.
- `solutions-architect` earns its place in a new project's first week and at each significant technology decision. The ADR format, especially "**Revisit if**", is worth adopting on its own; ongoing value drops once the shape of the system is settled.
- `project-coordinator` is the weakest fit, kept for the **handoff packet** and the charter.

This is enterprise delivery ceremony applied to a one-person shop where the business user, the engineer, and the tester are the same person. Adopt the artifacts that produce a decision or catch a defect; drop the ones whose only function is to be handed to a stakeholder who does not exist.
