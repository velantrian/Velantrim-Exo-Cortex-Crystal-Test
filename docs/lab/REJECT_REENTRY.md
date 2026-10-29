# Crystal-Test: explicit rejection with lexical reentry blocking

Status: experimental opt-in feature in `Velantrim-Exo-Cortex-Crystal-Test`; pending review and merge. This document does not describe an upstream Crystal main capability. It does not reopen the completed bounded Crystal V1 milestone.

## User operation

Ordinary rejection continues to reject one pending record. It does not assert that every future statement with the same wording is false. A curator can now explicitly request both rejection and the existing Immune Guard pattern in one atomic operation:

```bash
velantrim review-queue
VELANTRIM_CURATOR_ACTOR=local-owner VELANTRIM_CURATOR_ROLES=ADMIN VELANTRIM_CURATOR_SCOPES='fact:*' velantrim review-reject PENDING_FACT_ID --block-reentry --reason 'Explicit owner decision to block this wording'
```

Replace `PENDING_FACT_ID` with an existing Observed record. Principal configuration is the existing single-principal local deployment configuration, not a new authentication system. `--actor`, when supplied, remains an assertion matching that principal. Ordinary record rejection keeps its existing role/scope requirements. The workspace-wide guard additionally requires ADMIN and the explicit `fact:*` scope. Scoped administrators/reviewers cannot use a single-fact permission to install a global pattern.

The result includes `reentry_pattern_id` on success. The command returns exit 3 for authorization refusal, exit 2 for invalid principal configuration and exit 1 when the explicit compound decision could not reject the candidate. Old commands keep their existing exit-code behavior.

## Implementation and transaction

`core.cli` → `curator_runtime.reject_as_principal` → `review.reject` → `stage_review_decision` is the ordinary authority path. The opt-in flag does not add a second Canon writer or a model-selected trust state.

The review journal reads the candidate under `BEGIN IMMEDIATE`, checks restriction, revision and ESM state, derives the pattern from the exact stored claim, and uses the existing Immune writer on that same connection. The claim collapse, threat pattern, `immune_threat_recorded` audit event, `review_reject` audit event and decision record commit together. Failure at a tested write/audit boundary or process termination before commit rolls them back together. L0 is invalidated through the existing journal path. The decision payload carries only the pattern identifier; audit keeps its existing actor/reason metadata contract.

The decision ID includes the opt-in mode. Replaying the same journal operation adds no duplicate audit pair. Changing modes with the same journal id is rejected as an idempotency collision. Ordinary rejection IDs and return shape stay compatible.

## Replay and revocation

After successful commit, subsequent sequential ingest/import paths that invoke the existing Immune pre-screen reject matching wording even with a new fact ID. The guard survives a fresh process. The tests exercise ordinary ingest, sourced/text ingestion, file import, case/punctuation normalization and the strict read view, with an independently admitted neighboring fact as positive control.

The guard can be revoked explicitly through the existing audited operation:

```bash
velantrim immune-allow RETURNED_PATTERN_ID
```

Revoking the guard does not resurrect the original Collapsed record, bypass other gates, or make the content true. New admissible records remain subject to ordinary identity, evidence, Guardian and TruthGate policy. A pattern may already be shared with an earlier manual Immune rule; revocation removes that shared rule, not just one rejection's reference. Review `immune-report` first.

## Scope and limits

- Matching is the existing normalized whole-token containment rule, not semantic equality, paraphrase recognition or a Unicode-confusables defense. Longer text containing the pattern can also be blocked, including a quotation or a legitimate correction. Use the explicit option cautiously and revoke it when appropriate.
- Scope is the selected SQLite workspace. It is not per tenant, subject or predicate. No tenant authorization claim is made.
- This is a **storage/admission block on subsequent screened paths**, not physical erasure or a guarantee to remove the content from audit reasons, source files, logs, backups, earlier records or every existing read surface. Immune stores normalized pattern text under its existing contract. It must not be presented as REDACT_PII or GDPR erasure.
- This transaction does not fence an ingest that already passed its pre-screen before the decision committed. Direct low-level writes or paths that do not call Immune are outside the claim. No universal anti-resurrection guarantee is made.
- Existing canonical records with the same content are not silently deleted or demoted. The operation applies to an Observed candidate. Normal query operations remain read-only.
- Changing the guard's global severity floor can disable existing rules. A compound decision fails closed when the current floor exceeds the maximum severity instead of claiming to install an effective block. Policy changes after commit still take effect normally.
- Trusted in-process callers of `review.reject` remain responsible for authentication; bundled CLI access goes through `curator_runtime`. No new HTTP/MCP argument or automatic model tool is added.
- No LLM/API call, scheduler activation, semantic Reader, PostgreSQL activation or production authorization is introduced.

## Validation

`tests/test_reject_reentry.py` exercises the opt-in workflow, default compatibility, source-linked positive controls, revocation, on-disk SQLite L3 across processes, denied principals/spoofed actors, failure rollback, process death before commit, idempotent concurrent requests and malformed inputs. The exact results and baseline exceptions are recorded in `docs/status/reentry-guard-lab.json`.

```bash
python -m pytest tests/test_reject_reentry.py tests/test_review.py tests/test_review_decision_outbox.py tests/test_review_decision_hardening.py tests/test_review_decision_defensive_edges.py tests/test_immune.py tests/test_immune_atomicity.py tests/test_immune_atomicity_recovery.py tests/test_curator_runtime.py tests/test_cli_curator_principal.py -q -o addopts=''
```
