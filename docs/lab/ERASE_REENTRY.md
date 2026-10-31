# Crystal-Test: opt-in erasure with lexical reentry blocking

Status: experimental opt-in feature in `Velantrim-Exo-Cortex-Crystal-Test`.
This document does not describe an upstream Crystal main capability and does not
reopen completed Crystal V1.

## Problem

Physical erasure writes a content-free `erasure_log` tombstone. Ingest does not
read that tombstone as a wording block. After an erase for wrongness, the same
normalized claim can return under a new `fact_id` unless a curator also records
an Immune pattern. Atlas review called this out as an unjoined erasure /
rejection-memory boundary.

Ordinary `erase` remains GDPR Art. 17 physical deletion and stays unchanged.

## User operation

```bash
export VELANTRIM_CURATOR_ACTOR=lab-admin
export VELANTRIM_CURATOR_ROLES=ADMIN
export VELANTRIM_CURATOR_SCOPES='fact:*'

velantrim erase FACT_ID \
  --reason 'curator_wrong_claim' \
  --block-reentry
```

`--block-reentry` is opt-in. The CLI path goes through
`erase_with_reentry_block_as_principal` and requires **ADMIN + `fact:*`**, matching
`review-reject --block-reentry`. It records the existing Immune Guard pattern from
the stored claim **before** deletion, then performs the ordinary erase path.
The receipt includes `reentry_pattern_id` on success. Exit `2` = principal
configuration failure; exit `3` = authorization denial.

Trusted in-process callers may still call `erase_fact(..., block_reentry=True)`
directly; they remain responsible for authentication (same class of boundary as
direct `review.reject`).

Privacy-shaped reasons are refused (`data_subject_request`, `gdpr_request`,
`privacy`, `right_to_be_forgotten`, `art17`, `art_17`). Immune stores normalized
pattern text; that is incompatible with a privacy erasure claim. Use an explicit
wrongness reason. A free-text reason denylist is not a structured privacy intent
classifier (P2 follow-up).

Revoke the guard without resurrecting the erased row:

```bash
velantrim immune-allow RETURNED_PATTERN_ID
```

## Shared pattern / quotation risks

- Immune pattern ids are derived from normalized claim text. If a pattern already
  exists, erasure_reentry upserts type/severity on that **shared** row.
  `immune-allow` removes the shared rule, not a per-erase reference.
- Matching is whole-token containment. A later corrective sentence that quotes
  the blocked wording can also be refused. Use the opt-in cautiously and revoke
  when appropriate (same class of limit as `REJECT_REENTRY.md`).

## Limits

- Default erase still allows same-wording reentry (documented by tests).
- Matching is the existing normalized whole-token Immune rule, not paraphrase /
  semantic identity.
- Guard install and physical erase are sequential: Immune commit happens before
  L1/L3 deletion. L1 and L3 are not one distributed transaction (same class of
  limit as other Crystal write paths). If erase fails after the pattern is
  recorded, the pattern may remain — fail-closed toward blocking for wrongness.
- Cascade deletes never inherit `--block-reentry`.
- Not REDACT_PII, not GDPR certification, not multi-tenant scope.
- TruthGate / Guardian / Canon admission ownership unchanged.
- This is **erase + optional lexical block**, not belief revision with preserved
  correction history.

## Validation

```bash
python3 -m pytest -o addopts='' \
  tests/test_erase_reentry.py tests/test_erasure.py tests/test_immune.py -q
```
