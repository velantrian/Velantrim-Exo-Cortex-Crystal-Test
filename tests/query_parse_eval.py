"""Usefulness evaluation for core.query_parse (isolated, offline, deterministic).

Same questions, same isolated data, two conditions:
  manual -- the gold (correct) parameters passed by hand;
  parser -- parameters produced by core.query_parse.

Both go through the same ported #503 filter (core.pipeline.generate_answer).
Run:  python -m tests.query_parse_eval  [--write]
--write regenerates docs/query_parse/eval_results.json and demo.{json,md}.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from core.applicability import _parse_temporal_instant
from core.pipeline import generate_answer
from core.query_parse import ask, parse_question

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


def facts():
    return [_fact(f) for f in SETUP["facts"]]


def run_filter(question, **params):
    pack = {"facts": facts(), "query": question, "total": len(SETUP["facts"]), **params}
    return generate_answer(pack, trace=[])


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


def evaluate(split):
    items = json.loads((FIX / f"{split}.json").read_text(encoding="utf-8"))["items"]
    rows, counts = [], dict.fromkeys(CATEGORIES, 0)
    for it in items:
        tz = it["timezone"] if "timezone" in it else SETUP["timezone"]
        gold = it["gold"]
        manual = None
        if gold["kind"] == "parsed":
            manual = run_filter(it["question"], asked_object=gold["asked_object"], as_of=gold["as_of"],
                                temporal_scope="current")
        gated = ask(it["question"], SETUP["known_objects"], it.get("context"), now=NOW, timezone=tz,
                    query_fn=run_filter)
        parse = gated["parse"]
        category = classify(gold, parse)
        counts[category] += 1
        m, p = _summary(manual), _summary(gated.get("result"))
        rows.append({
            "id": it["id"], "question": it["question"], "context": it.get("context", []),
            "timezone": tz, "gold": gold, "category": category,
            "parser": {"kind": parse["kind"], "params": parse.get("params"),
                       "explanation": parse.get("explanation"),
                       "clarification": parse.get("question"), "limitation": parse.get("limitation"),
                       **{"grounds_" + k: v for k, v in p.items()}},
            "manual": {"params": ({k: gold[k] for k in ("asked_object", "as_of")} | {"temporal_scope": "current"})
                       if gold["kind"] == "parsed" else None,
                       **{"grounds_" + k: v for k, v in m.items()}},
            "answers_differ": (m["answer"], m["admitted"]) != (p["answer"], p["admitted"]),
        })
    return {"split": split, "n": len(items), "counts": counts,
            "answers_differ": [r["id"] for r in rows if r["answers_differ"]], "rows": rows}


DEMO_IDS = ("D01", "D02", "D03", "D04", "D05", "D07", "D08", "H05", "H07", "H12", "H20", "H23")


def demo(results):
    rows = [r for res in results for r in res["rows"] if r["id"] in DEMO_IDS]
    lines = ["# Query-parse demonstration (isolated data, generated)", "",
             "Generated by `python -m tests.query_parse_eval --write`. Explicit now `%s`, timezone `%s`."
             % (SETUP["now"], SETUP["timezone"]), "",
             "Path: **Question → parsed parameters → admitted grounds → answer or clarification**.", ""]
    for r in rows:
        p = r["parser"]
        lines += ["## %s — «%s»" % (r["id"], r["question"]), ""]
        if r["context"]:
            lines.append("- Context (bounded, structured): " + "; ".join(
                "«%s» → %s" % (c["question"], c.get("asked_object") or c.get("candidates")) for c in r["context"]))
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
        lines.append("")
    return rows, "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    results = [evaluate("dev"), evaluate("heldout"), evaluate("probes")]
    for res in results:
        print(res["split"], res["n"], json.dumps(res["counts"], ensure_ascii=False), "answers differ:", res["answers_differ"])
        for r in res["rows"]:
            if r["category"] not in ("correct_parse", "correct_clarification", "correct_unsupported") or r["answers_differ"]:
                print("  ", r["id"], r["category"], "differs" if r["answers_differ"] else "", r["question"],
                      r["parser"]["params"] or r["parser"]["clarification"] or r["parser"]["limitation"])
    if "--write" in argv:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "eval_results.json").write_text(json.dumps(
            {"setup": SETUP, "results": results}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        rows, md = demo(results)
        (OUT / "demo.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (OUT / "demo.md").write_text(md + "\n", encoding="utf-8")
    return results


if __name__ == "__main__":
    main()
