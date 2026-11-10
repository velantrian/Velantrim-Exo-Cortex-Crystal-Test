# Query-parse parser v6.1 — FROZEN

* File: `core/query_parse.py`
* sha256: `d1a879827712bc6f8f59e59bcdad27b6626f48f1c7ffa51ad1528bf70945a469`
* Last commit changing the file: `96ed6eee61fbdc5ab9eaa7c65bd1a9e5c711d8c3`
* Git tag: `query-parse-v6.1-frozen` (lightweight; points at the commit adding this record)
* Frozen on 2026-11-09 (Europe/Berlin). One scoped change on top of v6 (user decision 2026-11-09):
  a later turn with an unresolved time or an unfinished clarification, or an intermediate
  unsupported question with a different time, blocks inheriting the time of an older parsed turn.
  No vocabulary change.

Verify: `sha256sum core/query_parse.py` and `git diff query-parse-v6.1-frozen -- core/query_parse.py` (empty).

Earlier frozen snapshots: `tests/query_parse_v1.py … tests/query_parse_v6.py`
(v6 sha256 `e1ffd85719ff0adca17d91b2b36987b8ef1342db8b59977030793f3c073e3c70` = tag `query-parse-v6-frozen`;
v5 = tag `query-parse-v5-frozen`; v4 = tag `query-parse-v4-frozen`; no tag moved).
