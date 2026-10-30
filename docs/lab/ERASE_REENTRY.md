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
velantrim erase FACT_ID \
  --reason 'curator_wrong_claim' \
  --block-reentry
```

`--block-reentry` is opt-in. It records the existing Immune Guard pattern from
the stored claim **before** deletion, then performs the ordinary erase path.
The receipt includes `reentry_pattern_id` on success.

Privacy-shaped reasons are refused (`data_subject_request`, `gdpr_request`,
`privacy`, `right_to_be_forgotten`, `art17`, `art_17`). Immune stores normalized
pattern text; that is incompatible with a privacy erasure claim. Use an explicit
wrongness reason.

Revoke the guard without resurrecting the erased row:

```bash
velantrim immune-allow RETURNED_PATTERN_ID
```

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

## Validation

```bash
python3 -m pytest -o addopts='' \
  tests/test_erase_reentry.py tests/test_erasure.py tests/test_immune.py -q
```
