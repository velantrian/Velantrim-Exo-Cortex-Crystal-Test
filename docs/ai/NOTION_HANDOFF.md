# 🔄 Connectorless Notion Hand-off

This file is the GitHub-native transfer queue for material Crystal work produced by an
AI agent or contributor that cannot read or write the Notion workspace.

## Core invariant

```text
GitHub must contain the complete public technical and audit context required to
understand, review, test and continue the work without Notion access.

Notion may contain deeper rationale, alternatives, grant context and synchronized
history, but it must never be the only place where an implemented contract, known risk,
audit finding or required next action is recorded.
```

Do not duplicate every sentence across both systems. Duplicate the **decision-bearing
facts** needed to avoid information loss and preserve continuity.

## Access modes

| Mode | Meaning | Required action |
|---|---|---|
| `NOTION_AVAILABLE` | The current actor can read and update the relevant Notion record | Update GitHub and Notion in the same work cycle |
| `HANDOFF_REQUIRED` | The current actor cannot access Notion, but the change is `GITHUB_AND_NOTION` | Complete the GitHub record and add a hand-off item below |
| `SYNCED` | A connected actor copied the required rationale/history into Notion and recorded the final evidence | Link the safe Notion title/reference and close the item |
| `NOT_REQUIRED` | The work is `NONE` or `GITHUB_ONLY` | No Notion action is required |
| `BLOCKED_PRIVACY_OR_PERMISSION` | Required synchronization cannot be completed safely because of permissions, privacy or an unresolved target | Keep the PR draft and escalate explicitly |

`HANDOFF_REQUIRED` is not permission to omit documentation. It means the connectorless
actor must leave a complete, structured GitHub package for a connected actor.

## Connectorless agent procedure

When an AI agent performs a material audit, analysis or implementation without Notion
access:

1. Continue the analysis using the GitHub repository, code, tests, CI, PRs and issues.
2. Record material findings in the appropriate GitHub surfaces:
   - `docs/ai/CURRENT_STATE.md` for reality/status changes;
   - `docs/ai/COMPONENT_MAP.md` for ownership, files or tests;
   - `docs/ai/KNOWN_RISKS.md` for discovered, changed or closed risks;
   - `docs/ai/WORK_LOG.md` for the compact engineering hand-off;
   - an ADR/RFC/status/security/grant document when its contract changes.
3. Add a pending item to this file when the work class is `GITHUB_AND_NOTION`.
4. Set the PR fields to:
   - `Notion access: UNAVAILABLE`;
   - `Notion synchronization: HANDOFF_REQUIRED`;
   - `GitHub hand-off: docs/ai/NOTION_HANDOFF.md#...`.
5. Do not claim that Notion was updated.
6. Keep a `GITHUB_AND_NOTION` implementation PR draft until a connected actor completes
   the required Notion synchronization. Analysis-only work may remain recorded here
   without blocking unrelated engineering, but its hand-off must remain visible.

## Connected actor procedure

A human or AI agent with Notion access must:

1. Read the complete GitHub hand-off and verify the cited PR, SHA, tests and current
   repository state.
2. Create or update the relevant Notion page with the required rationale, alternatives,
   boundaries, evidence, limitations and next actions.
3. Add the safe Notion page title/reference to the GitHub PR or hand-off item.
4. Change the item status from `HANDOFF_REQUIRED` to `SYNCED`.
5. After merge, add the final merge SHA and CI/checkpoint evidence to Notion.
6. Never copy private Notion content, secrets, personal information or private datasets
   into this public repository.

## Required hand-off item

```markdown
## HOFF-YYYYMMDD-NN — Short title

- Status: `HANDOFF_REQUIRED` / `SYNCED` / `BLOCKED_PRIVACY_OR_PERMISSION`
- Created: YYYY-MM-DD
- GitHub PR/issue:
- Exact base/head SHA:
- Intended Notion record title:
- Notion access for originating actor: `UNAVAILABLE`

### Problem / opportunity

### Material findings

### Decision and rationale

### Alternatives rejected or deferred

### Truth / Canon / evidence / privacy / authority boundaries

### Files and public documentation updated

### Tests / CI / runtime evidence

### Known limitations and next actions

### Synchronization completion
- Connected actor:
- Safe Notion title/reference:
- Synchronization date:
- Final merge SHA / CI evidence:
```

## Pending hand-offs

No pending hand-offs at the time this protocol was created.

## Completed hand-offs

Move completed items here or mark them `SYNCED`; preserve their GitHub evidence and safe
Notion reference so later agents can reconstruct the history without private workspace
access.

## Crystal-Test explicit reentry guard — 2026-10-29

- Documentation impact: `GITHUB_AND_NOTION`.
- Notion access: `NOTION_AVAILABLE`; synchronization: `SYNCED` for the branch-local implementation and bounded local evidence.
- Safe target reference: `FORGE-CRYSTAL-01 — Forge vs Manus · PR #1/#2 audit · 2026-10-13`, separate engineering follow-up dated 2026-10-29. Historical pilot text was preserved.
- Public technical source: `docs/lab/REJECT_REENTRY.md`, `docs/status/reentry-guard-lab.json`, this branch's code/tests.
- Decision: opt-in compound rejection through existing review/Immune owners; ordinary reject remains record-level. CLI additionally requires ADMIN with `fact:*` for the workspace-wide guard.
- Limits: lexical containment, not semantic identity or erasure; no in-flight ingest fencing, automatic demotion of old Canon, tenant guarantee or production authority.
- PR #7 merged into the Crystal-Test lab main as `ff21220a708fd9225d05f870754de2509852dd5d` on 2026-10-30. Dated Notion follow-up records the updated head and test evidence. This is not the canonical Crystal repository.

## In-flight ingestion fence — 2026-10-29

- Impact `GITHUB_AND_NOTION`; user requested continuation and testing in Crystal-Test.
- `test_reentry_race_probe.py` reproduced promotion after guard commit on initial PR #7 head. A bounded SQLite promotion fence was implemented and tested, including a separate-process case and independent positive control.
- Scope is `core.ingest.ingest` transition, not the full graph pipeline, outbox, erasure or existing Canon. See `docs/lab/REJECT_REENTRY.md` and machine evidence in `docs/status/reentry-guard-lab.json`.
- Notion is available; the dated bounded-results follow-up is synced. Updated PR #7 head `ae73d582fdb828029fb34a6a37762c2bfd4470f7` was synchronized in the dated Notion follow-up. No production or upstream assertion.
## Crystal-Test lab CI proposal — 2026-10-29

- Impact: `GITHUB_AND_NOTION` (verification workflow). The canonical source remains the lab workflow and `FORGE_LAB_PROVENANCE.md`.
- Notion access: `NOTION_AVAILABLE`; synchronization: `SYNCED`. The [FORGE-CRYSTAL-01 checkpoint](https://app.notion.com/p/3f8ac84d054781449f62e208c9fef4f3) already records PR #8's rebased verified head `02cf5581b2ea7d58b26ceed67f4d554cbc91522a` and hosted run #41019730457 success (Python 3.11 and 3.12). Its earlier original-head note remains historical.
- The rebased tested SHA passed [hosted run #41019730457](https://github.com/velantrian/Velantrim-Exo-Cortex-Crystal-Test/actions/runs/41019730457) (`completed / success`). A later docs-only commit is not covered by that exact-head result until a new run passes. The three upstream workflows stay absent; inherited security tests are explicitly adapted to the separate lab contract, not skipped. No Bandit/pip-audit or production/Canon CI-equivalence claim.
- README lab notice changed in English; existing translations retain upstream content and require a follow-up lab-notice translation.
