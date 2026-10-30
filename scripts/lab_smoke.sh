#!/usr/bin/env bash
# Crystal-Test local lab smoke — not the upstream 9-job CI gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -d .github/workflows ]]; then
  echo "FAIL: .github/workflows must remain absent in Crystal-Test LAB" >&2
  exit 1
fi

if ! grep -q 'upstream_snapshot_commit: 692e05e319d1a789752fe797235798d4380e60d4' FORGE_LAB_PROVENANCE.md; then
  echo "FAIL: FORGE_LAB_PROVENANCE.md missing explicit upstream snapshot pin" >&2
  exit 1
fi

if ! grep -q 'workflows_present: false' FORGE_LAB_PROVENANCE.md; then
  echo "FAIL: FORGE_LAB_PROVENANCE.md must declare workflows_present: false" >&2
  exit 1
fi

PY=""
if command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
fi
if [[ -z "$PY" ]] && command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
fi
if [[ -z "$PY" ]]; then
  echo "FAIL: python3/python not found" >&2
  exit 1
fi

set +e
"$PY" -m pytest -o addopts='' tests/test_security_reproducibility_contract.py -q
status=$?
set -e
if [[ $status -ne 0 ]]; then
  if command -v pytest >/dev/null 2>&1; then
    pytest -o addopts='' tests/test_security_reproducibility_contract.py -q
  else
    echo "FAIL: pytest unavailable for LAB smoke (exit $status)" >&2
    exit "$status"
  fi
fi

echo "LAB smoke OK — local identity/security contract only; not upstream CI proof."
