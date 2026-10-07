# Deploying the subagent set into a project

A runbook for landing this repo as `.standards` in a project and turning the three
subagents on. `docs/subagents.md` explains *why* each piece exists; this is the ordered
list of what to do, plus the one-time test that proves the report check actually works
before you rely on it.

Budget about 30 minutes for steps 1–7, and 15 minutes for step 8 the first time. Step 8
only needs doing **once per machine**, not once per project — it is verifying Claude
Code's behaviour, not the project's.

> **First decide whether to install it here at all.** `docs/subagents.md` § "Scope" is
> honest about which of the three earn their place. `business-analyst` and `qa-tester`
> pay for themselves on most projects; `solutions-architect` is worth most in a new
> project's first week. Installing all three everywhere by reflex is how a set like this
> becomes ceremony.

---

## 1. Vendor the submodule

Skip if `.standards` is already there (most projects have it for `CLAUDE.md`):

```bash
git -C /path/to/project submodule add https://github.com/specie77/standards.git .standards
git -C /path/to/project submodule update --init --recursive
```

## 2. Symlink the definitions

Claude Code does not look in `.standards/agents/`. It scans `.claude/agents/`
recursively, and follows symlinks:

```bash
mkdir -p .claude/agents
ln -s ../../.standards/agents .claude/agents/standards
git add .claude/agents/standards
```

One symlinked **directory**, not per-file symlinks — a fourth subagent added upstream
then needs no per-project change. Do not copy the files; `docs/supply-chain.md`
§ "Shared tooling scripts" is the argument.

## 3. Add the permission rules

Copy the block from `docs/subagents.md` § "Required project configuration" into the
project's `.claude/settings.json`. Every deny in it has a stated reason there; the one
that matters most is `Edit(./.claude/**)`, without which the subagents can edit the
rules constraining them.

**Check it against your user-level settings before assuming it applies.** Rules merge
across user and project scope, and a broad user-level deny wins over anything narrower
here — `deny` beats `allow` unconditionally, in both directions and at every scope.

## 4. Add a Bash allowlist

`sandbox.enabled` is in the settings block, but on the VS Code extension it appears to
do nothing (`docs/subagents.md` § "Running under the VS Code extension"). A `PreToolUse`
hook works on every surface, so on an IDE-extension install this is the portable half of
the control, not an optional extra:

```jsonc
"PreToolUse": [
  { "matcher": "Bash",
    "hooks": [{ "type": "command",
                "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/bash-allowlist.sh" }] }
]
```

Write that script to permit exactly your test runner, linters, and the mandated scanners
(`pytest`, `bandit`, `gitleaks`, `pip-audit`) and refuse everything else. It is
project-specific — which runner, which paths — which is why this repo ships no shared
version of it.

## 5. Name the QA fixture outside the `.env` family

If the QA subagent needs configuration values to run a suite, give it a file of
**non-secret** values named so no `.env` deny matches it — `tests/fixtures/qa.env`, not
`.env.test`. A typical deny list covers `.env`, `.env.*`, or both, and a denied fixture
fails at read time with a confusing permission error rather than an obvious one.

The point is not to smuggle a readable file past the rules. It is that a file of fake
values has nothing to leak, which is a better control than any of the machinery above.

## 6. Wire the CI checks

Per `docs/supply-chain.md` § "CI integration checklist":

```yaml
- name: Subagent permission check
  run: python .standards/tools/check_agent_settings.py
```

That asserts the deny rules, `sandbox.enabled`, and the `SubagentStop` hook are all
present. It reads the settings file only. Note what it *cannot* do: confirm the sandbox
is enforced — it prints a reminder of that on every green run.

## 7. Restart, then confirm they loaded

Restart the session if `.claude/agents/` did not exist when it started. Then ask a
session what it can actually see and confirm all three names come back:

```
List every subagent type available via the Agent tool.
```

`business-analyst`, `solutions-architect`, and `qa-tester` should all appear. On the CLI
you can script it with `claude --print "…"`; the extension has no equivalent, so ask in
the chat panel.

A definition can be valid and still not be loaded — `lint_agents.py` in CI checks the
file contents, this checks discovery, and the symlink traversal it depends on is
undocumented behaviour. Both are needed.

---

## 8. Verify the referee

`tools/qa_report_check.py` runs when the QA subagent finishes and refuses to let it stop
if the report claims a pass with no command recorded, or omits the list of files it
changed. It is the only automated check standing between you and a tester that quietly
edited your code and reported success.

It rests on three things nobody has confirmed, all listed as **Undocumented** in
`docs/subagents.md` § "Mechanical claims": that exiting 2 actually blocks the stop, that
the message comes back to the subagent, and that the transcript can be found and read in
the shape the parser expects. **If any is wrong, the check does not complain — it waves
everything through**, because it is deliberately built to fail open rather than wedge a
session. A broken referee and a working one look identical from the outside.

So test it once, deliberately.

### 8a. Offline smoke test — 30 seconds, no session needed

This proves the script runs in this project at all: right Python, right path, right
flags. Save a deliberately bad report:

```markdown
## Verdict
PASS — everything looks good.

## Defects raised
- None.
```

It claims a pass, records no command, and has no `## Files I changed`. Both failures the
check exists to catch, in four lines. Then:

```bash
python3 .standards/tools/qa_report_check.py --check qa-report \
  --report-file /tmp/bad-report.md ; echo "exit=$?"
```

**Expect `exit=2`**, plus two complaints on stderr naming the missing command and the
missing section. Now add a `## Files I changed` section and a real `Command:` line and
re-run: **expect `exit=0`**.

If this fails, stop here — nothing further will work, and it is a path or Python problem,
not a Claude Code one.

### 8b. Live probe — the actual test

The smoke test proved the script works. It did **not** prove Claude Code listens to it.
For that, swap in a hook that always refuses, so there is no ambiguity about whether a
pass was earned or merely unnoticed.

Temporarily change the `qa-tester` matcher in `.claude/settings.json`:

```jsonc
{ "matcher": "qa-tester",
  "hooks": [{ "type": "command",
              "command": "python3 ${CLAUDE_PROJECT_DIR}/.standards/tools/probe_subagent_stop.py --block 1" }] }
```

`tools/probe_subagent_stop.py` is a diagnostic. It refuses the **first** stop, records
what Claude Code sent it, and then allows every stop after that — so the worst case is
one extra turn, never a session that cannot finish. It records the *shape* of the
transcript and never its text, because a transcript can contain a secret and a log file
in `/tmp` is a second place to leak from.

Reset the log, restart the session so the settings reload, and dispatch something
trivial:

```bash
python3 .standards/tools/probe_subagent_stop.py --reset
```

```
Use the qa-tester subagent to summarise the current state of the test suite.
Do not run anything — just produce your final report.
```

Then read the log:

```bash
cat "${TMPDIR:-/tmp}/subagent-stop-probe.log"
```

### 8c. What the result tells you

| Observation | What it proves | If it's absent |
|---|---|---|
| The subagent **kept going** after appearing to finish, and the log has an `invocation: 2` record | Exit 2 blocks the stop. The referee has teeth. | The hook ran but the exit code is ignored — `qa_report_check.py` is decorative. Fall back to `git diff` review, and say so in the docs. |
| The subagent's second report contains `SUBAGENT-STOP-PROBE acknowledged` | stderr is returned to the subagent, so the referee's complaints are *actionable* — it can fix the report and retry. | Blocking works but the reason doesn't reach it, so it will retry blindly. Still useful as a stop, less useful as a correction. |
| The `invocation: 2` record shows `stop_hook_active: true` | The loop guard field exists, so a permanently-failing report can't spin forever. | The guard in `qa_report_check.py` is inert. Keep every blocking check strictly finite. |
| `transcript.assistant_text_found_at_message_content_text: true` | The parser can find the report where it looks for it. | The transcript shape differs — the log's `entry_keys`, `message_keys`, and `content_block_types` tell you the real one, and the parser needs adjusting to match. |
| No log file at all | — | The hook never ran. Check the matcher name, the path, and that the session was restarted after editing settings. |

### 8d. Clean up

Restore the real matcher (`qa_report_check.py`), restart, and optionally do one
end-to-end run: ask the QA subagent for a report and confirm a genuinely deficient one
gets bounced. Then:

```bash
python3 .standards/tools/probe_subagent_stop.py --reset
```

**Record what you found.** These answers are machine-wide, not project-specific, and
three rows in `docs/subagents.md` § "Mechanical claims" are waiting on exactly this —
see issue #9. A result of "exit 2 does nothing" is more valuable than a green run,
because it means a documented control has to be rewritten.

---

## 9. First real run

Dispatch with a handoff packet — goal, files to read, files to write, constraints,
definition of done, out of scope. The six-part format is in `docs/delivery-artifacts.md`
§ "The handoff packet". A vague delegation is the single biggest cause of thin output,
because the subagent starts with an empty context window and sees none of your session.

Then, **every time the QA subagent runs**:

```bash
git -C /path/to/project diff --stat
```

Compare it against the `## Files I changed` section of the report. That comparison is
the control for the one thing nothing else catches — a tester that edited product source
to make its own test pass. It takes two minutes and no isolation strategy replaces it:
per the sandboxing docs, *any* approach that mounts your project writable, containers and
VMs included, still permits that write.

## Uninstalling

```bash
rm .claude/agents/standards
```

Then remove the `SubagentStop` hooks and the subagent-specific denies from
`.claude/settings.json`. The `.standards` submodule stays — the rest of it is unrelated.

"These produced nothing useful" is a legitimate outcome, and worth recording as one
rather than leaving a half-used set installed.
