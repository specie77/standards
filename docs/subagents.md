# Delivery subagent set for Claude Code

Three Claude Code **subagents** that split a project into functional spec → quality attributes → verification, so each one's output is usable by the next. The shared artifact map, ID scheme, and templates they work from live in `docs/delivery-artifacts.md` — a standard in its own right, readable without loading any subagent.

The charter and the coordination between the three are the **main session's** job. There is no coordinator subagent; `docs/delivery-artifacts.md` § "Who coordinates" explains why, and carries the charter template and handoff-packet format it used to hold.

> **Naming.** In this repo an *agent* is a deployable service in its own directory with an `AGENT.md`, a `requirements.txt`, a Dockerfile, and Dependabot entries. These three are *subagents* — prompt configurations loaded by Claude Code. The two are not interchangeable; say which you mean. Full definition: `docs/delivery-artifacts.md` § Terminology.

**Where the files are.** The definitions live in `agents/` at the repo root; this page lives in `docs/`. That split is deliberate: consuming projects symlink `agents/` into `.claude/agents/`, which Claude Code scans **recursively**, so anything in that directory is treated as an agent definition. A README sitting beside them would be scanned as one. Keep `agents/` to definitions only.

> **Installing into a project?** [`subagent-deployment.md`](subagent-deployment.md) is the ordered runbook — symlink, settings, Bash allowlist, CI wiring, and the one-time test that proves the report check actually blocks before you rely on it. This page is the reasoning behind each step.

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

Ask a session what it can actually see instead, and assert the three names appear.

**On the CLI**, one shot, scriptable:

```bash
claude --print "List every subagent type available via the Agent tool."
```

**Under the VS Code extension** that command does not exist: the extension bundles a private CLI copy and deliberately does not add `claude` to `PATH`, so `--print` needs the [standalone CLI install](https://code.claude.com/docs/en/setup). Either install it and run the above in the integrated terminal, or check from inside a chat session instead — ask it to list the subagent types available via the Agent tool, and confirm `business-analyst`, `solutions-architect`, and `qa-tester` all appear.

Either way the check is the same one: what a running session actually sees, not what the directory contains. `lint_agents.py` in CI covers the file contents; this covers discovery. Both are needed — a definition can be valid and still not be loaded, and the symlink that makes discovery work is itself undocumented behaviour (see the verification table below).

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
  "sandbox": { "enabled": true },          // OS-level; Bash + child processes. CLI only — see below
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
- **`sandbox.enabled` closes the secrets gap for `qa-tester` — on the surfaces that enforce it.** `Read`/`Edit` deny rules cover Claude's file tools and the file commands Claude Code recognises inside Bash (`cat`, `head`, `tail`, `sed`) — they do **not** cover a Python or Node script that opens `.env` itself. The sandbox is enforced for every Bash command *and its child processes*, which is the only layer that reaches that subprocess.

  Two limits on it, both load-bearing:

  - **It restricts Bash only.** Per the [sandboxing docs](https://code.claude.com/docs/en/sandboxing), built-in file tools, MCP servers, and hooks still run directly on the host — permission rules gate those instead. So the sandbox was never the broad boundary its name suggests; it closes one leg.
  - **It appears not to be enforced under the IDE extensions.** See § "Running under the VS Code extension" below. Do not assume this setting is doing anything until you have checked it on the surface you actually use.

  Pair it with a `PreToolUse` hook allowlisting the project's test runner — that hook runs on **every** surface (hooks are documented as firing across terminal, IDE extensions, desktop and web), which makes it the portable half of this control.
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

Every mechanical claim in these notes — what a path rule is consulted for, `deny` over `allow`, what the sandbox does and does not cover, the hook's exit-code semantics — is listed in § "Mechanical claims — verification status" below, marked **Documented** with a citation, **Observed** with a version and date, or **Undocumented**. The permission and sandbox semantics are documented; the hook and subagent internals largely are not. Read the undocumented ones as this design's assumptions, and re-check the whole table on a major bump.

## Running under the VS Code extension

The set is developed and used from the **Claude Code VS Code extension**, not the CLI, and the two surfaces are not equivalent for the controls above. What carries over and what does not:

| Control | Under the extension |
|---|---|
| `permissions.deny` rules | **Yes.** Settings are shared between extension and CLI, and a subagent *"inherits the parent conversation's permissions"* — it cannot widen them. |
| `SubagentStop` / `PreToolUse` hooks | **Yes.** Hooks are documented as firing *"across all Claude Code surfaces (terminal, IDE extensions, Desktop app, web)"*, and a `PreToolUse` hook in `settings.json` *"also runs before every tool a subagent uses"*. |
| `sandbox.enabled` | **Apparently not enforced.** Treat it as inert here until proven otherwise. |
| `claude --print` (the load check above) | **No.** The extension bundles a private CLI copy and deliberately does not add `claude` to `PATH`; that check needs the standalone CLI install. |

**The evidence on the sandbox**, recorded so it can be re-checked rather than taken on faith — as of 2026-08-24, extension `2.1.238`/`2.1.239`, macOS:

1. `/sandbox` — the documented way to configure *and observe* the sandbox — is **not available** in the extension. It supports only a subset of slash commands.
2. Every spawned native binary process carries `--output-format stream-json … --setting-sources=user,project,local` and **no `--sandbox` flag** (observed via `ps`).
3. [anthropics/claude-code#32814](https://github.com/anthropics/claude-code/issues/32814) describes exactly that mechanism — the extension spawning the binary without `--sandbox`, so the Seatbelt profile is never applied even with `sandbox.enabled: true`. Filed 2026-03-10 against extension `2.1.71`, closed as `duplicate`; the behaviour above suggests it was not fixed in the interim.

None of that is proof of non-enforcement — a missing flag does not strictly rule out the binary self-applying the profile from settings. It is enough to stop relying on it. **Keep the setting** (it is correct on the CLI, and costs nothing where it is inert), but do not count it as the control.

### What to use instead, tiered by whether you are watching

- **Attended — you are reading the session as it runs.** Permission denies + a `PreToolUse` Bash allowlist + the `SubagentStop` report check + a `git diff` review afterwards. All four work on every surface today. This is the normal path.
- **Unattended — the case this whole configuration section is gated on.** Run the session inside a **dev container**: *"a dev container runs Claude Code inside a Docker container that VS Code or a compatible editor manages, with your project mounted in."* That is the surface-independent answer, and it closes the secrets gap more completely than the sandbox ever did — the real `.env` need not exist inside the container at all. See [Sandbox environments](https://code.claude.com/docs/en/sandbox-environments).

Two things that follow, and are easy to get wrong:

- **You cannot containerise `qa-tester` alone.** All three subagents run inside the same Claude Code session, so the boundary is drawn around the whole session or not at all.
- **Running only the *test suite* in a container is not a substitute.** It protects the tests, not the agent: Claude's own Bash still runs on the host, so `python -c "print(open('.env').read())"` is still reachable. It is a good complement, not a replacement.

**The write gap survives every option here.** The isolation docs say it plainly — *"any approach that mounts your project directory writable can still modify that code."* A dev container does not fix it and neither does a VM. `git diff` after a QA session remains the control, on every surface.

## Mechanical claims — verification status

Everything above rests on how Claude Code behaves. Some of that is documented and citable; a significant part of it — most of the hook and subagent internals — is not, and an undocumented behaviour can change on any release without a note. `CLAUDE.md` § "Claude API — Explicit `thinking` Configuration" is built on exactly this argument, a default that silently moved between model versions. A claim with nothing against it is a claim nobody can re-check.

This table is where that is recorded, and a row that has drifted is a security finding, not a docs nit.

Three statuses, and they are not interchangeable. **Documented** — the official docs state it, cited. **Observed** — checked against a real installation on the date and version shown, not documented. **Undocumented** — neither; carried over from wherever it was first read, believed accurate, confirmed by nothing.

| Claim | Where it is used | Status |
|---|---|---|
| Path scoping is consulted for `Edit(path)` / `Read(path)` rules only; a path rule written for `Write`, `NotebookEdit`, or `Glob` is accepted, never consulted, and warned about at startup | § Required project configuration — every deny rule in the block | **Documented** — [permissions](https://code.claude.com/docs/en/permissions) |
| A `Read` deny also blocks `Edit`/`Write` on the same path | § Required project configuration — the `.env` denies | **Documented** — [permissions](https://code.claude.com/docs/en/permissions) (edits `2.1.208`+, writes `2.1.228`+) |
| `deny` beats `allow` unconditionally, with no allowlist exceptions | § Required project configuration | **Documented** — [permissions](https://code.claude.com/docs/en/permissions); order is deny → ask → allow |
| An `allow` entry auto-approves and denies nothing; there is no allow-implies-default-deny | § Required project configuration — why the old `WebFetch` allow was removed | **Documented** — [permissions](https://code.claude.com/docs/en/permissions) |
| Read/Edit path rules use **gitignore** pattern syntax; a bare filename matches at any depth | § Required project configuration — what the `.env` denies actually cover | **Documented** — [permissions](https://code.claude.com/docs/en/permissions) |
| A subagent inherits the parent conversation's permissions and cannot widen them; `tools:` frontmatter is a separate mechanism | § Required project configuration — why checking settings is worth more than reading frontmatter | **Documented** — [subagents](https://code.claude.com/docs/en/sub-agents) |
| Hooks fire on every surface — terminal, IDE extensions, desktop, web — and a `PreToolUse` hook in `settings.json` runs before every tool a subagent uses | § Running under the VS Code extension; the `SubagentStop` hook | **Documented** — [hooks](https://code.claude.com/docs/en/hooks) |
| The OS sandbox covers Bash **child processes**, closing the `.env` read gap | § Required project configuration — `sandbox.enabled` | **Documented** — [sandboxing](https://code.claude.com/docs/en/sandboxing) — but see the extension row below |
| The sandbox restricts **Bash only**; built-in file tools, MCP servers, and hooks run unconstrained on the host | § Required project configuration — the limits on `sandbox.enabled` | **Documented** — [sandbox environments](https://code.claude.com/docs/en/sandbox-environments) |
| The sandbox **permits writes inside the working directory**, so it does not close the equivalent write gap | § Required project configuration — the write-gap note; `qa-tester.md` rule 9 | **Documented** — [sandboxing](https://code.claude.com/docs/en/sandboxing); the isolation docs extend it to containers and VMs |
| `sandbox.enabled` appears **not enforced under the VS Code extension** | § Running under the VS Code extension | **Observed** `2026-08-24`, extension `2.1.238`/`2.1.239`, macOS — no `--sandbox` on the spawned binary, `/sandbox` unavailable, [#32814](https://github.com/anthropics/claude-code/issues/32814) |
| `model:` omitted inherits the main session's model | § Design notes — Models; why `lint_agents.py` requires the field | **Documented** — [subagents](https://code.claude.com/docs/en/sub-agents) |
| `SubagentStop` matcher filters on `agent_type` | § Required project configuration — the hook | **Documented** — [hooks](https://code.claude.com/docs/en/hooks) |
| Symlinked directory and symlinked file under `.claude/agents/` are both discovered; a bare `.standards/agents/` is not | § Install — the whole distribution mechanism | **Observed** `2.1.239`, Linux — recursive scan is documented, symlink following is not |
| `claude plugin validate` on a bare agents directory exits 0 regardless of contents | § Verify they loaded — why `lint_agents.py` exists | **Observed** `2.1.239`, Linux |
| `SubagentStop` **command** hook exiting 2 blocks the stop and returns stderr to the subagent | `tools/qa_report_check.py` | **Undocumented** — specified for *prompt* hooks only; command-hook semantics are not. Settle it with `subagent-deployment.md` § "Verify the referee" — issue #9 |
| The hook payload carries `stop_hook_active` | `tools/qa_report_check.py` — avoiding a stop loop | **Undocumented** — `transcript_path`, `cwd`, `agent_type` are documented; this one is not — issue #9 |
| The transcript is JSONL, one entry per turn, assistant text in `message.content[].text` | `tools/qa_report_check.py` — reading the final report | **Undocumented** — no official schema exists; community tooling agrees on this shape — issue #9 |
| `AskUserQuestion` is always stripped from subagents | § Design notes — why all three batch into `## Open Questions` | **Undocumented** — issue #9 |
| Subagent nesting is on by default up to 3 levels; only `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` disables it | § Design notes — why *not granting* `Agent` is the control | **Undocumented** — issue #9 |
| The first ~200 lines of `MEMORY.md` are injected into the subagent's **system prompt** at startup | § `memory:` — the reason for the prohibition | **Undocumented** — the memory feature is documented, the injection mechanism is not — issue #9 |

**"Undocumented" means confirmed by nothing.** Those rows are believed accurate and are carried from wherever they were first read; no installation has been made to demonstrate any of them. Three of them sit under `tools/qa_report_check.py`, which is why that script parses tolerantly and routes every unmet assumption to its fail-open path rather than blocking. Issue #9 tracks working the remainder against a real CLI install.

**The two `Observed` rows and the `Documented` ones age differently.** A documented behaviour can still change — that is the argument `CLAUDE.md` § "Claude API — Explicit `thinking` Configuration" makes about undocumented defaults drifting on a version bump, and it applies to documented ones too. Re-check the whole table on a major Claude Code bump; the extension row especially, since it describes a bug that may be fixed without announcement.

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
