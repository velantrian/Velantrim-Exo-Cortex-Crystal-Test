# Experiment: ordinary questions → explicit Crystal filter parameters (lab, v1 → v2 → v3)

> The **v1 report** (sections “Pinned versions” … “Limitations”) is preserved as
> written at `d550f3f`; its numbers are reproducible byte-identically from the
> frozen snapshot `tests/query_parse_v1.py` (`python -m tests.query_parse_eval
> --version v1 --write` → `docs/query_parse/eval_results_v1.json`,
> `demo_v1.{md,json}`). The **v2** section describes the fixes made after the
> first review; it is preserved too (`eval_results_v2.json`, `demo_v2.*`,
> `before_after_v2.json` regenerate byte-identically from the frozen
> `tests/query_parse_v2.py` with `--version v2 --write`). The **v3** section at
> the end follows the second review.

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
commit before the parser landed. Results (`docs/query_parse/eval_results_v1.json`,
regenerate with `python -m tests.query_parse_eval --version v1 --write`):

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

Demonstration: `docs/query_parse/demo_v1.md` / `demo_v1.json`
(Question → parsed parameters → admitted grounds → answer or clarification).

## Limitations (v1)

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

---

# v2 — fixes after review (explicit user constraints are kept)

Reviewer (Astra) reproduced four **confident misparses** of v1 on `d550f3f`.
Main point: a correct filter can still give a well-grounded answer to a
**wrongly parsed** question. v2 fixes these four failure modes; it does not
extend the supported vocabulary (no LLM, stdlib only, no new dependencies,
`#503` semantics unchanged, the parser still writes nothing onto facts/memory).

## What changed in `core/query_parse.py`

1. **Zone named in the question is never ignored.** Closed list only:
   «по московскому времени» / «по Москве» / «МСК» / `MSK` → `Europe/Moscow`;
   «по берлинскому времени» / «по Берлину» → `Europe/Berlin`; `UTC` / «по UTC»
   → `UTC`. The named zone overrides the default zone (explanation says so).
   Anything else zone-like («по местному/киевскому времени», `GMT`, `GMT+3`,
   `МСК+1`, `13:00+03:00`, «по Гринвичу», «часовой пояс …», «по времени …»,
   «по <City>» that is not an object alias) or two different zones →
   `needs_clarification`, **no query**. A zone named in a follow-up without a
   moment does not silently re-interpret an earlier absolute moment →
   clarification. `UTC` is no longer treated as an unknown object.
2. **Compound names are not replaced by a shorter one.** Every Cyrillic word of
   a multi-word alias accepts a few case endings (adjective / feminine / soft /
   hard-noun families), so «Главного моста» → «Главный мост» (B). If a short
   alias («Мост») sits where a longer alias that contains it nearly matches
   (neighbouring word shares its first 4 letters, e.g. «Главнейшего моста»), →
   clarification with both candidates. Forms outside the light rules (e.g.
   fleeting vowel «узел» → «узла») are not found → clarification, not another
   object.
3. **Time alternatives are kept.** Two or more clock expressions, two or more
   day expressions, or a numeric alternative («7 или 8 ноября», «в 10 или
   11 часов», «8 и 9 ноября») → clarification listing them. The first match
   is not treated as the user's choice.
4. **A non-parsed turn cannot silently restore an old object.** Every result
   now carries `mentioned_objects` (positively mentioned known objects, negated
   ones excluded); `context_turn` keeps them for unsupported/clarified turns.
   When a pronoun/follow-up looks back through the bounded context, objects
   mentioned in non-parsed turns after the last parsed one are collected; if
   they include anything other than that parsed object → clarification with
   all candidates (e.g. `L, L2`). If they mention only the same object, it is
   kept and the explanation says so.

The v1 code is frozen at `tests/query_parse_v1.py` (byte-identical to
`core/query_parse.py` at `d550f3f`, sha256 `2182d38a77903762d000e92a8c8b4d4560e32d8c1a06c0653c6013f7e228e6e3`).
`tests/test_query_parse_v1_defects.py` asserts the **defective** v1 behaviour on
that snapshot (including the original «Главного моста» → M assertion,
verbatim) — evidence, not specification. `tests/test_query_parse_v2_fixes.py`
pins the fixed behaviour; every case checks the parse parameters **and**
whether the query ran (spy `query_fn`); with ambiguity it must not run.

## New counterexample set

`tests/fixtures/query_parse/counterexamples_v2.json` — 20 items (zone 8,
compound name 4, time alternatives 4, object switch 4), gold written and
committed (`2e72626`) **before** the fixes. It adds an isolated object `B`
(«Главный мост») and fact `B-closed` for this file only. Items with
`context_questions` build their structured context by running the parser under
test on those questions, so v1 and v2 each get the context they would really
produce. dev / held-out / probes / setup fixtures are unchanged.

## Results v2 (`docs/query_parse/eval_results_v2.json`, `python -m tests.query_parse_eval --write`)

| Split | n | correct parse | **confident misparse** | correct clarif. | unnecessary clarif. | correct unsupported | wrong unsupported | answers differ from manual |
|---|---|---|---|---|---|---|---|---|
| dev | 28 | 14 | 0 | 8 | 0 | 6 | 0 | 0 |
| held-out | 24 | 15 | 0 | 5 | 1 | 3 | 0 | 1 (H23) |
| post-hoc probes | 10 | 3 | 0 | 4 | 2 | 0 | 1 | 3 (P02, P05, P10) |
| counterexamples v2 | 20 | 8 | 0 | 12 | 0 | 0 | 0 | 0 |

Same items with the frozen v1 snapshot (for comparison):

| Split | n | correct parse | **confident misparse** | correct clarif. | unnecessary clarif. | correct unsupported | wrong unsupported | answers differ from manual |
|---|---|---|---|---|---|---|---|---|
| dev (v1) | 28 | 14 | 0 | 8 | 0 | 6 | 0 | 0 |
| held-out (v1) | 24 | 15 | 0 | 5 | 1 | 3 | 0 | 1 (H23) |
| post-hoc probes (v1) | 10 | 1 | 1 | 4 | 3 | 0 | 1 | 4 |
| counterexamples v2 (v1) | 20 | 4 | 14 | 1 | 1 | 0 | 0 | 14 |

`clarification_instead_of_unsupported` is 0 everywhere. Every changed item
(19) is listed in `docs/query_parse/before_after_v2.json`; the demonstration
with a “Before (v1)” line is `docs/query_parse/demo_v2.md` / `demo_v2.json`.

## Before → after (the four reviewed cases)

| Case | v1 (`d550f3f`) | v2 |
|---|---|---|
| P01 «…8 ноября в 10:00 по московскому времени?» | `as_of 10:00+01:00` (Berlin); query ran; L-repair (answer matched manual **by coincidence**) | `as_of 10:00+03:00`; L-repair |
| **C01** «…8 ноября в 13:00 по московскому времени?» | `13:00+01:00`; query ran; **L-ready «готов»** ≠ manual | `13:00+03:00` (= 11:00 Berlin); **L-repair «на ремонте»** = manual |
| C02 «…в 13:00 по Берлину?» (contrast) | `13:00+01:00`; L-ready | same; explanation names the zone |
| C03 «…8 ноября в 11:30 UTC?» | clarification «L, UTC?» (UTC as object); no query | `11:30+00:00` (= 12:30 Berlin); L-ready |
| C04/C05/C07 «по местному/киевскому времени», «по Лондону» | Berlin used; query ran; L-ready | clarification; **no query** |
| C06 «…13:00 GMT+3?» | clarification, but for the wrong reason («L, GMT?») | clarification about the zone; no query |
| C09/C10 «Главного моста» | **M** («Мост»); M-works | **B**; B-closed |
| C12 «Главнейшего моста» | M; query ran | clarification B / M; no query |
| C13 «…в 10:00 или в 12:00?» | `10:00`; query ran; L-repair | clarification; no query |
| C14 «…7 или 8 ноября?» | `2026-11-08`; query ran | clarification; no query |
| C15/C16 two moments / «вчера или 7 ноября» | first/one match; query ran | clarification; no query |
| C17 «Какой статус L сейчас?» → «Был ли L2 готов вчера в 10:00?» (unsupported) → «А его статус?» | **L**; query ran; L-ready | clarification «L, L2?»; no query |
| C18/C19 same with «Что менялось у L2 за неделю?» / «…L2 был вчера утром?» | L; query ran | clarification «L, L2?»; no query |
| C20 control: intervening turn mentions only L | L | L (explanation notes it) |

Moscow vs Berlin on the **live store** (SQLite, synthetic facts, dumps equal
before/after): `tests/test_query_parse_v2_fixes.py::test_moscow_vs_berlin_on_live_store_memory_unchanged`
— 13:00 MSK → «L: статус — на ремонте», 13:00 Berlin → «L: статус — готов».

Other visible change: held-out H17 «… в 10:00 по Берлину?» was correct in v1
only because the default zone happened to be Berlin; v2 uses the named zone
explicitly (same parameters, explanation now cites «по берлину»).

## Reading the numbers carefully

* The held-out set was **known to the rule author** before the parser was
  written; it is not an independent check. The v2 counterexamples are written
  by the same author who fixes them, after the reviewer named the failure
  modes — they show that these specific modes are closed, not general accuracy.
* **100 % line/branch coverage** of `core/query_parse.py` means every line and
  branch was executed by some test, **not** that the behaviour is correct: v1
  also had 100 % coverage while a test asserted the wrong «Мост» choice.
* Small, synthetic, Russian-only set. No claim of general “understanding”.

## Still not fixed / limitations (v2)

* Unchanged unnecessary clarifications / wrong unsupported from v1: H23
  «позавчера», P02 «в прошлую пятницу», P10 non-adjacent negation («если не
  считать L2»), P05 «Был ли L готов…» (no status word → unsupported). Not
  addressed on purpose (fix confident errors first, vocabulary later).
* Zones: closed list of three; explicit UTC offsets, other cities/zones,
  abbreviations → clarification (safe, but not parsed).
* Inflection is a small ending table, not morphology: fleeting vowels and
  irregular forms are not found (→ clarification, not a wrong object). The
  near-miss rule uses a 4-letter prefix heuristic; it may ask unnecessarily
  when an unrelated word that shares the prefix precedes a short alias.
* Several-moment detection is conservative: «в 10:00, а не в 12:00» also
  clarifies (negated alternative is not interpreted).
* Possible object switch is tracked only through `mentioned_objects` in the
  bounded 3-turn structured context; turns built by other code without that
  field are treated as before.
* All v1 limitations about #503 and author-markup correctness still apply.

---

# v3 — three more defect classes and general properties

Second review: before extending the vocabulary, fix three defect classes and
pin general properties. v2 is frozen as `tests/query_parse_v2.py`
(byte-identical to `core/query_parse.py` at `eee4062`, sha256
`d2cab8d08829217da46c69975bd8ff2deb0d86262d49f4035ad3416ee17d92d0`); the v2
report regenerates byte-identically from it. `tests/test_query_parse_v2_defects.py`
asserts the defective v2 behaviour on that snapshot (evidence, not spec).

## Defects found in v2 and what v3 does

1. **Zone-name case changed the decision.** v2 detected «по <City>» only with
   a capital letter in the original text, and not at the start of a sentence
   («По Лондону»): «по лондону», «По Лондону …», «ПО ЛОНДОНУ» were silently
   ignored and the default Berlin zone was used (confident misparse). v3
   detects «по <word>» on the casefolded text; the word is a possible
   place/zone unless it is an object alias, a pronoun, or starts with a
   non-place stem (`статус`, `состояни`, `данн`, `умолчани`, … — closed list in
   `_PO_NOT_PLACE`). Supported zones (Москва/Берлин/UTC) were already
   case-insensitive and stay so.
2. **The clock was truncated.** v2 matched only `HH:MM`, so `10:00:30` →
   `10:00:00`, `10:00:61` → `10:00`, «в 10 часов 30 минут» → 10:00, «10:30
   вечера» → 10:30, «в половине десятого» → whole-day date. v3 parses the clock
   whole: `HH:MM[:SS]` with seconds kept exactly; fractional seconds
   (`10:00:30.5`, `10:00:30,25`), minute/second words, «половина», «четверть»,
   «полдень», «полночь», «в 10.00» and ISO `…T10:00` → clarification, no query;
   a day part after a clock is applied («10:30 вечера» → 22:30, «в 10 часов
   вечера» → 22:00, «10 ночи» → 22:00); a combination that is not unambiguous
   («15:00 утра», «в 11 дня») → clarification. Day patterns are searched
   outside clock spans (so `30.5` is not read as a date).
3. **Object choice depended on catalogue order.** v2 tried aliases in
   catalogue order among equally long aliases and took the first match. With
   M «Мост» and Y «Моста»: «Моста» → whichever came first. v3 collects all
   aliases matching at a position, then resolves:
   1. the **longest span** wins (covers more of the user's words: «Главного
      моста» → «Главный мост», not «Мост»);
   2. among equally long spans an **exact name beats a match via inflection**
      («Моста» → Y exactly; M only via «Мост»+«а»);
   3. all objects left at the top tier are kept; **more than one → clarification**
      (same alias on two objects, «Пульсаром» → P1/P2; two inflection-only
      matches, «Мостами» → M/Y).
   The explanation states the match type («точное совпадение названия» / «через
   склонение») and what was outranked. The v2 near-miss rule (4-letter prefix)
   took only the first near miss found in catalogue order for the candidate
   list; v3 uses the union of all near misses, so the candidates do not depend
   on order. The heuristic itself is unchanged.

## Counterexamples v3 and properties

`tests/fixtures/query_parse/counterexamples_v3.json` — 23 items (zone case 9,
clock precision 10, catalogue order 4), gold committed in `c5ff9e6` **before**
the fixes; isolated extension object Y («Моста»), fact `Y-open`.

`tests/test_query_parse_v3_props.py` (stdlib only):
* zone case: 19 zone phrases × 6 case functions (`str`, `lower`, `upper`,
  `title`, `swapcase`, `capitalize`) × 2 positions → one decision per phrase;
* clock: grid of hours × minutes × seconds in three templates → `as_of` has
  exactly those seconds; 15 other forms → clarification; every parsed fixture
  item with an explicit `HH:MM[:SS]` shows the same digits in local `as_of`;
* catalogue: `itertools.permutations` of the catalogue × {names as given,
  reversed} for 8 object cases and a context follow-up; inputs not mutated;
* permutation invariance over all fixture sets (below);
* every clarification is checked with a spy: the query does not run.

Permutation invariance (`docs/query_parse/permutation_invariance_v3.json`;
all catalogue permutations × 2 alias orders; decision = kind, params,
candidates, clarification/limitation text, mentioned objects):

| Split | items | variants | v2: items whose decision changed | v3 |
|---|---|---|---|---|
| dev | 28 | 6720 | none | none |
| held-out | 24 | 5760 | none | none |
| probes | 10 | 2400 | none | none |
| counterexamples v2 | 20 | 28800 | none | none |
| counterexamples v3 | 23 | 33120 | **K20, K21** | none |

## Results v3 (`docs/query_parse/eval_results_v3.json`, `python -m tests.query_parse_eval --write`)

| Split | n | correct parse | **confident misparse** | correct clarif. | unnecessary clarif. | correct unsupported | wrong unsupported | answers differ from manual |
|---|---|---|---|---|---|---|---|---|
| dev | 28 | 14 | 0 | 8 | 0 | 6 | 0 | 0 |
| held-out | 24 | 15 | 0 | 5 | 1 | 3 | 0 | 1 (H23) |
| post-hoc probes | 10 | 3 | 0 | 4 | 2 | 0 | 1 | 3 (P02, P05, P10) |
| counterexamples v2 | 20 | 8 | 0 | 12 | 0 | 0 | 0 | 0 |
| counterexamples v3 | 23 | 11 | 0 | 12 | 0 | 0 | 0 | 0 |
| *counterexamples v3 — v2 snapshot* | *23* | *6* | ***12*** | *5* | *0* | *0* | *0* | *8* |

On dev / held-out / probes / counterexamples v2 the categories are the same as
in v2. 16 items changed (category, parameters, grounds or message text) — all in
`docs/query_parse/before_after_v3.json`; demonstration with a “Before (v2)” line
in `docs/query_parse/demo_v3.md`.

Note: in v2, K10/K13/K14 (seconds truncated) were confident misparses whose
**answer happened to match** the manual one on this data (both instants fall
into L-repair) — the same kind of coincidence that hid the zone bug in P01.

## Before → after (v2 snapshot → v3)

| Case | v2 (`eee4062`) | v3 |
|---|---|---|
| K01 «…13:00 по лондону?» / K02 «По Лондону …» / K03 «ПО ЛОНДОНУ» | Berlin `13:00+01:00`, query ran, «готов» | clarification, no query |
| C07 «…по Лондону?» | clarification | clarification (same; phrase now quoted casefolded) |
| K10 «…в 10:00:30?» | `10:00:00+01:00` | `10:00:30+01:00` |
| K13 «…10:00:30 по Москве?» | `10:00:00+03:00` | `10:00:30+03:00` |
| K14 «на 2026-11-08 10:00:30?» | `10:00:00+01:00` | `10:00:30+01:00` |
| K15 «…10:00:61?» | `10:00:00`, query ran | clarification (not a time), no query |
| K16 «…в 10 часов 30 минут?» | `10:00`, query ran | clarification, no query |
| K17 «…в 10:30 вечера?» | `10:30` → «на ремонте» | `22:30` → «готов» (= manual) |
| K18 «…в половине десятого?» | date-only `2026-11-08`, query ran | clarification, no query |
| K11/K12/K19 `10:00:30.5`, «в 10.00», ISO `T` | clarification (for an unrelated reason) | clarification about the time form |
| K20 «Какой статус Моста сейчас?» (M «Мост», Y «Моста») | M or Y depending on catalogue order (M in fixture order) | Y in every order (exact > inflection) |
| K21 «…Мостами…» | M or Y depending on order | clarification M/Y in every order |

## Reading the numbers carefully

* Fixtures (dev, held-out, probes, counterexamples v2/v3) and fixes are by the
  **same author**; counterexamples were written after the reviewer named the
  defect classes. They show that these classes are closed on these items, not
  general accuracy. Held-out was known to the rule author.
* **Coverage ≠ correctness.** `core/query_parse.py` is again at 100 % lines and
  branches; v2 was at 100 % too while truncating seconds and depending on order.
* Permutation invariance is checked over these catalogues (≤ 6 objects) and
  these questions only.
* No claim of general “understanding”.

## Still not fixed / limitations (v3)

* Same open items as v2: H23 «позавчера», P02 «в прошлую пятницу», P10
  non-adjacent negation, P05 «Был ли L готов…» (wrong unsupported).
* «по <word>» is a possible place unless the word is an alias, a pronoun or in a
  closed non-place stem list → unknown words after «по» ask for clarification
  (safe, but may be unnecessary, e.g. a phrase like «по плану»).
* Seconds are kept; sub-second precision, word forms of time and ISO `T` are
  not parsed (clarification).
* Day-part table is fixed (утра 0–11; дня 1–5 → +12, 12–17; вечера 5–11 → +12,
  17–23; ночи 12 → 0, 0–4, 9–11 → +12, 21–23); anything else clarifies.
* Ranking rule is longest span > exact > inflection. An exact short alias
  inside a longer inflected phrase is still decided by the longest span.
* The near-miss rule is still a 4-letter prefix heuristic.

---

# v4 — user rule change (2026-11-09), explicit identifiers, confirmed choice

## Gold change (a rule change, not a parser result)

On 2026-11-09 the user changed the contract: **if one word form matches two
objects — one directly, one through inflection — both stay candidates and the
parser asks, unless context resolves it.** v3 encoded the opposite rule
("exact > inflection").

* `counterexamples_v3.json` is **not edited**. A new gold file
  `tests/fixtures/query_parse/counterexamples_v3_gold_v2.json` holds the same
  23 questions; only **K20** «Какой статус Моста сейчас?» (M «Мост», Y «Моста»)
  changes: old gold `parsed Y` → new gold `needs_clarification [M, Y]`. Each
  change records `old_gold`, `new_gold`, `reason` (= the user's rule change,
  explicitly *not* a consequence of any parser result). K21–K23 were reviewed and
  unchanged.
* **The v3 report's "0 confident misparse on counterexamples_v3" refers to the
  old gold.** On the new gold the frozen v3 parser has **1 confident misparse
  (K20: picks Y and runs the query)** — see the table below and
  `tests/test_query_parse_v3_gold_change.py`.
* New items `counterexamples_v4.json` (22): E01–E09 explicit identifiers
  («объекта M», «Моста (объект M)», conflicting ids), F01–F13 confirmed choice
  via structured context (answer to a clarification, reuse later, conflict with a
  newer mention, outside the 3-turn window).
* Gold commit `4f9f230` precedes the code commit `dfd854e`.
* v3 was frozen as `tests/query_parse_v3.py`
  (sha256 `bd5e8f7a5f8b5f5e5a46a10c6814b3fd476ac5cf7dfae0553eb865a7ac822897`);
  v1/v2/v3 report files regenerate byte-identically.

## v4 rules

* **Collision:** several objects from one form (direct + inflection, or two
  inflections) → `needs_clarification` with the match type of each candidate,
  e.g. «M (через склонение «мост»), Y (точное название «моста»)». Ranking is now
  by span length only.
* **Explicit identifier:** a token equal to an object id written exactly, after
  «объект*» or in «( )», selects that object if every other mention is
  compatible with it, there is exactly one such id and no «и/или/либо» between
  mentions; otherwise clarification with the union of candidates (E05–E07).
* **Confirmed choice:** right after an object clarification, a bare answer
  («M», «Да, Y», «объект M») naming exactly one offered candidate is a confirmed
  choice. The time comes from the structured `pending_time` stored in the
  context turn (never from re-parsing old text; «сейчас» re-anchors on the
  explicit current `now`). If the clarified question had no time, the parser asks
  for the time and keeps `confirmed_object`. A choice not among the candidates →
  clarification. Later the same collision is resolved by the confirmed choice
  only inside the bounded context (3 turns) and only if no newer turn mentions
  another candidate; a conflict → clarification.
* All other v3 properties kept (zone case invariance, whole clock, order
  independence). Parser never writes facts or memory; `ask()` runs the query
  only for `parsed`.

## Results v4 (`docs/query_parse/eval_results_v4.json`, `python -m tests.query_parse_eval --version v4 --write`)

Columns: correct parse / confident misparse / correct clarification /
unnecessary clarification / correct unsupported / wrong unsupported /
clarification instead of unsupported / answers differ from manual.

| Split | n | parse ✓ | misparse | clarif ✓ | clarif unnecessary | unsup ✓ | unsup wrong | clarif-for-unsup | answers differ |
|---|---|---|---|---|---|---|---|---|---|
| dev | 28 | 14 | 0 | 8 | 0 | 6 | 0 | 0 | 0 |
| heldout | 24 | 15 | 0 | 5 | 1 | 3 | 0 | 0 | 1 (H23) |
| probes | 10 | 3 | 0 | 4 | 2 | 0 | 1 | 0 | 3 (P02, P05, P10) |
| counterexamples_v2 | 20 | 8 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| counterexamples_v3_gold_v2 | 23 | 10 | 0 | 13 | 0 | 0 | 0 | 0 | 0 |
| counterexamples_v4 | 22 | 14 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| *v3 snapshot on cv3_gold_v2* | 23 | 10 | **1 (K20)** | 12 | 0 | 0 | 0 | 0 | 1 |
| *v3 snapshot on cv4* | 22 | 5 | 4 | 3 | 5 | 0 | 5 | 0 | 12 |

v3 on cv4: misparse E06, F04, F05, F13; unnecessary clarification E03, E08,
F02, F11, F12; wrong unsupported F01, F07, F08, F09, F10. dev/heldout/probes/cv2
are identical for v3 and v4. Before→after per item:
`docs/query_parse/before_after_v4.json` (20 items with changed text or
category); demo: `docs/query_parse/demo_v4.md`.

**Permutation invariance** (`permutation_invariance_v4.json`): every
permutation of each split's catalogue × names as given/reversed, context rebuilt
by the parser under test — 108 480 variants over the six v4 sets, `changed = []`
for v4 (and for v3).

## Reading the numbers carefully (v4)

* Same author for the rule, gold and fix; the new items were written knowing the
  rule. They show the stated rules hold on these items, not general accuracy.
* 100 % statement and branch coverage of `core/query_parse.py` again; coverage ≠
  correctness.
* No claim of general “understanding”.

## Still not fixed / limitations (v4)

* Same open items: H23 «позавчера», P02 «в прошлую пятницу», P10 non-adjacent
  negation, P05 «Был ли L готов…» (wrong unsupported; the user will decide
  separately).
* Explicit id must be written exactly as in the catalogue (case-sensitive);
  «объекта m» is a name match, not an explicit id.
* A confirmed choice is used only inside the 3-turn window and only for the same
  candidate set it was confirmed for.
* «по <word>», day-part table and the 4-letter near-miss heuristic unchanged
  from v3.

## Independent check v4 (`docs/query_parse/independent_v4_results.json`)

* Set: `tests/fixtures/query_parse/independent_v4.json`, 30 items, committed
  unchanged (sha256 `4bd2d804b726eaac97120daa175eddd2a42dc67afcb91d3411f858298b0f4cb6`,
  verified against the provided `.sha256`). It was read only after the freeze
  commit `64e485a` and tag `query-parse-v4-frozen` were pushed.
* Its own note: written by a different author (Grok Bot, the assistant) without
  access to the parser code, tests, fixtures, docs or PR, but knowing the contract
  and the v1–v3 defect classes — **not fully independent**.
* Parser: frozen `core/query_parse.py` (sha256 `81e1f663…9d26`), no rule
  changes. Runner: `python -m tests.query_parse_independent_v4 --write`; it only
  maps formats (catalogue aliases → names, file `now`/`default_tz`, earlier
  turns → structured context via the same parser, gold `object_id`/`as_of`/`date`
  → harness gold; as_of compared as an instant).
* Harness issue H1: the set has no facts, so grounds and "answers differ from
  manual" are **n/a**, not 0.

| Set | n | parse ✓ | misparse | clarif ✓ | clarif unnecessary | unsup ✓ | unsup wrong | clarif-for-unsup | answers differ |
|---|---|---|---|---|---|---|---|---|---|
| independent_v4 | 30 | 12 | 3 | 11 | 0 | 2 | 1 | 1 | n/a (H1) |

For every clarification/unsupported item the spy confirms the query was not
called. Catalogue rotations × name order (480 variants): no decision changed
(not all 8! permutations).

**Disagreements with gold (contract_gap = false):**

| id | question | parser | gold | class |
|---|---|---|---|---|
| I13 | «…в десять утра 8 ноября?» | parsed L, date-only 2026-11-08 (query ran) | clarification | **parser error** — worded time silently dropped |
| I20 | «У L статус сейчас лучше, чем у L2?» | clarification L/L2 (no query) | unsupported | **parser error** — comparison «лучше, чем» not detected (safe, wrong kind) |
| I15 | «…будет 12 ноября в 10:00?» | unsupported (forecast) | clarification | gold/contract ambiguity — PR contract maps «будет» to unsupported; neither runs the query |

**contract_gap items (listed separately):** I19, I21, I28, I29, I30 are
flagged. Disagreements among them:

| id | question | parser | gold (cautious) | class |
|---|---|---|---|---|
| I19 | «…котельной сегодня в 08:00?» | parsed K at 2026-11-09T08:00:00+01:00 | clarification | contract ambiguity; parser = the author's named alternative |
| I30 | «…L2 был 7 ноября?» | parsed L2, date-only 2026-11-07 | clarification | contract ambiguity; PR contract says bare date = whole day; parser = named alternative |

I21 («L, а не L2» → clarification), I28 (unknown «Мостик» → clarification) and
I29 («Готов ли L2 сейчас?» → unsupported) agree with the cautious gold. Nothing
was fixed; the two parser errors are open items for a later version.

---

# v5 — rules R1–R6 (user/Astra decision 2026-11-09), fixed BEFORE the code change

v4 is frozen as `tests/query_parse_v4.py` (sha256
`81e1f6632163ddd1d88d365b2d8a7f2121197ac00885c9452c865a93a9ac9d26`, equal to
`core/query_parse.py` at tag `query-parse-v4-frozen`, which is not moved). All
v1–v4 report files and `independent_v4_results.json` regenerate byte-identically
from the frozen snapshots. No vocabulary or new phrasings are added: no «готов ли
L», no new date forms; markers below are used only to **block** a query.

## Rules

* **R1 — time not parsed ⇒ no query.** A time in words («в десять утра 8 ноября»)
  → clarification while word-time is unsupported; a time expression is never
  dropped in favour of a whole-day query. General form: after the parsed clock,
  date, «сейчас» and zone spans are removed, any remaining *time-like marker*
  blocks the query with a clarification. Marker list (detection only, nothing is
  parsed from them): day-part words `утра дня вечера ночи утром днём днем вечером
  ночью` (bare «утром…» without a clock keeps the v1 «часть суток» clarification);
  `час…`; «в» + a 1–2 digit number not consumed by a clock or date («в 10»);
  «в» + an hour numeral word `один/одного … двадцать четыре`.
* **R2 — «сегодня в 08:00»** = the moment today (date from the explicit `now` in
  the explicit zone) at 08:00 in that zone; no explicit zone → clarification. (v4
  already behaved so; now pinned.)
* **R3 — explicit calendar date without a time** («был 7 ноября», «на
  2026-11-07», «на 07.11», follow-up «А 7 ноября?») → clarification asking for the
  time. Replaces the v1–v4 «8 ноября» → date-only whole day.
* **R4 — «весь день 7 ноября».** Finding: v4 does **not** support this phrasing
  explicitly (no rule, not documented); it ignored «весь день» and its bare-date
  rule happened to give date-only `2026-11-07`. So nothing is added: in v5 R3
  applies → **clarification** (never a moment, never another day).
  «сегодня» alone keeps its documented behaviour (date-only, whole day); so does
  «вчера» alone, which R3 does not name. **Inconsistency, reported, not decided:**
  «был 7 ноября» asks for the time, while «сегодня» / «вчера» without a time still
  ask about the whole day. «весь день сегодня» = «сегодня» (same day, whole day).
* **R5 — future moment ⇒ unsupported**, decided by the resolved time vs the
  explicit `now`, not by the word: «Какой статус L 12 ноября в 10:00?» (now =
  9 Nov) → unsupported (v2–v4: year clarification), «был 12 ноября» → unsupported,
  «сегодня в 08:00» at 07:58 → unsupported. Checked before the object (as v4 did
  for «будет»). **«будет» with a past/current resolved time** («будет 8 ноября в
  10:00») → clarification: the tense and the time contradict; neither a forecast
  refusal nor a silent past query. «будет» with no time → unsupported (forecast).
  «завтра/послезавтра» stay unsupported.
* **R6 — comparisons ⇒ unsupported.** Marker list (comparison detection only):
  `сравн…` (v1), `лучше`, `хуже`, `чем`, `отлича…`, `разниц…`, `одинаков…`.

## Gold versions (existing fixture files are not edited)

* `dev_gold_v2.json`: **D15** «Какой статус L был 8 ноября?» parsed date-only
  `2026-11-08` → clarification (R3); **D23** «…20 декабря в 10:00?» clarification
  (year) → unsupported (R5).
* `independent_v4_gold_v2.json` — the 30 opened questions are now a **regression
  set (not independent)**: **I15** «будет 12 ноября в 10:00» clarification →
  unsupported (R5); **I19** «сегодня в 08:00» clarification → parsed K
  `2026-11-09T08:00:00+01:00` (R2). I13, I20, I30 already matched R1/R6/R3.
* Each change has `old_gold`, `new_gold`, `rule`, `reason` (= decision of
  2026-11-09, not a parser result). heldout, probes, cv2, cv3_gold_v2, cv4 were
  reviewed: no item affected.
* `counterexamples_v5.json`: 36 new items (V01–V36) for R1–R6, including the
  morning/evening example on the shared setup (L «на ремонте» until
  2026-11-08T11:59:59+01:00, «готов» from 12:00).

## Results v5 (`docs/query_parse/eval_results_v5.json`, `python -m tests.query_parse_eval --version v5 --write`)

Code commit `5a16e6c` follows the rules/gold commit `483ff98`.

| Split | n | parse ✓ | misparse | clarif ✓ | clarif unnecessary | unsup ✓ | unsup wrong | clarif-for-unsup | answers differ |
|---|---|---|---|---|---|---|---|---|---|
| dev_gold_v2 | 28 | 13 | 0 | 8 | 0 | 7 | 0 | 0 | 0 |
| heldout | 24 | 15 | 0 | 5 | 1 | 3 | 0 | 0 | 1 (H23) |
| probes | 10 | 3 | 0 | 4 | 2 | 0 | 1 | 0 | 3 (P02, P05, P10) |
| counterexamples_v2 | 20 | 8 | 0 | 12 | 0 | 0 | 0 | 0 | 0 |
| counterexamples_v3_gold_v2 | 23 | 10 | 0 | 13 | 0 | 0 | 0 | 0 | 0 |
| counterexamples_v4 | 22 | 14 | 0 | 8 | 0 | 0 | 0 | 0 | 0 |
| counterexamples_v5 | 36 | 9 | 0 | 13 | 0 | 14 | 0 | 0 | 0 |
| *v4 snapshot on dev_gold_v2* | 28 | 13 | 1 (D15) | 7 | 0 | 6 | 0 | 1 (D23) | 0 |
| *v4 snapshot on counterexamples_v5* | 36 | 9 | 11 | 1 | 0 | 5 | 1 | 9 | 6 |

The v4 report's dev numbers (14 / 0 misparse) refer to the old dev gold. v4 on
cv5: misparse V01–V06, V12–V15, V18 (time dropped or bare date → whole-day or
wrong-moment query); wrong unsupported V24; clarification instead of
unsupported V20, V21, V26, V27 (future) and V28–V32 (comparison). Other sets are
identical for v4 and v5. Before→after: `before_after_v5.json` (26 items).

**Permutation invariance** (`permutation_invariance_v5.json`): every catalogue
permutation × name order over the seven v5 sets, 117 120 variants, `changed = []`
for v5 and v4. Regression set: all 8! permutations × name order, 2 419 200
variants, `changed = []`.

### Regression set (formerly independent; `regression_independent_v5.json`)

The 30 questions were opened after the v4 run → **regression, not independent**.

| gold | parser | n | parse ✓ | misparse | clarif ✓ | clarif unnecessary | unsup ✓ | unsup wrong | clarif-for-unsup | not correct |
|---|---|---|---|---|---|---|---|---|---|---|
| original | v4 | 30 | 12 | 3 | 11 | 0 | 2 | 1 | 1 | I13, I15, I19, I20, I30 |
| original | v5 | 30 | 12 | 1 | 13 | 0 | 3 | 1 | 0 | I15, I19 (gold changed by R5/R2) |
| gold_v2 | v4 | 30 | 13 | 2 | 11 | 0 | 3 | 0 | 1 | I13, I20, I30 |
| gold_v2 | v5 | 30 | 13 | 0 | 13 | 0 | 4 | 0 | 0 | — |

"answers differ" is n/a (the set has no facts, H1). No query was called on any
clarification/unsupported item (spy), for both parsers and both golds.

### Morning vs evening (`morning_evening_v5.md`)

Setup L: «на ремонте» until 2026-11-08T11:59:59+01:00, «готов» from 12:00.
Manual parameters: 09:00 / 10:00 → «на ремонте»; 18:00 / 21:00 → «готов».

| question | v4 (frozen) | v5 |
|---|---|---|
| «…в десять утра 8 ноября?» | date-only `2026-11-08`, query ran, **no answer** (whole day not covered) | clarification, no query |
| «…8 ноября в 9:00 вечером?» | `09:00`, query ran, **«на ремонте»** («вечером» dropped; 21:00 would be «готов») | clarification, no query |
| «…8 ноября в шесть вечера?» | date-only, query ran, **no answer** (manual 18:00: «готов») | clarification, no query |

### Demo (`demo_v5.md`): exactly three outcomes

1. **Correct answer** — «Какой статус L был 8 ноября в 09:00?» → `L`, `2026-11-08T09:00:00+01:00` →
   grounds L-repair → «L: статус — на ремонте», receipt cites L-repair.
2. **Useful clarification** — «Какой статус L был в десять утра 8 ноября?» → no query →
   «Время «в десять утра» в такой форме не разобрано … Укажите время как ЧЧ:ММ, например «8 ноября в 10:00».»
3. **Understandable limitation** — «У L статус сейчас лучше, чем у L2?» → no query →
   «Первая версия разбирает только статус одного объекта на один момент; сравнение не поддерживается.»

### Still open / caveats (v5)

* Open from before: H23 «позавчера», P02 «в прошлую пятницу», P10 non-adjacent
  negation, P05 «Был ли L готов…» (wrong unsupported; «готов ли» not added by
  instruction).
* **Inconsistency (reported, not decided):** «был 7 ноября» now asks for the time,
  while «сегодня» / «вчера» without a time still mean the whole day.
* «весь день 7 ноября» is not supported (v4 never supported it explicitly) →
  clarification; «весь день сегодня» = «сегодня».
* «будет» + past/current time → clarification is an engineering decision
  documented here; the rules did not name it.
* R1/R6 marker lists are closed lists for blocking only; unknown wordings of time
  or comparison outside them are not detected. «чем» is blocked as a comparison
  marker in any status question.
* Rules, gold and fixes have the same author; the regression set is no longer
  independent. 100 % statement/branch coverage of `core/query_parse.py`;
  coverage ≠ correctness. No claim of general "understanding".

---

# v6 — final contract C1–C6 (user decision 2026-11-09), fixed BEFORE the code change

v5 is frozen as `tests/query_parse_v5.py` (sha256
`9d87bd5d2ad8bed7682deefbf81cd570730df7b6fec486ceb29a4ad7c397f6f5` = tag
`query-parse-v5-frozen`; no tag moved). v1–v5 reports regenerate byte-identically.
No vocabulary expansion, no «готов ли L».

## Rules

* **C1** «сегодня», «вчера», a calendar date **without a time** → clarification
  asking for the time. This replaces the v1–v5 whole-day reading of «сегодня» /
  «вчера» (and resolves the v5 inconsistency).
* **C2** a day with a clock («сегодня в 08:00», «вчера в 10:00», «8 ноября в
  10:00») → a moment in the established zone: a supported zone named in the text
  (Москва / Берлин / UTC, any case), otherwise the configured default; no zone
  or an unknown zone → clarification (unchanged).
* **C3** an explicitly requested whole day → **unsupported** with the message
  that a whole-day check is not supported by the parser yet. Markers (detection
  only): `весь день` (also covers «за весь день»), `в течение … дня` (the
  existing «в течение» detection, now labelled as whole day when «дня» follows).
* **C4** a future state → unsupported (as v5, by the resolved time vs `now`).
* **C5** «будет» with a past moment → clarification (as v5, now pinned).
* **C6** no time at all → clarification; «сейчас» stays the explicit `now`.
  **Context decision:** a follow-up («А его статус?», «А L?») inheriting the time
  of the previous *parsed* turn is an existing documented v1 rule (contract table
  above: «time is inherited from that turn … no prior time → clarification»). It
  is kept, with the explanation in the output, but restricted to moments («сейчас»
  re-anchored to the new `now`, an absolute moment reused). The same holds for a
  confirmed choice answering a clarified question (v4 rule). A date-only time is
  never inherited or reused.
* **Invariant:** no `parsed` output carries a date-only `as_of`; `ask()` always
  gets a moment. The filter (#503) still supports date-only `as_of`; it is not
  touched.

## Gold versions (existing files unchanged)

* `dev_gold_v3.json`: **D07** «Какой статус L сегодня?» parsed `2026-11-09` →
  clarification (C1).
* `heldout_gold_v2.json`: **H12** «Что с L сегодня по статусу?» parsed
  `2026-11-09` → clarification (C1).
* `counterexamples_v5_gold_v2.json`: **V16** «сегодня» and **V17** «вчера»
  parsed date-only → clarification (C1); **V18** «весь день 7 ноября»
  clarification → unsupported (C3); **V19** «весь день сегодня» parsed
  `2026-11-09` → unsupported (C3).
* `independent_v4_gold_v3.json` (regression set): **I03** «Статус котельной
  сегодня?» and **I26** «А его статус сегодня?» parsed date → clarification
  (C1).
* Each change records `old_gold`, `new_gold`, `rule` and `reason` (the user's final
  contract decision of 2026-11-09, not a parser result). probes, cv2,
  cv3_gold_v2 and cv4 were reviewed and are unaffected.
* `counterexamples_v6.json`: 22 new items G01–G22.
