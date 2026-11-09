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
PARSERS = {"v1": parser_v1, "v2": parser_v2_frozen, "v3": parser_v3_frozen, "v4": parser_current}
SPLITS = {"v1": V1_SPLITS, "v2": V2_SPLITS, "v3": V3_SPLITS, "v4": V4_SPLITS}
PREVIOUS = {"v2": "v1", "v3": "v2", "v4": "v3"}
PREV_LABEL = {"v2": "v1 snapshot, d550f3f", "v3": "v2 snapshot, eee4062", "v4": "v3 snapshot, a6d11f3"}


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
DEMO_IDS_BY = {"v1": DEMO_IDS, "v2": DEMO_IDS_V2, "v3": DEMO_IDS_V3, "v4": DEMO_IDS_V4}


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
    version = argv[argv.index("--version") + 1] if "--version" in argv else "v4"
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
    (OUT / f"eval_results_{version}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
    rows, md = demo(results, DEMO_IDS_BY[version], version)
    (OUT / f"demo_{version}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / f"demo_{version}.md").write_text(md + "\n", encoding="utf-8")
    if version != "v1":
        (OUT / f"before_after_{version}.json").write_text(
            json.dumps(before_after(results, version), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if version in ("v3", "v4"):
        prev = "v2" if version == "v3" else "v3"
        perm = {"_note": "decision (kind, params, candidates, clarification/limitation text, mentioned_objects) for every "
                         "permutation of the split's catalogue x {names as given, names reversed}; 'changed' lists items "
                         "whose decision differs between catalogue orders",
                prev: [permutation_check(PARSERS[prev], s) for s in SPLITS[version]],
                version: [permutation_check(PARSERS[version], s) for s in SPLITS[version]]}
        (OUT / f"permutation_invariance_{version}.json").write_text(json.dumps(perm, ensure_ascii=False, indent=1) + "\n",
                                                           encoding="utf-8")



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
