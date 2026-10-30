# Forge Lab Provenance

This repository is an **isolated experimental copy** prepared for controlled Forge testing; it is not the upstream repository. The snapshot comes from the tracked-file tree at commit `692e05e319d1a789752fe797235798d4380e60d4` (tree `fa5ab819abdcd62bdee53dfaa2ac8f33922df1e6`) in [velantrian/velantrim-exocortex-crystal](https://github.com/velantrian/velantrim-exocortex-crystal). Git history was not copied. The source code, documentation, tests, configuration, and AGPL-3.0 license were copied without intentional production-logic changes. No secrets or credentials were identified by the preparation audit.

```yaml
lab_surface: crystal_test
canonical_repo: velantrian/velantrim-exocortex-crystal
upstream_snapshot_commit: 692e05e319d1a789752fe797235798d4380e60d4
upstream_snapshot_tree: fa5ab819abdcd62bdee53dfaa2ac8f33922df1e6
git_history_copied: false
workflows_present: false
excluded_workflows:
  - .github/workflows/ci.yml
  - .github/workflows/l3-benchmark-history.yml
  - .github/workflows/postgresql-integration.yml
authority: LAB_ONLY
pin_role: identity_and_provenance_not_live_upstream_head
local_verification: scripts/lab_smoke.sh
```

The three upstream GitHub Actions workflows were deliberately excluded: `.github/workflows/ci.yml`, `.github/workflows/l3-benchmark-history.yml`, and `.github/workflows/postgresql-integration.yml`. Consequently, the Crystal-Test security reproducibility contract asserts that those workflow files remain absent and keeps supply-chain pins that still exist in this copy (Dependabot + `.github/requirements-security.txt`). Upstream action-SHA pins remain documented expectations for the canonical repository; they are not enforced against missing workflow files here.

In the complete lab preparation run, the remaining suite reported 2,372 passed and 13 skipped, with 100% coverage. That measurement is historical lab-preparation evidence, not a claim that this repository currently runs the upstream 9-job CI gate. This repository has not been submitted to Forge.

**Do not treat green local smoke, historical coverage numbers, or inherited STATUS/TEST_REPORT text as verified Crystal `main` CI proof.**
