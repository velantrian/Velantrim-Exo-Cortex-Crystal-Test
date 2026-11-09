"""Usefulness evaluation for core.query_parse (isolated, offline, deterministic).

Same questions, same isolated data, two conditions:
  manual -- the gold (correct) parameters passed by hand;
  parser -- parameters produced by core.query_parse.

Both go through the same ported #503 filter (core.pipeline.generate_answer).
Run:  python -m tests.query_parse_eval  [--version v1|v2|v3|v4] [--write]   (default v4)

v1 = frozen snapshot of the original parser (tests/query_parse_v1.py, byte-identical
     to core/query_parse.py at d550f3f) on the original splits dev/heldout/probes;
     --write regenerates docs/query_parse/eval_results_v1.json, demo_v1.{json,md}
     (must be byte-identical to the committed v1 report).
v2 = frozen snapshot tests/query_parse_v2.py (byte-identical to core/query_parse.py
     at eee4062) on dev/heldout/probes + counterexamples_v2, v1 snapshot for the
     before -> after table; --write regenerates eval_results_v2.json, demo_v2.*,
     before_after_v2.json (must be byte-identical to the committed v2 report).
v3 = frozen snapshot tests/query_parse_v3.py (byte-identical to core/query_parse.py
     at a6d11f3) on all v3 splits, v2 snapshot for before -> after; --write
     regenerates the v3 report byte-identically (eval_results_v3.json, demo_v3.*,
     before_after_v3.json, permutation_invariance_v3.json).
v4 = current core.query_parse on all splits; counterexamples_v3 is scored against
     the NEW gold version counterexamples_v3_gold_v2 (old gold file unchanged) and
     the new counterexamples_v4; v3 snapshot for before -> after; --write produces
     eval_results_v4.json, demo_v4.*, before_after_v4.json, permutation_invariance_v4.json.
     Since v5 the v4 parser is the frozen snapshot tests/query_parse_v4.py (= tag
     query-parse-v4-frozen); the v4 report regenerates byte-identically.
v6 = current core.query_parse (final contract C1-C6, 2026-11-09) on the latest gold
     versions (dev_gold_v3, heldout_gold_v2, probes, cv2, cv3_gold_v2, cv4,
     counterexamples_v5_gold_v2, counterexamples_v6); v5 frozen snapshot for before
     -> after; --write: eval_results_v6.json, demo_v6.*, before_after_v6.json,
     permutation_invariance_v6.json.
v5 = core.query_parse at tag query-parse-v5-frozen, now tests/query_parse_v5.py (rules R1-R6, 2026-11-09) on dev_gold_v2 (dev.json
     unchanged), heldout, probes, cv2, cv3_gold_v2, cv4 and counterexamples_v5; v4
     snapshot for before -> after; --write produces eval_results_v5.json (with the
     v4 snapshot on the v5 sets), demo_v5.* (exactly three outcomes),
     before_after_v5.json, permutation_invariance_v5.json, morning_evening_v5.*.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from core.applicability import _parse_temporal_instant
from core.pipeline import generate_answer
import core.query_parse as parser_current
from tests import query_parse_v1 as parser_v1
from tests import query_parse_v2 as parser_v2_frozen
from tests import query_parse_v3 as parser_v3_frozen
from tests import query_parse_v4 as parser_v4_frozen
from tests import query_parse_v5 as parser_v5_frozen
from tests import query_parse_v6 as parser_v6_frozen

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "query_parse"
OUT = ROOT / "docs" / "query_parse"
SETUP = json.loads((FIX / "setup.json").read_text(encoding="utf-8"))
NOW = datetime.fromisoformat(SETUP["now"])


def _fact(f):
    return {"fact_id": f["fact_id"], "claim": f["claim"], "source": "isolated-synthetic:" + f["fact_id"],
            "claim_type": "WORLD_FACT", "source_status": "EXTERNAL", "truth_status": "VERIFIED",
            "epistemic_state": "Validated", "confidence": 1.0, "restricted": False,
            "metadata": {"applicability": dict(f["applicability"])}}


V1_SPLITS = ("dev", "heldout", "probes")
V2_SPLITS = V1_SPLITS + ("counterexamples_v2",)
V3_SPLITS = V2_SPLITS + ("counterexamples_v3",)
V4_SPLITS = V2_SPLITS + ("counterexamples_v3_gold_v2", "counterexamples_v4")
V6_SPLITS = ("dev_gold_v3", "heldout_gold_v2", "probes", "counterexamples_v2", "counterexamples_v3_gold_v2",
             "counterexamples_v4", "counterexamples_v5_gold_v2", "counterexamples_v6")
V5_SPLITS = ("dev_gold_v2", "heldout", "probes", "counterexamples_v2", "counterexamples_v3_gold_v2", "counterexamples_v4",
             "counterexamples_v5")
PARSERS = {"v1": parser_v1, "v2": parser_v2_frozen, "v3": parser_v3_frozen, "v4": parser_v4_frozen,
           "v5": parser_v5_frozen, "v6": parser_v6_frozen, "v6_1": parser_current}
SPLITS = {"v1": V1_SPLITS, "v2": V2_SPLITS, "v3": V3_SPLITS, "v4": V4_SPLITS, "v5": V5_SPLITS, "v6": V6_SPLITS}
PREVIOUS = {"v2": "v1", "v3": "v2", "v4": "v3", "v5": "v4", "v6": "v5"}
PREV_LABEL = {"v2": "v1 snapshot, d550f3f", "v3": "v2 snapshot, eee4062", "v4": "v3 snapshot, a6d11f3",
              "v5": "v4 snapshot, tag query-parse-v4-frozen", "v6": "v5 snapshot, tag query-parse-v5-frozen"}


def load_split(split):
    return json.loads((FIX / f"{split}.json").read_text(encoding="utf-8"))


def split_objects(data):
    return SETUP["known_objects"] + data.get("extra_known_objects", [])


def facts(extra=()):
    return [_fact(f) for f in list(SETUP["facts"]) + list(extra)]


def make_filter(extra=()):
    def run(question, **params):
        fs = facts(extra)
        return generate_answer({"facts": fs, "query": question, "total": len(fs), **params}, trace=[])
    return run


run_filter = make_filter()


def build_context(parser, it, objects, tz):
    """Explicit context from the fixture, or built by running ``parser`` on context_questions."""
    if "context_questions" not in it:
        return it.get("context")
    ctx = []
    for q in it["context_questions"]:
        ctx.append(parser.context_turn(q, parser.parse_question(q, objects, ctx, now=NOW, timezone=tz)))
    return ctx


def _summary(result):
    if result is None:
        return {"query_called": False, "admitted": [], "answer": None}
    app = result.get("applicability") or {}
    return {"query_called": True, "admitted": [f["fact_id"] for f in result.get("facts", [])],
            "answer": result.get("answer"), "error": result.get("error"),
            "historical_only": [h["fact_id"] for h in app.get("historical_facts", [])],
            "uncertainty": result.get("uncertainty")}


def _same_instant(a, b):
    pa, pb = _parse_temporal_instant(a), _parse_temporal_instant(b)
    return pa is not None and pb is not None and pa[0] == pb[0] and (
        pa[1] == pb[1] if pa[0] == "date" else pa[1].astimezone().timestamp() == pb[1].astimezone().timestamp())


def classify(gold, parse):
    g, p = gold["kind"], parse["kind"]
    if g == "parsed" and p == "parsed":
        ok = (parse["params"]["asked_object"] == gold["asked_object"]
              and _same_instant(parse["params"]["as_of"], gold["as_of"]))
        return "correct_parse" if ok else "confident_misparse"
    if p == "parsed":
        return "confident_misparse"  # parsed although the gold says it must not run
    if g == p == "needs_clarification":
        return "correct_clarification"
    if g == p == "unsupported":
        return "correct_unsupported"
    if p == "needs_clarification":
        return "unnecessary_clarification" if g == "parsed" else "clarification_instead_of_unsupported"
    return "wrong_unsupported"


CATEGORIES = ("correct_parse", "confident_misparse", "correct_clarification", "unnecessary_clarification",
              "correct_unsupported", "wrong_unsupported", "clarification_instead_of_unsupported")


def evaluate(split, parser=parser_current):
    data = load_split(split)
    items = data["items"]
    objects = split_objects(data)
    run = make_filter(data.get("extra_facts", ()))
    rows, counts = [], dict.fromkeys(CATEGORIES, 0)
    for it in items:
        tz = it["timezone"] if "timezone" in it else SETUP["timezone"]
        gold = it["gold"]
        manual = None
        if gold["kind"] == "parsed":
            manual = run(it["question"], asked_object=gold["asked_object"], as_of=gold["as_of"],
                         temporal_scope="current")
        context = build_context(parser, it, objects, tz)
        gated = parser.ask(it["question"], objects, context, now=NOW, timezone=tz, query_fn=run)
        parse = gated["parse"]
        category = classify(gold, parse)
        counts[category] += 1
        m, p = _summary(manual), _summary(gated.get("result"))
        row = {
            "id": it["id"], "question": it["question"], "context": context or [],
            "timezone": tz, "gold": gold, "category": category,
            "parser": {"kind": parse["kind"], "params": parse.get("params"),
                       "explanation": parse.get("explanation"),
                       "clarification": parse.get("question"), "limitation": parse.get("limitation"),
                       **{"grounds_" + k: v for k, v in p.items()}},
            "manual": {"params": ({k: gold[k] for k in ("asked_object", "as_of")} | {"temporal_scope": "current"})
                       if gold["kind"] == "parsed" else None,
                       **{"grounds_" + k: v for k, v in m.items()}},
            "answers_differ": (m["answer"], m["admitted"]) != (p["answer"], p["admitted"]),
        }
        if "context_questions" in it:
            row["context_questions"] = it["context_questions"]
        if "group" in it:
            row["group"] = it["group"]
        rows.append(row)
    return {"split": split, "n": len(items), "counts": counts,
            "answers_differ": [r["id"] for r in rows if r["answers_differ"]], "rows": rows}


DEMO_IDS = ("D01", "D02", "D03", "D04", "D05", "D07", "D08", "H05", "H07", "H12", "H20", "H23")


DEMO_IDS_V2 = DEMO_IDS + ("P01", "P09", "C01", "C02", "C03", "C05", "C09", "C12", "C13", "C14", "C17", "C20")
DEMO_IDS_V3 = DEMO_IDS_V2 + ("K01", "K02", "K04", "K07", "K09", "K10", "K11", "K13", "K16", "K17", "K18",
                             "K20", "K21", "K22")
DEMO_IDS_V4 = DEMO_IDS_V3 + ("E01", "E03", "E05", "E06", "F01", "F02", "F04", "F05", "F07", "F09", "F10", "F13")
# v5: exactly three outcomes through the full path
DEMO_V5 = (("V34", "Outcome 1 — correct answer"), ("V01", "Outcome 2 — useful clarification (no query)"),
           ("V28", "Outcome 3 — understandable limitation (unsupported, no query)"))
DEMO_V6 = (("G04", "Outcome 1 — correct answer"), ("G01", "Outcome 2 — useful clarification (no query)"),
           ("G08", "Outcome 3 — understandable limitation (unsupported, no query)"))
DEMO_SPEC = {"v5": DEMO_V5, "v6": DEMO_V6}
DEMO_IDS_BY = {"v1": DEMO_IDS, "v2": DEMO_IDS_V2, "v3": DEMO_IDS_V3, "v4": DEMO_IDS_V4,
               "v5": tuple(i for i, _ in DEMO_V5), "v6": tuple(i for i, _ in DEMO_V6)}


def demo(results, ids=DEMO_IDS, version="v1"):
    rows = [r for res in results for r in res["rows"] if r["id"] in ids]
    before = {}
    if version != "v1":
        before = {(b["split"], b["id"]): b[PREVIOUS[version]] for b in before_after(results, version)}
        split_of = {r["id"]: res["split"] for res in results for r in res["rows"]}
    title = "# Query-parse demonstration (isolated data, generated)" if version == "v1" else \
        "# Query-parse demonstration %s (isolated data, generated)" % version
    cmd = "`python -m tests.query_parse_eval --write`" if version == "v1" else \
        "`python -m tests.query_parse_eval --version %s --write`" % version
    lines = [title, "",
             "Generated by %s. Explicit now `%s`, timezone `%s`." % (cmd, SETUP["now"], SETUP["timezone"]), "",
             "Path: **Question → parsed parameters → admitted grounds → answer or clarification**.", ""]
    for r in rows:
        p = r["parser"]
        lines += ["## %s — «%s»" % (r["id"], r["question"]), ""]
        if r["context"]:
            lines.append("- Context (bounded, structured): " + "; ".join(
                "«%s» → %s" % (c["question"], c.get("asked_object") or c.get("candidates") or (
                    "%s; mentioned %s" % (c["kind"], c["mentioned_objects"]) if c.get("mentioned_objects") else None))
                for c in r["context"]))
        lines.append("- Parse: `%s`" % p["kind"])
        if p["params"]:
            lines.append("- Parameters: `%s`" % json.dumps(p["params"], ensure_ascii=False))
            for k, v in (p["explanation"] or {}).items():
                lines.append("  - %s: %s" % (k, v))
            lines.append("- Admitted grounds: %s" % (", ".join(p["grounds_admitted"]) or "none"))
            if p["grounds_historical_only"]:
                lines.append("- Historical only (not grounds, not attested): %s" % ", ".join(p["grounds_historical_only"]))
            lines.append("- Answer: %s" % (p["grounds_answer"] if p["grounds_answer"] is not None
                                            else "none — " + str(p["grounds_error"])))
        else:
            lines.append("- No query was run.")
            lines.append("- %s: %s" % ("Clarification" if p["clarification"] else "Limitation",
                                       p["clarification"] or p["limitation"]))
        lines.append("- Manual-parameter condition: %s" % (
            "no correct parameters without asking the user; no query (gold: %s)" % r["gold"]["kind"]
            if r["manual"]["params"] is None else
            "same answer and grounds" if not r["answers_differ"] else
            "DIFFERENT — manual answer %r, grounds %s" % (r["manual"]["grounds_answer"], r["manual"]["grounds_admitted"])))
        b = before.get((split_of[r["id"]], r["id"])) if before else None
        if b:
            lines.append("- **Before (%s)**: %s; %s; query %s; grounds %s; answer %r" % (
                PREV_LABEL[version], b["category"], json.dumps(b["params"], ensure_ascii=False) if b["params"] else (b["clarification"] or b["limitation"]),
                "ran" if b["query_called"] else "not run", b["grounds_admitted"], b["grounds_answer"]))
        lines.append("")
    return rows, "\n".join(lines)


def before_after(v2_results, version="v2"):
    """Same items, previous snapshot vs ``version``: every item whose category, parse or grounds changed."""
    old, new = PREVIOUS[version], version
    out = []
    for res2 in v2_results:
        res1 = evaluate(res2["split"], PARSERS[old])
        for r1, r2 in zip(res1["rows"], res2["rows"]):
            assert r1["id"] == r2["id"]
            key = lambda r: (r["category"], r["parser"]["kind"], r["parser"]["params"], r["parser"]["grounds_admitted"],
                             r["parser"]["grounds_answer"], r["parser"]["clarification"], r["parser"]["limitation"])
            if key(r1) != key(r2):
                out.append({"split": res2["split"], "id": r2["id"], "question": r2["question"],
                            "context_" + old: r1["context"], "context_" + new: r2["context"], "gold": r2["gold"],
                            old: {k: r1["parser"][k] for k in ("kind", "params", "clarification", "limitation",
                                                               "grounds_admitted", "grounds_answer")}
                                  | {"category": r1["category"], "query_called": r1["parser"]["grounds_query_called"],
                                     "answers_differ_from_manual": r1["answers_differ"]},
                            new: {k: r2["parser"][k] for k in ("kind", "params", "clarification", "limitation",
                                                               "grounds_admitted", "grounds_answer")}
                                  | {"category": r2["category"], "query_called": r2["parser"]["grounds_query_called"],
                                     "answers_differ_from_manual": r2["answers_differ"]}})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    version = argv[argv.index("--version") + 1] if "--version" in argv else "v6"
    parser = PARSERS[version]
    splits = SPLITS[version]
    results = [evaluate(s, parser) for s in splits]
    for res in results:
        print(res["split"], res["n"], json.dumps(res["counts"], ensure_ascii=False), "answers differ:", res["answers_differ"])
        for r in res["rows"]:
            if r["category"] not in ("correct_parse", "correct_clarification", "correct_unsupported") or r["answers_differ"]:
                print("  ", r["id"], r["category"], "differs" if r["answers_differ"] else "", r["question"],
                      r["parser"]["params"] or r["parser"]["clarification"] or r["parser"]["limitation"])
    if "--write" in argv:
        write(results, version)
    return results


def write(results, version):
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"setup": SETUP, "results": results}
    if version != "v1":
        payload = {"version": version, "parser": "core/query_parse.py", "setup": SETUP,
                   "extra_setup": {s: {k: load_split(s).get(k, []) for k in ("extra_known_objects", "extra_facts")}
                                   for s in SPLITS[version] if "extra_known_objects" in load_split(s)},
                   "results": results}
    if version == "v4":
        prev = [evaluate(s, PARSERS["v3"]) for s in SPLITS["v4"]]
        payload["v3_snapshot_on_v4_sets"] = {
            "_note": "frozen v3 parser (tests/query_parse_v3.py) scored on the v4 sets. counterexamples_v3_gold_v2 is "
                     "the same 23 questions as counterexamples_v3 with K20 relabelled by the user's rule change "
                     "(2026-11-09); the v3 report's 0 confident misparse on counterexamples_v3 refers to the old gold.",
            "results": [{"split": r["split"], "n": r["n"], "counts": r["counts"], "answers_differ": r["answers_differ"],
                         "not_correct": [x["id"] for x in r["rows"] if not x["category"].startswith("correct")]}
                        for r in prev]}
    if version == "v6":
        prev = [evaluate(s, PARSERS["v5"]) for s in SPLITS["v6"]]
        payload["v5_snapshot_on_v6_sets"] = {
            "_note": "frozen v5 parser (tests/query_parse_v5.py, = tag query-parse-v5-frozen) scored on the v6 sets "
                     "(latest gold versions; gold changes = user's final contract decision 2026-11-09, C1-C6).",
            "results": [{"split": r["split"], "n": r["n"], "counts": r["counts"], "answers_differ": r["answers_differ"],
                         "not_correct": [x["id"] for x in r["rows"] if not x["category"].startswith("correct")]}
                        for r in prev]}
    if version == "v5":
        prev = [evaluate(s, PARSERS["v4"]) for s in SPLITS["v5"]]
        payload["v4_snapshot_on_v5_sets"] = {
            "_note": "frozen v4 parser (tests/query_parse_v4.py, = tag query-parse-v4-frozen) scored on the v5 sets. "
                     "dev_gold_v2 is dev.json with D15/D23 relabelled by the user/Astra decision of 2026-11-09 "
                     "(rules R1-R6); the v4 report's numbers on dev refer to the old gold.",
            "results": [{"split": r["split"], "n": r["n"], "counts": r["counts"], "answers_differ": r["answers_differ"],
                         "not_correct": [x["id"] for x in r["rows"] if not x["category"].startswith("correct")]}
                        for r in prev]}
    (OUT / f"eval_results_{version}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
    rows, md = demo(results, DEMO_IDS_BY[version], version)
    if version in DEMO_SPEC:
        rows, md = demo_v5(rows, md, DEMO_SPEC[version], PARSERS[version])
    (OUT / f"demo_{version}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / f"demo_{version}.md").write_text(md + "\n", encoding="utf-8")
    if version != "v1":
        (OUT / f"before_after_{version}.json").write_text(
            json.dumps(before_after(results, version), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if version in ("v3", "v4", "v5", "v6"):
        prev = PREVIOUS[version]
        perm = {"_note": "decision (kind, params, candidates, clarification/limitation text, mentioned_objects) for every "
                         "permutation of the split's catalogue x {names as given, names reversed}; 'changed' lists items "
                         "whose decision differs between catalogue orders",
                prev: [permutation_check(PARSERS[prev], s) for s in SPLITS[version]],
                version: [permutation_check(PARSERS[version], s) for s in SPLITS[version]]}
        (OUT / f"permutation_invariance_{version}.json").write_text(json.dumps(perm, ensure_ascii=False, indent=1) + "\n",
                                                           encoding="utf-8")
    if version == "v5":
        me = morning_evening()
        (OUT / "morning_evening_v5.json").write_text(json.dumps(me, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (OUT / "morning_evening_v5.md").write_text(morning_evening_md(me) + "\n", encoding="utf-8")


def demo_v5(rows, md, spec=DEMO_V5, parser=None):
    """Exactly three outcomes in a fixed order; the answer carries its receipt (citations). Used for v5 and v6."""
    from core import provenance
    parser = parser or PARSERS["v5"]
    order = [i for i, _ in spec]
    rows = sorted(rows, key=lambda r: order.index(r["id"]))
    head, *sections = md.split("\n## ")
    by_id = {sec.split(" — ", 1)[0]: sec for sec in sections}
    out = [head.replace("Path: **", "Exactly three outcomes. Path: **")]
    for i, label in spec:
        sec = "%s: %s" % (label, by_id[i])
        row = next(r for r in rows if r["id"] == i)
        if row["parser"]["kind"] == "parsed":
            g = parser.ask(row["question"], SETUP["known_objects"], None, now=NOW, timezone=SETUP["timezone"],
                                  query_fn=run_filter)
            rec = provenance.build_receipt(g["result"])
            row["receipt"] = {"answer": rec["answer"], "citations": [c["fact_id"] for c in rec["citations"]]}
            sec = sec.replace("\n- Manual-parameter condition", "\n- Receipt: answer %r, citations %s\n- Manual-parameter condition"
                              % (rec["answer"], ", ".join(row["receipt"]["citations"])))
        out.append(sec)
    return rows, "\n## ".join(out)


# ── v5: losing the time changes the answer (isolated setup facts for L) ─────

MORNING_EVENING = (("V01", "10:00"), ("V05", "09:00 or 21:00"), ("V06", "18:00"))
MANUAL_MOMENTS = ("2026-11-08T09:00:00+01:00", "2026-11-08T10:00:00+01:00", "2026-11-08T18:00:00+01:00",
                  "2026-11-08T21:00:00+01:00")


def morning_evening():
    items = {it["id"]: it for it in load_split("counterexamples_v5")["items"]}
    objects, tz = split_objects({}), SETUP["timezone"]

    def side(parser, q):
        g = parser.ask(q, objects, None, now=NOW, timezone=tz, query_fn=run_filter)
        p, res = g["parse"], _summary(g.get("result"))
        return {"kind": p["kind"], "params": p.get("params"), "clarification": p.get("question"),
                "limitation": p.get("limitation"), "query_called": g["query_called"],
                "grounds_admitted": res["admitted"], "answer": res["answer"], "error": res.get("error")}

    manual = []
    for at in MANUAL_MOMENTS:
        res = _summary(run_filter("manual", asked_object="L", as_of=at, temporal_scope="current"))
        manual.append({"as_of": at, "grounds_admitted": res["admitted"], "answer": res["answer"], "error": res.get("error")})
    return {"_note": "Setup facts: L «на ремонте» valid until 2026-11-08T11:59:59+01:00, L «готов» from "
                     "2026-11-08T12:00:00+01:00. Manual rows use hand-set parameters with the same filter.",
            "manual": manual,
            "items": [{"id": i, "question": items[i]["question"], "intended_time": intended,
                       "v4": side(PARSERS["v4"], items[i]["question"]), "v5": side(PARSERS["v5"], items[i]["question"])}
                      for i, intended in MORNING_EVENING]}


def morning_evening_md(me):
    def show(x):
        if x["query_called"]:
            return "parsed `%s` → query ran → grounds %s → answer: %s" % (
                json.dumps(x["params"], ensure_ascii=False), x["grounds_admitted"] or "none",
                x["answer"] if x["answer"] is not None else "none — %s" % x["error"])
        return "%s, **no query**: %s" % (x["kind"], x["clarification"] or x["limitation"])
    lines = ["# Morning vs evening: losing the time changes the answer (v4 → v5, generated)", "",
             "Generated by `python -m tests.query_parse_eval --version v5 --write`. " + me["_note"], "",
             "| manual as_of | admitted grounds | answer |", "|---|---|---|"]
    lines += ["| `%s` | %s | %s |" % (m["as_of"], ", ".join(m["grounds_admitted"]) or "none",
                                        m["answer"] if m["answer"] is not None else "none — %s" % m["error"])
              for m in me["manual"]]
    for it in me["items"]:
        lines += ["", "## %s — «%s» (intended %s)" % (it["id"], it["question"], it["intended_time"]), "",
                  "- **v4** (frozen): " + show(it["v4"]), "- **v5**: " + show(it["v5"])]
    return "\n".join(lines)



# ── catalogue-order invariance (stdlib itertools only) ─────────────────────

def catalogue_variants(objects, full=True):
    """Every permutation of the catalogue (full) or all rotations (cheap), each
    with names in given and in reversed order."""
    import itertools
    n = len(objects)
    orders = itertools.permutations(range(n)) if full else (tuple((i + k) % n for i in range(n)) for k in range(n))
    for order in orders:
        for rev in (False, True):
            yield [dict(objects[i], names=list(reversed(objects[i].get("names", []))) if rev
                        else list(objects[i].get("names", []))) for i in order]


def decision(result):
    """Order-sensitive parts of a parse result that must not depend on the catalogue order."""
    return (result["kind"], json.dumps(result.get("params"), sort_keys=True), tuple(sorted(result.get("candidates", []))),
            result.get("question"), result.get("limitation"), tuple(result.get("mentioned_objects", [])))


def permutation_check(parser, split, full=True):
    """Return {'items': n, 'variants': k, 'changed': [ids whose decision differs across catalogue orders]}."""
    data = load_split(split)
    base_objects = split_objects(data)
    changed, variants = [], 0
    for it in data["items"]:
        tz = it["timezone"] if "timezone" in it else SETUP["timezone"]
        seen = set()
        for objects in catalogue_variants(base_objects, full):
            ctx = build_context(parser, it, objects, tz)
            seen.add(decision(parser.parse_question(it["question"], objects, ctx, now=NOW, timezone=tz)))
            variants += 1
        if len(seen) > 1:
            changed.append(it["id"])
    return {"split": split, "items": len(data["items"]), "variants": variants, "changed": changed}


if __name__ == "__main__":
    main()
