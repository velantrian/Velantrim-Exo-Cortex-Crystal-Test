"""Usefulness evaluation for core.query_parse (isolated, offline, deterministic).

Same questions, same isolated data, two conditions:
  manual -- the gold (correct) parameters passed by hand;
  parser -- parameters produced by core.query_parse.

Both go through the same ported #503 filter (core.pipeline.generate_answer).
Run:  python -m tests.query_parse_eval  [--version v1|v2] [--write]

v1 = frozen snapshot of the original parser (tests/query_parse_v1.py, byte-identical
     to core/query_parse.py at d550f3f) on the original splits dev/heldout/probes;
     --write regenerates docs/query_parse/eval_results_v1.json, demo_v1.{json,md}
     (must be byte-identical to the committed v1 report).
v2 = current core.query_parse on dev/heldout/probes + counterexamples_v2, and the
     v1 snapshot on the same items for the before -> after table;
     --write produces docs/query_parse/eval_results_v2.json, demo_v2.{json,md},
     before_after_v2.json.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from core.applicability import _parse_temporal_instant
from core.pipeline import generate_answer
import core.query_parse as parser_v2
from tests import query_parse_v1 as parser_v1

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
PARSERS = {"v1": parser_v1, "v2": parser_v2}


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


def evaluate(split, parser=parser_v2):
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


def demo(results, ids=DEMO_IDS, version="v1"):
    rows = [r for res in results for r in res["rows"] if r["id"] in ids]
    before = {}
    if version != "v1":
        before = {(b["split"], b["id"]): b["v1"] for b in before_after(results)}
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
            lines.append("- **Before (v1 snapshot, d550f3f)**: %s; %s; query %s; grounds %s; answer %r" % (
                b["category"], json.dumps(b["params"], ensure_ascii=False) if b["params"] else (b["clarification"] or b["limitation"]),
                "ran" if b["query_called"] else "not run", b["grounds_admitted"], b["grounds_answer"]))
        lines.append("")
    return rows, "\n".join(lines)


def before_after(v2_results):
    """Same items, v1 snapshot vs v2: every item whose category, parse or grounds changed."""
    out = []
    for res2 in v2_results:
        res1 = evaluate(res2["split"], parser_v1)
        for r1, r2 in zip(res1["rows"], res2["rows"]):
            assert r1["id"] == r2["id"]
            key = lambda r: (r["category"], r["parser"]["kind"], r["parser"]["params"], r["parser"]["grounds_admitted"],
                             r["parser"]["grounds_answer"], r["parser"]["clarification"], r["parser"]["limitation"])
            if key(r1) != key(r2):
                out.append({"split": res2["split"], "id": r2["id"], "question": r2["question"],
                            "context_v1": r1["context"], "context_v2": r2["context"], "gold": r2["gold"],
                            "v1": {k: r1["parser"][k] for k in ("kind", "params", "clarification", "limitation",
                                                               "grounds_admitted", "grounds_answer")}
                                  | {"category": r1["category"], "query_called": r1["parser"]["grounds_query_called"],
                                     "answers_differ_from_manual": r1["answers_differ"]},
                            "v2": {k: r2["parser"][k] for k in ("kind", "params", "clarification", "limitation",
                                                               "grounds_admitted", "grounds_answer")}
                                  | {"category": r2["category"], "query_called": r2["parser"]["grounds_query_called"],
                                     "answers_differ_from_manual": r2["answers_differ"]}})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    version = argv[argv.index("--version") + 1] if "--version" in argv else "v2"
    parser = PARSERS[version]
    splits = V1_SPLITS if version == "v1" else V2_SPLITS
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
                                   for s in V2_SPLITS if "extra_known_objects" in load_split(s)},
                   "results": results}
    (OUT / f"eval_results_{version}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n",
                                                     encoding="utf-8")
    rows, md = demo(results, DEMO_IDS if version == "v1" else DEMO_IDS_V2, version)
    (OUT / f"demo_{version}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / f"demo_{version}.md").write_text(md + "\n", encoding="utf-8")
    if version != "v1":
        (OUT / f"before_after_{version}.json").write_text(
            json.dumps(before_after(results), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
