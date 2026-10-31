# Crystal-Test Top-3 LAB — review protocol (post-audit)

**Role:** reviewer checklist / acceptance protocol (not runtime authority).  
**Date:** 2026-10-31  
**Independent audit input:** ChatGPT Top-3 LAB audit (conflict #8↔#9, fail-open #11, auth #10).

## Decision recorded after audit

| Item | Decision |
|---|---|
| #8 vs #9 | Allow independent `lab.yml`; forbid only excluded **upstream** workflows. Lab CI ≠ canonical Crystal proof. |
| #11 empty curator token | Present-but-empty env → `401`, no writer-token fallback; presence disables unauth-local. |
| #10 erase reentry auth | CLI `--block-reentry` requires ADMIN + `fact:*` via curator_runtime helper. |

## PR heads to verify (update after each push)

| PR | Branch | Topic |
|---|---|---|
| #9 | `cursor/lab-identity-honesty-2fc7` | LAB identity + upstream/lab CI distinction |
| #10 | `cursor/erase-reentry-guard-2fc7` | erase `--block-reentry` + ADMIN gate |
| #11 | `cursor/split-api-tokens-2fc7` | split HTTP tokens + empty-token fail-closed |
| #8 | `codex/lab-ci-and-experiment-protocol-2026-10-29` | independent lab.yml (external) |

Resolve live SHAs with GitHub before merge. Rebase dependents after each merge.

## Acceptance checks

### #9
- [ ] Upstream workflows still absent
- [ ] Optional `lab.yml` does not break smoke/contract
- [ ] Provenance declares `upstream_workflows_present: false` and `lab_ci_is_not_canonical_crystal_proof: true`
- [ ] README does not claim upstream 9-job gate locally

```bash
bash scripts/lab_smoke.sh
```

### #10
- [ ] Default erase still allows reentry (regression test)
- [ ] Non-admin CLI `--block-reentry` → exit 3 / authorized false
- [ ] Admin + fact:* succeeds; shared-pattern / quotation risks documented

```bash
python3 -m pytest -o addopts='' tests/test_erase_reentry.py tests/test_erasure.py -q
```

### #11
- [ ] Unset curator token → single-token baseline
- [ ] Distinct curator token → writer cannot approve
- [ ] Empty curator token env → 401, no fallback
- [ ] Equal tokens → 401

```bash
python3 -m pytest -o addopts='' tests/test_api_split_tokens.py tests/test_api_curator_principal.py -q
```

## Remaining P2 (not blocking this protocol)

- Structured erase intent instead of privacy reason denylist
- Belief-revision surface distinct from erase/block (architecture note only)

## Reviewer verdict block

```text
Reviewed by:
Date:
#9: APPROVE / REQUEST CHANGES / DEFER
#10: APPROVE / REQUEST CHANGES / DEFER
#11: APPROVE / REQUEST CHANGES / DEFER
#8: APPROVE / REQUEST CHANGES / DEFER
Notes:
```
