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
