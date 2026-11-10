# Query-parse parser v4 — FROZEN

* File: `core/query_parse.py`
* sha256: `81e1f6632163ddd1d88d365b2d8a7f2121197ac00885c9452c865a93a9ac9d26`
* Last commit changing the file: `dfd854edc951ea86fa2cdf6fa9935bd233d7a12a`
* Git tag: `query-parse-v4-frozen` (lightweight; points at the commit adding this record)
* Frozen on 2026-11-09 (Europe/Berlin).

After this freeze no parsing rules are changed. The independent check
(`tests/fixtures/query_parse/independent_v4.json`) is run against exactly this
file; disagreements are recorded and classified, not fixed.

Verify: `sha256sum core/query_parse.py` and `git diff query-parse-v4-frozen -- core/query_parse.py` (empty).

Earlier frozen snapshots: v1 `tests/query_parse_v1.py`, v2 `tests/query_parse_v2.py`,
v3 `tests/query_parse_v3.py` (sha256 `bd5e8f7a5f8b5f5e5a46a10c6814b3fd476ac5cf7dfae0553eb865a7ac822897`).
