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

## HOFF-20261111-01 — Crystal-Test → Titan bridge: selection attestation

- Status: `HANDOFF_REQUIRED`
- Created: 2026-11-11
- GitHub PR/issue: draft PR #15 (base); this work is on a separate branch on top of its head and is not merged.
- Exact base/head SHA: base `77f10c81dc68fb60d7facb459c0c92264debd905`; head: see this branch's Git history.
- Intended Notion record title: the existing Crystal / Titan bridge or Experiment Registry entry, as a dated follow-up. Not chosen by this actor.
- Notion access for originating actor: `UNAVAILABLE`

### Problem / opportunity

The bridge selected grounds correctly, but the record line Titan renders for the model did not carry Crystal's own status labels, so the model could not tell an admitted ground from unverified memory.

### Material findings

- The three live runs of 2026-11-10 sent grounds with `Validated` / `VERIFIED` in Crystal's receipt and without either label in the request. All three replies called the record unverified. Titan's remote boundary text tells the model to do so unless the entry text marks it `Validated` or `ImmutableCore`.
- Titan's boundary text is an instruction to the model, not a program check of two fields. A separate record key is dropped by Titan's formatter; only `source`, `confidence` and `claim` are rendered.
- `Validated` (epistemic state) and `VERIFIED` (`truth_status`) are different Crystal fields and are not interchangeable.

### Decision and rationale

Carry the selection as an attestation, not as a bare status word: both Crystal labels under their own names, the claim hash, the procedure actually run, the request scope, which filters were applied and the boundary of the result. Interpretation guidance goes through Titan's `console_instructions`, not into a memory record, so no control text is disguised as memory content and no Titan-side trust is created.

### Alternatives rejected or deferred

- Inserting the word `Validated` into the record text: rejected; it would act as an automatic transfer of trust and conflate two Crystal fields.
- A validation function inside Titan: deferred; no Titan change is made in this lab.
- Model calls with the new format: deferred pending explicit authorization.

### Truth / Canon / evidence / privacy / authority boundaries

Crystal remains the only owner of admission. The attestation describes a selection; it does not certify the generated answer and does not change any state in either project. A missing label is shown as `unknown` and never defaulted.

### Files and public documentation updated

`tests/support/crystal_titan_bridge.py`, `tests/support/titan_chat_spy.py`, `tests/test_crystal_titan_bridge_attestation.py`, `docs/ai/WORK_LOG.md`, this file.

### Tests / CI / runtime evidence

60 passed locally (15 new, 45 existing bridge tests), fake provider, Titan sandbox `6b45854`. No CI run recorded for this branch. No model was called.

### Known limitations and next actions

The effect on a model's reading is not measured. The live runner scripts are not updated. Next bounded step: six calls (earlier and new format, same three cases, same settings), then a human reading; requires explicit authorization.

### Synchronization completion
- Connected actor:
- Safe Notion title/reference:
- Synchronization date:
- Final merge SHA / CI evidence:


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
- Draft PR/head reference will be added to the dated Notion follow-up after publication. Post-merge SHA/CI evidence remains pending owner review and merge.

## In-flight ingestion fence — 2026-10-29

- Impact `GITHUB_AND_NOTION`; user requested continuation and testing in Crystal-Test.
- `test_reentry_race_probe.py` reproduced promotion after guard commit on initial PR #7 head. A bounded SQLite promotion fence was implemented and tested, including a separate-process case and independent positive control.
- Scope is `core.ingest.ingest` transition, not the full graph pipeline, outbox, erasure or existing Canon. See `docs/lab/REJECT_REENTRY.md` and machine evidence in `docs/status/reentry-guard-lab.json`.
- Notion is available; the dated bounded-results follow-up is synced. Add exact updated PR head after publication. No production or upstream assertion.
