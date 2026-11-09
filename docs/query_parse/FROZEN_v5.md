# Query-parse parser v5 — FROZEN

* File: `core/query_parse.py`
* sha256: `9d87bd5d2ad8bed7682deefbf81cd570730df7b6fec486ceb29a4ad7c397f6f5`
* Last commit changing the file: `5a16e6ca49f1a5ca06bb1c9eb8f93168f6ba7301`
* Git tag: `query-parse-v5-frozen` (lightweight; points at the commit adding this record)
* Frozen on 2026-11-09 (Europe/Berlin). Rules: R1–R6 (user/Astra decision 2026-11-09), see docs/QUERY_PARSE_EXPERIMENT.md.

After this freeze no parsing rules are changed.

Verify: `sha256sum core/query_parse.py` and `git diff query-parse-v5-frozen -- core/query_parse.py` (empty).

Earlier frozen snapshots: v1 `tests/query_parse_v1.py`, v2 `tests/query_parse_v2.py`,
v3 `tests/query_parse_v3.py`, v4 `tests/query_parse_v4.py`
(sha256 `81e1f6632163ddd1d88d365b2d8a7f2121197ac00885c9452c865a93a9ac9d26` = tag `query-parse-v4-frozen`, not moved).
