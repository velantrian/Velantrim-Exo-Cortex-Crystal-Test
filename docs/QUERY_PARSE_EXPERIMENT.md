# Experiment: ordinary questions → explicit Crystal filter parameters (lab, v1)

Status: **lab experiment, draft**. Goal: learn whether a user can drive the
existing object/time filter with ordinary Russian phrasing and which errors the
parsing step adds. This is **not** a claim of general “understanding”.

## Pinned versions

| What | SHA |
|---|---|
| Crystal-Test `main` (base of this branch) | `2772cb5595d96bd149f58a0a7772fda97d357f9a` |
| Crystal-Test PR #13 head (earlier lab filter, untouched) | `fbd99947bb2550db2768f8fd154cafdd3d561488` |
| main Crystal merge of #503 (reference contract) | `ba8e84a4f8f24bdb816ea8fb89485f1dedccd0a3` |
| main Crystal #503 verified head | `13a83c29c2712acee4130fac25a1648d98f3c985` |

Base choice: Crystal-Test `main` + port of the accepted #503 contract, not PR #13,
because #13 predates the audit fixes (`metadata["applicability"]` persistence,
inclusive date-only `valid_until`, receipt boundary) and is still open.

## Step 1 — alignment with the accepted #503 contract

`core/applicability.py` is byte-identical to main Crystal `ba8e84a`; the
pipeline/query/HTTP/CLI/async wiring and #503 tests were ported. Lab-specific
change: lab `store_fact` has no `preserve_metadata`, so `build_facts_pack`
reads the existing row's metadata and carries it forward before embedding
`metadata["applicability"]` (read-then-write, not one atomic unit — lab
limitation). See `docs/OBJECT_TEMPORAL_APPLICABILITY.md` for the contract and
`tests/test_lab_503_alignment.py` for lab-specific pins, including the
**inclusive end-of-day** fix: at `fbd9994`, `valid_until="2026-11-08"` with
`as_of="2026-11-08T12:00:00+01:00"` was treated as expired (midnight); now it is
covered until 23:59:59.999999 of that day. Receipt boundary (three cases:
current next to old; only old; only current) is in
`tests/test_applicability_receipt_boundary.py`.

## Step 2 — parser contract (`core/query_parse.py`)

Pure function, stdlib only, no I/O, no model calls, no server clock, no
machine timezone.

`parse_question(question, known_objects, context=None, *, now, timezone)`

* `known_objects`: `[{"id": "L", "names": ["L", "Л"]}, …]`
* `context`: prior **structured** turns (`context_turn(question, result)`),
  newest last. Bound: only the last `MAX_CONTEXT_TURNS = 3` are used; old text
  is never re-parsed. The newest turn with an object decision decides: a parsed
  object, or candidates (→ clarification).
* `now`: explicit aware `datetime`; `timezone`: explicit IANA name or tzinfo.

Result kinds:

* `parsed` — `params = {asked_object, as_of, temporal_scope: "current"}` and
  `explanation` per parameter (which alias/negation, which context turn, which
  explicit clock/zone/year source);
* `needs_clarification` — one concrete question (+ `candidates` when relevant);
* `unsupported` — a limitation message.

`ask(..., query_fn=...)` is the gate: only `parsed` calls the query, always with
all three parameters and `request_error(...) is None`; other kinds run nothing
and return no answer. A parse failure therefore never becomes a query with an
omitted (= disabled) object or time filter.

### Mapping onto #503 (semantics unchanged)

`temporal_scope="current"` + `as_of=T` means *state at T*: admitted grounds are
facts whose validity interval covers T, or whose observation is exactly T at
the same precision; earlier observations are historical-only. Hence:

| Phrase | as_of | Notes |
|---|---|---|
| «сейчас», «на данный момент», «текущий», «теперь» | explicit `now` instant | |
| «сегодня» | date-only, calendar day of `now` in the explicit zone | whole day must be covered — **not** the same as «сейчас» |
| «вчера» (bare) / «8 ноября» | date-only | whole day |
| «вчера в 10:00», «8 ноября в 10:00» | instant in explicit zone | year from explicit `now`; if that lands in the future → year clarification |
| «за вчера», «за неделю», «с … по …», «между», «в течение» | — | `unsupported` (period) |
| «что менялось», «изменился», «сравни», «история», «когда …», «будет/завтра» | — | `unsupported` |
| no time words | — | clarification («сейчас или на дату?»), never unscoped |
| part of day («утром») | — | clarification |
| DST-ambiguous/nonexistent local time | — | clarification |

Follow-ups: «А его статус?» takes the object only from bounded context; time is
inherited from that turn (relative «сейчас» re-anchored to the new explicit
`now`, an absolute moment/date reused); no prior time → clarification.

Objects: aliases matched case-insensitively, longest match; single-word
Cyrillic aliases accept a few case endings (e.g. «Пульсара»). A mention
immediately after «не» is negated. Several positive objects, an unknown
identifier-like token (e.g. `Z`), a shared alias (collision) or no object →
clarification naming candidates.

## Step 3 — question/evidence boundary

The parser only produces request parameters. It never writes object,
observation time or `status_applies_to` onto facts, and never touches memory or
truth status. Tests: L question with an L2 document linked to L → L2 not
admitted; fact dicts unchanged after the query; live SQLite dumps equal before
and after parsed queries; persisted declarations unchanged
(`tests/test_query_parse.py`).

## Step 4 — usefulness (isolated data)

Data: `tests/fixtures/query_parse/setup.json` (7 synthetic VERIFIED facts,
5 objects incl. alias collision «Пульсар»). Conditions on the same questions:
manual gold parameters vs parser parameters, both through the same ported
filter. Gold written before running. `heldout.json` was frozen in its own
commit before the parser landed. Results (`docs/query_parse/eval_results.json`,
regenerate with `python -m tests.query_parse_eval --write`):

| Split | n | correct parse | **confident misparse** | correct clarif. | unnecessary clarif. | correct unsupported | wrong unsupported | answers differ from manual |
|---|---|---|---|---|---|---|---|---|
| dev | 28 | 14 | 0 | 8 | 0 | 6 | 0 | 0 |
| held-out | 24 | 15 | 0 | 5 | 1 | 3 | 0 | 1 (H23) |
| post-hoc probes | 10 | 1 | 1 | 4 | 3 | 0 | 1 | 4 |

Error examples:

* H23 «Какой статус был у L позавчера в 12:00?» → unnecessary clarification
  («Какого дня…»): «позавчера» is not in the rules (deliberately not added after
  seeing the held-out set).
* P01 «… 8 ноября в 10:00 по московскому времени?» → **confident misparse**:
  timezone in the question is ignored, explicit Europe/Berlin used (10:00+01:00
  instead of +03:00). On this data the answer happens to match the manual one.
* P09 «… в 10:00 UTC?» → `UTC` treated as an unknown object → wrong clarification.
* P10 «…, если не считать L2?» → negation not adjacent → clarification about L/L2.
* P05 «Был ли L готов вчера в 10:00?» → no status word → unsupported.
* Unit test: «Главного моста» with alias «Главный мост» → **confident misparse**
  to object M (alias «Мост»): multi-word aliases are not inflected.

Honesty notes: dev, held-out and gold were written by the same author; the
parser code was written after the held-out file was frozen, but by someone who
had read it. To limit leakage the vocabulary was restricted to forms planned
before the held-out set was written; no rule was changed after the first
held-out run. Probes were written after seeing results and are not held-out.
The set is small and synthetic; numbers are not a general accuracy estimate.

Demonstration: `docs/query_parse/demo.md` / `demo.json`
(Question → parsed parameters → admitted grounds → answer or clarification).

## Limitations

* Rules only; Russian phrasing set only; small isolated synthetic set.
* One object, one moment. Periods, changes, comparisons, history, event times,
  forecasts are unsupported.
* Explicit `now` and timezone are required; a timezone named inside the
  question is ignored (known confident-misparse mode, P01).
* Bounded structured context (3 turns); no coreference beyond the rules.
* The parser decides what was asked; it does not establish the semantic
  correctness of author markup (`primary_object`, times, `status_applies_to`) —
  still a separate task, as in #503.
* `#503` caveats carry over: explicit parameters only, interval beats
  `observed_at`, open `valid_from` is indefinite, object ids case-sensitive.
* No general “understanding” is claimed.
