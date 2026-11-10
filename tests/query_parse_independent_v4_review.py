"""Hand classification of every disagreement of the frozen v4 parser with the
independent gold. Written after the run; nothing here changes the parser or the gold.
classification: parser_error | gold_contract_ambiguity."""

DISAGREEMENTS = {
    "I13": {"category": "confident_misparse", "contract_gap": False, "classification": "parser_error",
            "query_ran": True,
            "note": "«в десять утра 8 ноября»: the worded time is silently dropped and the whole day 2026-11-08 is "
                    "queried. Both the PR contract (time words → clarification) and the gold say clarification. "
                    "Same class as K18 «в половине десятого», which v3/v4 do clarify; «десять утра» is not caught."},
    "I15": {"category": "wrong_unsupported", "contract_gap": False, "classification": "gold_contract_ambiguity",
            "query_ran": False,
            "note": "«будет 12 ноября в 10:00»: the PR #14 contract table maps «будет»/future to unsupported "
                    "(forecast); the independent gold says needs_clarification. Neither runs the query; the two "
                    "contracts differ on which refusal kind a future moment gets."},
    "I20": {"category": "clarification_instead_of_unsupported", "contract_gap": False,
            "classification": "parser_error", "query_ran": False,
            "note": "«лучше, чем у L2»: comparisons are unsupported in both contracts, but the parser only detects "
                    "«сравн*»; it asks «L или L2?» instead. Safe (no query), wrong outcome kind."},
    "I19": {"category": "confident_misparse", "contract_gap": True, "classification": "gold_contract_ambiguity",
            "query_ran": True,
            "note": "«сегодня в 08:00»: parser takes the moment 2026-11-09T08:00:00+01:00, which is the alternative "
                    "the gold author names; cautious gold is clarification. The contract does not define "
                    "«сегодня» + explicit time."},
    "I30": {"category": "confident_misparse", "contract_gap": True, "classification": "gold_contract_ambiguity",
            "query_ran": True,
            "note": "«был 7 ноября» without time: the PR #14 contract (table row «8 ноября» → date-only, whole day) "
                    "gives date 2026-11-07, which is the gold author's named alternative; the independent "
                    "contract defines whole day only for «сегодня», cautious gold is clarification."},
}
