"""Aggregate question scores into counts (plan 6.2-6.3) and write the Markdown report.

Everything is a count, "k of n", never a bare percentage: n is about 20 per split, so a
percentage would suggest precision the numbers do not have. Dev and test are never pooled.
"""
from erp.eval.score import QuestionScore


def frac(k: int, n: int) -> dict:
    return {"k": int(k), "n": int(n), "text": f"{int(k)} of {int(n)}"}


def _frac_or_none(k, n):
    return frac(k, n) if n else None


def summarize(scores: list[QuestionScore]) -> dict:
    gold_q = [s for s in scores if s.has_gold_value]
    routed = [s for s in scores if s.routing_tools_ok is not None]
    verified = [s for s in scores if s.verifier_ran]
    g = [s for s in scores if s.category == "G"]
    expect_answer = [s for s in scores if s.expected_behavior == "answer"]

    def by_cat(cat):
        c = [s for s in scores if s.category == cat]
        cg = [s for s in c if s.has_gold_value]
        cr = [s for s in c if s.routing_tools_ok is not None]
        return {"questions": len(c),
                "numeric_accuracy": _frac_or_none(sum(s.numeric_correct for s in cg), len(cg)),
                "citation_numeric": _frac_or_none(sum(s.gold_citing_claims for s in c),
                                                  sum(s.numeric_claims_in_scope for s in c)),
                "behavior": frac(sum(s.behavior_ok for s in c), len(c)),
                "routing_tools": _frac_or_none(sum(s.routing_tools_ok for s in cr), len(cr)),
                "unsupported_claims": frac(sum(s.unsupported_claims for s in c), sum(s.numeric_claims for s in c))}

    return {
        "questions": len(scores),
        "headline": {
            "numeric_accuracy": frac(sum(s.numeric_correct for s in gold_q), len(gold_q)),
            "citation_numeric": frac(sum(s.gold_citing_claims for s in scores),
                                     sum(s.numeric_claims_in_scope for s in scores)),
            "citation_numeric_gold_claims": frac(sum(s.gold_claims_citing for s in scores),
                                                 sum(s.gold_claims for s in scores)),
        },
        "secondary": {
            "routing_tools": _frac_or_none(sum(s.routing_tools_ok for s in routed), len(routed)),
            "routing_tools_period": _frac_or_none(sum(s.routing_period_ok for s in routed), len(routed)),
            "refusal_G": frac(sum(s.behavior_ok for s in g), len(g)),
            "behavior_all": frac(sum(s.behavior_ok for s in scores), len(scores)),
            "over_refusal": frac(sum(s.behavior in ("refuse", "not_available") for s in expect_answer),
                                 len(expect_answer)),
            "unsupported_claims": frac(sum(s.unsupported_claims for s in scores),
                                       sum(s.numeric_claims for s in scores)),
            "verifier_rejections": _frac_or_none(sum(s.verifier_rejected for s in verified), len(verified)),
            "verifier_would_reject": _frac_or_none(sum(s.verifier_would_reject for s in verified), len(verified)),
            "advice_language": frac(sum(bool(s.advice_language) for s in scores), len(scores)),
            "errors": frac(sum(s.behavior == "error" for s in scores), len(scores)),
        },
        "by_category": {cat: by_cat(cat) for cat in sorted({s.category for s in scores})},
        "failures": {
            "numeric": [s.id for s in gold_q if not s.numeric_correct],
            "behavior": [f"{s.id} (expected {s.expected_behavior}, got {s.behavior})" for s in scores
                         if not s.behavior_ok],
            "routing": [s.id for s in routed if not s.routing_period_ok],
            "unsupported_claims": [s.id for s in scores if s.unsupported_claims],
            "verifier_would_reject": [s.id for s in scores if s.verifier_would_reject],
            "advice_language": [f"{s.id} {s.advice_language}" for s in scores if s.advice_language],
            "expected_failures": [s.id for s in scores if s.expected_failure],
        },
    }


HEADLINE_ROWS = [
    ("headline", "numeric_accuracy", "Numeric accuracy (questions with a gold value: a claim matches value, unit, period)"),
    ("headline", "citation_numeric", "Citation correctness, numeric (all numeric claims citing a gold page)"),
    ("headline", "citation_numeric_gold_claims", "Citation correctness, numeric (gold-matching claims citing a gold page)"),
    ("secondary", "routing_tools", "Routing: right tools"),
    ("secondary", "routing_tools_period", "Routing: right tools and period"),
    ("secondary", "refusal_G", "Refusal correctness (category G)"),
    ("secondary", "behavior_all", "Behaviour correct (all questions)"),
    ("secondary", "over_refusal", "Over-refusal (expected an answer, declined)"),
    ("secondary", "unsupported_claims", "Unsupported numeric claims (no evidence)"),
    ("secondary", "verifier_rejections", "Verifier rejections (template shipped)"),
    ("secondary", "verifier_would_reject", "Verifier would reject (report recorded)"),
    ("secondary", "advice_language", "Answers with advice/verdict words"),
    ("secondary", "errors", "Harness errors (LLM or embedding call failed)"),
]

CAT_COLUMNS = [("numeric_accuracy", "Numeric correct"), ("citation_numeric", "Numeric claims citing gold page"),
               ("behavior", "Behaviour correct"), ("routing_tools", "Routing (tools)"),
               ("unsupported_claims", "Unsupported claims")]


def _cell(x):
    return x["text"] if x else "n/a"


def render_report(meta: dict, metrics: dict[str, dict], descriptions: dict[str, str]) -> str:
    systems = list(metrics)
    lines = [f"# Eval results: {meta['split']} split", "",
             "Counts, not percentages. Not investment advice; DCF figures are what the stated assumptions imply.", "",
             "| Run | |", "|---|---|"]
    for key in ("timestamp", "git_sha", "model", "models_reported", "split", "questions_sha256", "dcf_assumptions_sha256",
                "facts_unverified", "gold_pending_author_check", "rescored_at"):
        if meta.get(key) is not None:
            lines.append(f"| {key} | {meta[key]} |")
    lines += ["", "## Systems", ""] + [f"- **{s}**: {descriptions.get(s, '')}" for s in systems]
    lines += ["", "## Headline and secondary metrics", "",
              "| Metric | " + " | ".join(systems) + " |", "|---|" + "---|" * len(systems)]
    for group, key, label in HEADLINE_ROWS:
        lines.append(f"| {label} | " + " | ".join(_cell(metrics[s][group][key]) for s in systems) + " |")
    lines += ["", "Qualitative citation correctness is labelled by hand: run `eval/sample_qualitative.py` on this "
              "run folder, fill the `supports` column, then `--tally` the CSV.", ""]
    for s in systems:
        lines += [f"## Per category: {s}", "",
                  "| Category | Questions | " + " | ".join(label for _, label in CAT_COLUMNS) + " |",
                  "|---|---|" + "---|" * len(CAT_COLUMNS)]
        for cat, row in metrics[s]["by_category"].items():
            lines.append(f"| {cat} | {row['questions']} | " + " | ".join(_cell(row[k]) for k, _ in CAT_COLUMNS) + " |")
        lines.append("")
    expected = metrics[systems[0]]["failures"]["expected_failures"] if systems else []
    lines += ["## Known expected failures", "",
              "Unit-conversion questions (category B, gold in INR million or INR lakh crore): no tool converts "
              "units, and the LLM may not do arithmetic, so these are reported as failures by design "
              f"(no conversion tool in M7): {', '.join(expected) or 'none in this split'}.", ""]
    for s in systems:
        f = metrics[s]["failures"]
        lines += [f"## Failures: {s}", ""]
        for key in ("numeric", "behavior", "routing", "unsupported_claims", "verifier_would_reject", "advice_language"):
            lines.append(f"- {key}: {', '.join(f[key]) or 'none'}")
        lines.append("")
    return "\n".join(lines)
