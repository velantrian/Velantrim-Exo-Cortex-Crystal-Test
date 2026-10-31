# Crystal-Test: optional split ingest / curator HTTP tokens

Status: experimental opt-in in `Velantrim-Exo-Cortex-Crystal-Test`.
Does not rewrite ADR-018 for upstream Crystal and does not claim production IAM.

## Problem

The bundled FastAPI service maps one bearer token to one curator principal.
A deployment that gives an agent `VELANTRIM_API_TOKEN` for `/ingest` therefore
also grants `/review/approve` and `/review/reject` unless the host splits auth.

## Opt-in dual-token mode

```bash
export VELANTRIM_API_TOKEN='writer-only-secret'
export VELANTRIM_API_CURATOR_TOKEN='curator-only-secret'   # must differ
export VELANTRIM_CURATOR_ACTOR=alice
export VELANTRIM_CURATOR_ROLES=CURATOR
export VELANTRIM_CURATOR_SCOPES='fact:*'
```

| Surface | Credential |
|---|---|
| `/ingest`, `/ask`, review GET helpers | `VELANTRIM_API_TOKEN` |
| `/review/approve`, `/review/reject`, `/review/resolve-conflict` | `VELANTRIM_API_CURATOR_TOKEN` |

When `VELANTRIM_API_CURATOR_TOKEN` is unset, behavior stays the ADR-018
single-token baseline.

## Fail-closed rules

- whitespace-padded curator token → `401`
- curator token equal to API token → `401`
- curator token set without API token → `401` (disables unauth-local bypass)
- writer bearer on curator write routes → `401` with zero mutation

## Limits

- Still one configured principal mapping (not multi-user IdP).
- No token issuance/rotation/revocation service.
- No tenant isolation or distributed fencing.
- MCP remains read-only and unchanged.
- Not a production multi-tenant authorization claim.

## Validation

```bash
python3 -m pytest -o addopts='' \
  tests/test_api_split_tokens.py tests/test_api_curator_principal.py -q
```
