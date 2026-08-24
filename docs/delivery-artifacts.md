# Delivery Artifacts Standard

The shared vocabulary for planning and specification work: where delivery artifacts
live, who owns each one, how they are identified, and the templates they follow.

This is the **single source of truth** for the artifact map and the ID scheme. The
subagent prompts in `agents/` point here rather than restating it — three
copies of an ownership table drift silently, which is the same argument
`docs/supply-chain.md` § "Shared tooling scripts" makes about copied scripts.

Read this alongside `CLAUDE.md` § Documentation, which decides what belongs in a
markdown file versus a GitHub issue.

---

## Terminology — two different things called "agent"

| Term | Means | Has |
|---|---|---|
| **agent** | A deployable service in its own directory | `AGENT.md`, `requirements.txt`, usually a Dockerfile, Dependabot entries, a § 8 security checklist |
| **subagent** | A Claude Code prompt configuration | A markdown file with frontmatter; no deployable footprint |

The two are not interchangeable. Any document that says "agent" without saying which
kind is ambiguous exactly where it must not be — the checklists that apply to one do
not apply to the other. Say which you mean, every time.

---

## Where the artifacts live

Delivery artifacts live under **`docs/delivery/`**, never directly in `docs/`.

`docs/` already holds `security-protocols.md`, `supply-chain.md`, and
`security-cadence.md`. A dozen numbered delivery files dropped beside them would bury
the standards they sit next to. The `docs/delivery/` prefix keeps the two sets
separable at a glance and in a diff.

### Artifact map

| Path | Owner | Format |
|---|---|---|
| `docs/delivery/00-charter.md` | main session | markdown |
| `docs/delivery/10-functional-requirements.md` | business-analyst | markdown |
| `docs/delivery/11-user-stories.md` | business-analyst | markdown |
| `docs/delivery/12-process-map.html` | business-analyst | self-contained HTML |
| `docs/delivery/30-uat-scenarios.md` | business-analyst | markdown |
| `docs/delivery/20-nonfunctional-requirements.md` | solutions-architect | markdown |
| `docs/delivery/21-architecture.md` | solutions-architect | markdown |
| `docs/delivery/adr/ADR-NNNN-<slug>.md` | solutions-architect | markdown |
| `docs/delivery/40-test-plan.md` | qa-tester | markdown |
| `docs/delivery/41-test-cases.md` | qa-tester | markdown |
| `docs/delivery/42-defects.md` | qa-tester | markdown |
| `docs/delivery/50-traceability.md` | qa-tester | markdown |

**Ownership is a review boundary, not a formality.** The analyst doesn't set numeric
targets, the architect doesn't write test cases, and QA doesn't touch product code or
rewrite the requirements it is testing against. Collapsing any of those removes the
independence that makes the artifact set worth trusting — a tester that can edit the
requirement it just failed has told you nothing. No subagent writes outside the paths
listed against its name.

Note the limit of that guarantee: for a subagent holding `Bash`, path ownership is a
prompt-level promise, not an enforced boundary. See `docs/subagents.md`
§ "Required project configuration".

### ID scheme

| ID | Means |
|---|---|
| `FR-001` | Functional requirement |
| `BR-001-a` | Business rule, nested inside its FR — the policy values a decision branches on |
| `NFR-001` | Non-functional requirement / quality attribute target |
| `US-001` | User story |
| `UAT-001` | User acceptance scenario |
| `TC-001` | Test case |
| `DEF-001` | Defect |
| `ADR-0001` | Architecture decision record |
| `RISK-001` | Risk (also `ISSUE-001`, `ASSUMPTION-001`) |
| `WI-001` | Work item |

**IDs are permanent.** Never renumber. New items continue the sequence; changed items
get an amended body and a changelog line; retired items are marked
`[SUPERSEDED by <ID>]` and left in place. A renumbered ID silently invalidates every
cross-reference pointing at it — including the traceability matrix, which is the one
artifact whose whole value is that its references resolve.

---

## Where work is tracked

`CLAUDE.md` § Documentation mandates GitHub Issues for feature requests and future
enhancements. Work items and RAID entries therefore live as **issues**, not as
markdown trackers.

Two backlogs cannot both be honest, and the markdown one has no notifications, no
cross-repo view, and no link to a PR.

- **Work item** → one issue, label `wbs`, title prefixed `WI-###:`. Body carries the
  handoff packet.
- **Risk / issue / assumption** → one issue, label `raid`, title prefixed `RISK-###:`
  / `ISSUE-###:` / `ASSUMPTION-###:`.
- **Decision** → an ADR authored by the solutions-architect. Link the issue to it
  rather than restating the rationale.
- **Status** is the issue state plus its labels. Do not maintain a separate status
  document.

The **charter** is the one artifact that stays in markdown: it is a scope contract,
and § 4 "Explicitly out of scope" is the highest-value section in the set.

**Filing these issues:** per `CLAUDE.md` § GitHub CLI, never pass a multiline body
inline to `gh`. Write the body to a temp file with the `Write` tool and use
`--body-file`:

```
# 1. Write tool → /private/tmp/gh_body.md
# 2. Bash:
gh issue create --title "WI-001: ..." --label wbs --body-file /private/tmp/gh_body.md
rm /private/tmp/gh_body.md
```

Multiline content in the command string breaks the Bash allowlist match and triggers
a permission prompt on every issue. Subagents do not hold `Bash` for this purpose —
they emit the issue body as text in their final report, and the main session files it.

---

## Who coordinates

**The main session.** There is deliberately no coordinator subagent.

Every subagent starts with an empty context window and sees none of your
conversation. A coordinator subagent would therefore be planning the work, and
writing the briefings the specialists depend on, while knowing strictly *less* about
the project than the session that dispatched it. It also could not file the issues it
produced — it would hand back text for the main session to file, which the main
session can compose directly.

The cost was concrete: a coordinator is the only subagent that needs permission to
spawn other subagents, and that grant has to be scoped by a permission rule in every
consuming project, forever, with nothing able to verify it was applied. Removing it
means **no subagent in this set can spawn another** — the nesting surface is gone by
construction rather than by configuration.

What the coordinator was genuinely good at was paperwork, and paperwork is what this
page is. The templates below are the part worth keeping.

---

## Templates

### `docs/delivery/00-charter.md`

```markdown
# Project Charter — <name>
**Status:** Draft | Baselined  **Last updated:** <date>

## 1. Problem statement
<2–4 sentences. The problem, not the solution.>

## 2. Objectives and success measures
| ID | Objective | How success is measured |
|---|---|---|

## 3. In scope
## 4. Explicitly out of scope
<The most valuable section in the document. Be specific.>

## 5. Stakeholders and decision rights
| Role | Who | Decides on |
|---|---|---|

## 6. Constraints
<Budget, deadline, mandated technology, compliance regime, team size.>

## 7. Assumptions
| ID | Assumption | Impact if false |
|---|---|---|

## 8. Milestones
| Milestone | Definition of done | Target |
|---|---|---|
```

### Work item issue

```markdown
Title: WI-001: Draft functional requirements for <feature>
Labels: wbs
---
**Owner subagent:** business-analyst
**Depends on:** — (or WI-###)

## Goal
<one sentence>

## Read
## Write
## Constraints
## Definition of done
FR-### written, each with acceptance criteria, no TBDs.
<plus the standing items below where they apply>

## Out of scope for this subagent
```

### RAID issue

```markdown
Title: RISK-001: <risk in one line>
Labels: raid
---
**Type:** Risk | Issue | Assumption
**Likelihood / Impact:** <for risks>   **Validated by:** <for assumptions>
**Response / Resolution:**
**Relates to:** WI-###, ADR-####, FR-###
```

---

## The handoff packet

The single most useful thing to get right when dispatching a subagent. A subagent
starts with a blank context window and sees none of your session, so a vague
delegation prompt is the biggest cause of thin output — the model fills the gap with
plausible invention rather than asking, because it cannot ask.

Every dispatch names all six:

1. **Goal** — one sentence.
2. **Read** — the exact files, in order.
3. **Write** — the exact files it may create or modify.
4. **Constraints** — including which `.standards/` sections apply, cited by section.
5. **Definition of done** — objectively checkable by someone else.
6. **Out of scope** — what this subagent must *not* do, especially where another
   subagent owns it.

Use the same six headings in a work item issue body, so the issue *is* the packet.

---

## Standing definition-of-done items

Add these to any work item that creates or modifies an **agent directory** — the
deployable kind, a new `foo-trader/` with a `requirements.txt` or Dockerfile. They are
mandatory and no specialist subagent's prompt knows them:

- `AGENT.md` present and complete per `docs/security-protocols.md` § 1 — purpose,
  inputs table with trust levels, outputs table, trust-boundary summary, error
  behaviour.
- The § 8 security checklist in `docs/security-protocols.md` worked through for the
  new directory.
- `.github/dependabot.yml` gains a `pip` entry for the directory, plus a `docker`
  entry if it contains a Dockerfile (`CLAUDE.md` § New Agent Checklist).
- CI path filters updated so the new directory's tests and image build are gated on
  its own paths *and* on any shared path its Dockerfile `COPY`s from
  (`CLAUDE.md` § CI Minute Budget, the shared-dependency gotcha).

**Cite the section; do not paste its contents into the work item.** A pasted copy is a
second version that drifts.

---

## Sequencing

Charter → functional requirements → non-functional requirements (these need the
functional set to size against) → architecture and ADRs → implementation → test plan
and cases → UAT.

Requirements work for independent features can run in parallel. Anything downstream of
an unresolved ADR cannot.

---

## Derive from the standards, don't restate them

Where a constraint already exists as a section in `.standards/`, cite the section
rather than paraphrasing it into a second, drifting copy. This applies to work item
definitions of done, NFR drivers, and test plan exit criteria alike.

The security, privacy, and compliance posture in particular is largely pre-decided:
`docs/security-protocols.md` § 12 (host and network hardening), § 13 (Cloudflare
Tunnel exposure), § 14 (browser-facing auth), § 5.1 (secret rotation cadence), and
`docs/supply-chain.md` (dependency pinning, SBOM freshness, the mandated `pip-audit` /
`bandit` / `gitleaks` CI steps). An artifact whose driver is one of these must point
at it. A second security vocabulary with different numbers is worse than none.
