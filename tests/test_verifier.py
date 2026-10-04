"""M6: the answer verifier (deterministic, no LLM).

Tool results come from the real tool layer on the sample facts (INR crore): revenue FY26 267,021,
FY25 255,324; profit attributable to owners FY26 49,210, FY25 48,553. Net margin FY26 18.43%
(49210 / 267021 x 100 = 18.4293), FY25 19.02% (48553 / 255324 x 100 = 19.0162). Revenue growth
FY26 4.58% ((267021 - 255324) / 255324 x 100 = 4.5813).
DCF: the TOY fixture (not TCS): WACC 12.00%, terminal growth 4.00%, 229.32 per share; the
sensitivity grid adds -1, -0.5, 0, +0.5, +1 points to each (config/dcf.yaml).
"""
import pytest

from erp.agent.llm import load_agent_config
from erp.agent.tools import ToolCall, ToolEnv, run_tool
from erp.agent.verifier import verify_answer
from erp.ingest.index_chroma import add_chunks, open_collection
from fakes import fake_embed
from test_agent_tools import CHUNKS, DISPLAY
from test_dcf_run import TOY_YAML

CFG = load_agent_config()


@pytest.fixture
def env(loaded, tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, collection=col, embed_fn=fake_embed,
                   dcf_assumptions=TOY_YAML)


def run(env, tool, **args):
    r = run_tool(ToolCall(tool=tool, args=args), env)
    assert r.ok, r.error
    return r


def fact(env, metric, period):
    return run(env, "get_financial_fact", metric_id=metric, period=period)


def ratio(env, ratio_id, period):
    return run(env, "compute_ratio", ratio_id=ratio_id, period=period)


def toy_dcf(env, sensitivity=False):
    env.conn.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    env.ticker = "TOY"
    return run(env, "run_dcf", scenario="base", include_sensitivity=sensitivity)


def eid(result, i=0):
    return result.numbers[i].evidence_id


def verify(text, results, **kw):
    return verify_answer(text, results, cfg=CFG, **kw)


def checks(report, severity="error"):
    return [i.check for i in report.issues if i.severity == severity]


# ---------- numeric grounding: good numbers pass ----------

@pytest.mark.parametrize("written", [
    "INR 267,021 crore",        # exactly as displayed
    "INR 2,67,021 crore",       # Indian digit grouping, as TCS prints it
    "₹267,021 crore",
    "Rs. 2,67,021 crore",
    "267021 crore",
    "267,021",                  # no unit written: matched on value
])
def test_formatting_variants_of_a_tool_number_pass(env, written):
    r = fact(env, "revenue_from_operations", "FY26")
    rep = verify(f"Revenue from operations in FY26 was {written} [{eid(r)}].", [r])
    assert rep.ok, rep.issues
    assert [n.number_id for n in rep.numbers_in_text] == [r.numbers[0].number_id]


@pytest.mark.parametrize("written", ["18.43%", "18.4%", "18%", "18.43 per cent"])
def test_rounding_as_displayed_passes(env, written):
    r = ratio(env, "net_margin", "FY26")
    rep = verify(f"Net margin in FY26 was {written} [{eid(r)}].", [r])
    assert rep.ok, rep.issues


def test_period_labels_dates_and_citation_ids_are_not_figures(env):
    r = fact(env, "revenue_from_operations", "FY26")
    text = (f"In FY26 (fiscal year 2025-26, which runs from 1 April 2025 to 31 March 2026, i.e. "
            f"2025-04-01 to April 1, 2025 ... March 31, 2026), revenue was INR 267,021 crore [{eid(r)}].")
    rep = verify(text, [r])
    assert rep.ok, rep.issues


def test_page_numbers_must_be_pages_of_the_evidence(env):
    r = fact(env, "revenue_from_operations", "FY26")       # AR FY26, PDF page 167, printed 197
    assert verify(f"Revenue was INR 267,021 crore (PDF page 167, printed page 197) [{eid(r)}].", [r]).ok
    rep = verify(f"Revenue was INR 267,021 crore (page 212) [{eid(r)}].", [r])
    assert checks(rep) == ["page_unknown"]


def test_number_from_a_passage_is_a_warning_not_an_error(env):
    r = run(env, "search_documents", query="single customer revenue")
    rep = verify("No single customer accounts for 10% or more of revenue [chunk:c-cust].", [r])
    assert rep.ok and "passage_number" in checks(rep, "warning")


# ---------- numeric grounding: injected bad numbers are caught ----------

@pytest.mark.parametrize("bad", [
    "INR 267,000 crore",        # rounded to thousands: not as displayed
    "INR 270,021 crore",        # typo
    "INR 267,021 million",      # unit converted / wrong unit
    "INR 2.67 lakh crore",      # unit converted
    "INR 2,670.21 billion",     # unit converted
    "267,021%",                 # wrong unit kind
    "INR 11,697 crore",         # LLM arithmetic: 267,021 - 255,324
])
def test_injected_bad_numbers_are_caught(env, bad):
    r26 = fact(env, "revenue_from_operations", "FY26")
    r25 = fact(env, "revenue_from_operations", "FY25")
    rep = verify(f"Revenue from operations in FY26 was {bad} [{eid(r26)}].", [r26, r25])
    assert not rep.ok and "number_unsupported" in checks(rep)


def test_invented_percentage_is_caught(env):
    r = ratio(env, "net_margin", "FY26")
    rep = verify(f"Net margin in FY26 was 18.43% [{eid(r)}], with an operating margin of 24.7%.", [r])
    assert checks(rep) == ["number_unsupported"] and "24.7%" in rep.issues[0].span


def test_more_decimals_than_shown_is_caught(env):
    r = ratio(env, "net_margin", "FY26")
    assert not verify(f"Net margin was 18.4293% [{eid(r)}].", [r]).ok
    assert verify(f"Net margin was 18.430% [{eid(r)}].", [r]).ok        # trailing zero only


def test_number_attached_to_the_wrong_period_is_caught(env):
    r26 = fact(env, "revenue_from_operations", "FY26")
    r25 = fact(env, "revenue_from_operations", "FY25")
    rep = verify(f"Revenue was INR 255,324 crore in FY26 [{eid(r25)}].", [r26, r25])
    assert "period_mismatch" in checks(rep)


def test_date_not_in_the_tool_results_is_caught(env):
    r = fact(env, "revenue_from_operations", "FY26")
    rep = verify(f"FY26 began on 1 April 2019; revenue was INR 267,021 crore [{eid(r)}].", [r])
    assert "date_unknown" in checks(rep)


# ---------- citations and numbers_used ----------

def test_citation_id_in_the_text_must_exist(env):
    r = fact(env, "revenue_from_operations", "FY26")
    rep = verify("Revenue was INR 267,021 crore [fact:999].", [r])
    assert "citation_unknown" in checks(rep)


def test_cited_and_listed_ids_must_exist(env):
    r = fact(env, "revenue_from_operations", "FY26")
    nid = r.numbers[0].number_id
    rep = verify(f"Revenue was INR 267,021 crore [{eid(r)}].", [r],
                 listed_number_ids=[nid, "fact:999#value"], cited_ids=["chunk:made-up"])
    assert sorted(checks(rep)) == ["citation_unknown", "number_id_unknown"]
    assert any("fact:999#value" in i.message for i in rep.issues)
    assert any("chunk:made-up" in i.message for i in rep.issues)


def test_citation_pointing_at_the_wrong_evidence_is_caught(env):
    rev = fact(env, "revenue_from_operations", "FY26")
    pat = fact(env, "profit_after_tax", "FY26")
    rep = verify(f"Revenue was INR 267,021 crore [{eid(pat)}].", [rev, pat])
    assert checks(rep) == ["citation_mismatch"]
    rep = verify("Revenue was INR 267,021 crore [chunk:c-cyber].",
                 [rev, run(env, "search_documents", query="cyber attacks")])
    assert checks(rep) == ["citation_mismatch"]


def test_a_calculation_citation_supports_its_input_figures(env):
    r = ratio(env, "net_margin", "FY26")
    rep = verify(f"Net margin was 18.43% on revenue of INR 267,021 crore [{eid(r)}].", [r])
    assert rep.ok, rep.issues


def test_missing_citation_is_only_a_warning(env):
    r = fact(env, "revenue_from_operations", "FY26")
    rep = verify("Revenue was INR 267,021 crore in FY26.", [r])
    assert rep.ok and "citation_missing" in checks(rep, "warning")


def test_numbers_used_are_the_numbers_the_text_actually_says(env):
    rev = fact(env, "revenue_from_operations", "FY26")
    pat = fact(env, "profit_after_tax", "FY26")
    eps = fact(env, "eps_basic", "FY26")
    listed = [rev.numbers[0].number_id, pat.numbers[0].number_id]          # PAT listed but never written
    rep = verify(f"Revenue was INR 267,021 crore [{eid(rev)}]; basic EPS was INR 136.01 per share [{eid(eps)}].",
                 [rev, pat, eps], listed_number_ids=listed)
    assert rep.ok
    assert [n.number_id for n in rep.numbers_in_text] == [rev.numbers[0].number_id, eps.numbers[0].number_id]
    warned = {i.check for i in rep.issues if i.severity == "warning"}
    assert {"numbers_used_not_in_text", "numbers_used_missing"} <= warned


def test_same_figure_from_two_tools_is_counted_once(env):
    f = fact(env, "revenue_from_operations", "FY26")
    r = ratio(env, "net_margin", "FY26")          # has revenue FY26 as an input: same fact id
    rep = verify(f"Revenue was INR 267,021 crore [{eid(f)}].", [f, r])
    assert [n.number_id for n in rep.numbers_in_text] == [f.numbers[0].number_id]


# ---------- comparison claims ----------

def test_comparison_with_only_one_year_fetched_is_caught(env):
    # The live failure (PDEV-17): only FY26 was fetched, the text claims a change from FY25.
    r = ratio(env, "net_margin", "FY26")
    rep = verify(f"Net margin was 18.43% in FY26 [{eid(r)}] and decreased from FY25 to FY26.", [r])
    assert "comparison_unsupported" in checks(rep)


def test_comparison_with_both_years_and_the_right_direction_passes(env):
    r26, r25 = ratio(env, "net_margin", "FY26"), ratio(env, "net_margin", "FY25")
    for text in [f"Net margin decreased from FY25 to FY26 [{eid(r26)}, {eid(r25)}].",
                 f"Net margin fell from 19.02% in FY25 to 18.43% in FY26 [{eid(r25)}, {eid(r26)}].",
                 f"Net margin in FY26 was lower than in FY25 [{eid(r26)}, {eid(r25)}].",
                 f"Compared with FY25, net margin declined in FY26 [{eid(r26)}]."]:
        rep = verify(text, [r26, r25])
        assert rep.ok, (text, rep.issues)


@pytest.mark.parametrize("text", [
    "Net margin increased from FY25 to FY26 [{a}, {b}].",
    "Net margin rose from 19.02% in FY25 to 18.43% in FY26 [{b}, {a}].",
    "Net margin in FY26 was higher than in FY25 [{a}, {b}].",
    "Net margin improved in FY26 [{a}].",
])
def test_wrong_direction_is_caught(env, text):
    r26, r25 = ratio(env, "net_margin", "FY26"), ratio(env, "net_margin", "FY25")
    rep = verify(text.format(a=eid(r26), b=eid(r25)), [r26, r25])
    assert "comparison_wrong_direction" in checks(rep), rep.issues


def test_growth_rate_supports_a_direction_and_its_sign_is_checked(env):
    g = ratio(env, "revenue_growth_yoy", "FY26")
    assert verify(f"Revenue grew 4.58% in FY26 [{eid(g)}].", [g]).ok
    assert "comparison_wrong_direction" in checks(verify(f"Revenue fell 4.58% in FY26 [{eid(g)}].", [g]))


def test_increase_to_a_figure_needs_the_earlier_figure(env):
    r26 = fact(env, "revenue_from_operations", "FY26")
    rep = verify(f"Revenue increased to INR 267,021 crore in FY26 [{eid(r26)}].", [r26])
    assert "comparison_unsupported" in checks(rep)
    r25 = fact(env, "revenue_from_operations", "FY25")
    assert verify(f"Revenue increased to INR 267,021 crore in FY26 [{eid(r26)}].", [r26, r25]).ok
    rep = verify(f"Revenue decreased to INR 267,021 crore in FY26 [{eid(r26)}].", [r26, r25])
    assert "comparison_wrong_direction" in checks(rep)


def test_qualitative_direction_words_without_figures_are_not_checked(env):
    r = run(env, "search_documents", query="cyber attacks")
    assert verify("Cyber threats have increased, so TCS expanded its security operations [chunk:c-cyber].", [r]).ok


def test_change_to_the_unchanged_base_value_is_caught(env):
    # The live slip: "terminal growth decreases to 5.00%" when the tool shows it unchanged.
    d = toy_dcf(env, sensitivity=True)
    rep = verify(f"If terminal growth decreases to 4.00%, the value per share is INR 229.32 [{eid(d)}].", [d])
    assert "change_contradicts" in checks(rep)


def test_sensitivity_changes_are_checked_against_the_base_case(env):
    d = toy_dcf(env, sensitivity=True)
    by_field = {n.number_id.split("#")[1]: n for n in d.numbers}
    lower = next(n for n in d.numbers if n.label.startswith("Value per share at WACC 13.00% and terminal growth 4.00%"))
    ok_text = (f"If WACC increases to 13.00%, the value per share falls to {lower.display} [{eid(d)}], "
               f"from {by_field['value_per_share'].display} in the base case.")
    rep = verify(ok_text, [d])
    assert rep.ok, rep.issues
    bad = f"If WACC decreases to 13.00%, the value per share falls to {lower.display} [{eid(d)}]."
    assert "change_contradicts" in checks(verify(bad, [d]))
    bad = f"If WACC increases to 13.00%, the value per share rises to {lower.display} [{eid(d)}]."
    assert "change_contradicts" in checks(verify(bad, [d]))


def cell(d, wacc, growth):
    return next(n for n in d.numbers if n.label == f"Value per share at WACC {wacc} and terminal growth {growth}")


def test_grid_value_must_belong_to_the_conditions_the_sentence_states(env):
    # Live slip (PDEV-13, M6 run): "Increasing WACC to 13.92% ... decreases the value per share to
    # INR 1,858.48" when 1,858.48 was the cell for WACC 13.92% AND terminal growth 6.00%.
    d = toy_dcf(env, sensitivity=True)
    wrong = cell(d, "13.00%", "5.00%").display   # base growth is 4.00%: this cell also moves growth, unstated
    rep = verify(f"If WACC increases to 13.00%, the value per share falls to {wrong} [{eid(d)}].", [d])
    assert "sensitivity_mismatch" in checks(rep)
    right = cell(d, "13.00%", "5.00%").display
    assert verify(f"At a WACC of 13.00% and terminal growth of 5.00%, the value per share is {right} [{eid(d)}].",
                  [d]).ok
    # each clause states its own condition; the unstated one stays at the base case
    a, b = cell(d, "13.00%", "4.00%").display, cell(d, "12.00%", "3.00%").display
    rep = verify(f"If WACC rises to 13.00%, the value falls to {a}, while if terminal growth falls to 3.00%, "
                 f"it falls to {b} [{eid(d)}].", [d])
    assert rep.ok, rep.issues


def test_from_x_to_y_with_numbers_must_match_the_direction(env):
    d = toy_dcf(env, sensitivity=True)
    assert "change_contradicts" in checks(verify(f"WACC decreases from 12.00% to 13.00% [{eid(d)}].", [d]))
    assert verify(f"WACC increases from 12.00% to 13.00% [{eid(d)}].", [d]).ok


# ---------- interpretive words ----------

def test_unsupported_interpretive_words_are_warnings_only(env):
    r = fact(env, "revenue_from_operations", "FY26")
    rep = verify(f"Revenue was INR 267,021 crore [{eid(r)}]. TCS has a strong and stable business.", [r])
    assert rep.ok
    flagged = [i for i in rep.issues if i.check == "interpretive_word"]
    assert {i.span for i in flagged} == {"strong", "stable"} and all(i.severity == "warning" for i in flagged)


def test_interpretive_word_backed_by_a_number_is_not_flagged(env):
    r = fact(env, "revenue_from_operations", "FY26")
    rep = verify(f"Revenue was a significant INR 267,021 crore [{eid(r)}].", [r])
    assert "interpretive_word" not in checks(rep, "warning")


def test_template_style_answer_with_only_tool_numbers_passes(env):
    r26, r25 = ratio(env, "net_margin", "FY26"), ratio(env, "net_margin", "FY25")
    lines = [f"{n.label}: {n.display} [{n.evidence_id}]." for r in (r26, r25) for n in r.numbers]
    rep = verify("\n".join(lines), [r26, r25])
    assert rep.ok, rep.issues
