"""M5: the tool layer. Four existing tools behind one interface; every result carries evidence.

Sample facts (data/sample/facts_sample.csv, INR crore): revenue FY26 267021, FY25 255324;
profit attributable to owners FY26 49210. AR FY26 = source 1, P&L on PDF p.167 (printed 197).
DCF uses the TOY fixture (not TCS, not real): base value per share 229.3236 (hand arithmetic in test_dcf_run.py).
"""
import pytest

from erp.agent.llm import load_agent_config
from erp.agent.tools import ToolCall, ToolEnv, format_number, run_tool
from erp.ingest.index_chroma import add_chunks, open_collection
from fakes import fake_embed
from test_dcf_run import TOY_YAML

DISPLAY = load_agent_config()["display"]


def chunk_meta(chunk_id, page, section):
    return {"source_id": 1, "doc_type": "annual_report", "doc_title": "TCS Integrated Annual Report 2025-26",
            "page": page, "page_end": page, "page_label": str(page + 30), "page_label_end": str(page + 30),
            "section": section, "fiscal_year": 2026, "chunk_id": chunk_id, "is_table_heavy": False,
            "file_sha256": "ab" * 32, "embed_model": "fake"}


CHUNKS = [
    ("Cyber attacks: TCS runs security operations centres and holds cyber insurance.",
     chunk_meta("c-cyber", 64, "Enterprise Risk Management")),
    ("Dividends and buybacks return surplus cash to shareholders.", chunk_meta("c-div", 24, "Financial Capital")),
    ("No single customer accounts for 10% or more of revenue.", chunk_meta("c-cust", 226, "Notes")),
]


@pytest.fixture
def collection(tmp_path):
    col = open_collection(tmp_path / "chroma", "test_docs")
    add_chunks(col, CHUNKS, embed_fn=fake_embed)
    return col


@pytest.fixture
def env(loaded, collection):
    return ToolEnv(conn=loaded, ticker="TCS", display=DISPLAY, collection=collection, embed_fn=fake_embed,
                   dcf_assumptions=TOY_YAML)


def call(env, tool, **args):
    return run_tool(ToolCall(tool=tool, args=args), env)


# ---------- formatting ----------

@pytest.mark.parametrize("value,unit,expected", [
    (267021, "INR_CRORE", "INR 267,021 crore"),
    (136.01, "INR_PER_SHARE", "INR 136.01 per share"),
    (18.4292621179607, "PERCENT", "18.43%"),
    (153.27327, "INR", "INR 153"),
])
def test_format_number_is_done_by_code(value, unit, expected):
    assert format_number(value, unit, DISPLAY) == expected


# ---------- get_financial_fact ----------

def test_fact_result_carries_number_and_evidence(env):
    r = call(env, "get_financial_fact", metric_id="revenue_from_operations", period="FY26")
    assert r.ok and r.error is None
    (n,) = r.numbers
    (e,) = r.evidence
    assert e.evidence_id.startswith("fact:") and e.kind == "fact"
    assert n.evidence_id == e.evidence_id and n.number_id == f"{e.evidence_id}#value"
    assert (n.value, n.unit, n.display, n.period, n.basis) == (267021, "INR_CRORE", "INR 267,021 crore",
                                                               "FY26", "consolidated")
    assert (e.source_id, e.page, e.page_label, e.period, e.basis, e.accounting_standard) == \
        (1, 167, "197", "FY26", "consolidated", "Ind AS")
    assert e.verified is False
    assert any("Not yet checked by a human" in note for note in r.notes)
    assert any("2025-04-01" in note and "2026-03-31" in note for note in r.notes)
    assert r.detail["fact_id"] == int(e.evidence_id.split(":")[1])


def test_missing_fact_is_an_error_not_a_guess(env):
    r = call(env, "get_financial_fact", metric_id="revenue_from_operations", period="FY22")
    assert not r.ok and r.numbers == [] and r.evidence == []
    assert "FY22" in r.error


@pytest.mark.parametrize("args", [
    {"metric_id": "revenue_from_operations"},                                   # no period
    {"metric_id": "revenue_from_operations", "period": "FY26", "basis": "group"},  # bad basis
])
def test_bad_arguments_are_refused(env, args):
    r = call(env, "get_financial_fact", **args)
    assert not r.ok and r.error.startswith("bad arguments")


def test_unknown_metric_and_bad_period_label_are_errors(env):
    assert not call(env, "get_financial_fact", metric_id="share_price", period="FY26").ok
    assert not call(env, "get_financial_fact", metric_id="revenue_from_operations", period="2026").ok


def test_unknown_tool(env):
    r = call(env, "predict_price")
    assert not r.ok and "unknown tool" in r.error


# ---------- compute_ratio ----------

def test_ratio_result_has_calc_evidence_and_input_facts(env):
    r = call(env, "compute_ratio", ratio_id="net_margin", period="FY26")
    assert r.ok
    calc, *facts = r.evidence
    assert calc.kind == "calc" and calc.evidence_id.startswith("calc:")
    assert calc.formula == "profit_attributable_to_owners[FY26] / revenue_from_operations[FY26] * 100"
    assert calc.input_evidence_ids == [f.evidence_id for f in facts]
    assert [(f.page, f.period) for f in facts] == [(167, "FY26"), (167, "FY26")]
    ratio = r.numbers[0]
    assert ratio.evidence_id == calc.evidence_id
    assert ratio.display == "18.43%"            # 49210 / 267021 x 100 = 18.4293 (test_ratios.py)
    # the input figures are numbers too, each pointing at its own fact
    assert {n.display for n in r.numbers[1:]} == {"INR 49,210 crore", "INR 267,021 crore"}
    assert all(n.evidence_id.startswith("fact:") for n in r.numbers[1:])
    assert any(note.startswith("Definition:") and "exceptional" in note for note in r.notes)


def test_ratio_needing_a_missing_year_is_an_error(env):
    r = call(env, "compute_ratio", ratio_id="revenue_growth_yoy", period="FY25")   # needs FY24
    assert not r.ok and "FY24" in r.error


# ---------- run_dcf ----------

def test_dcf_result_has_run_evidence(env):
    env.conn.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    env.ticker = "TOY"
    r = call(env, "run_dcf", scenario="base")
    assert r.ok
    (e,) = r.evidence
    assert e.kind == "dcf_run" and e.evidence_id.startswith("dcf:") and e.period == "2026-03-31"
    by_field = {n.number_id.split("#")[1]: n for n in r.numbers}
    assert by_field["value_per_share"].display == "INR 229.32 per share"
    assert by_field["wacc"].display == "12.00%" and by_field["terminal_growth"].display == "4.00%"
    assert not any(k.startswith("sensitivity") for k in by_field)
    assert any("not a prediction" in note for note in r.notes)


def test_dcf_sensitivity_numbers_on_request(env):
    env.conn.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    env.ticker = "TOY"
    r = call(env, "run_dcf", scenario="base", include_sensitivity=True)
    sens = [n for n in r.numbers if "#sensitivity_" in n.number_id]
    cells = [n for n in sens if n.quantity == "value_per_share"]
    assert cells and all(n.unit == "INR_PER_SHARE" and "WACC" in n.label and n.variant for n in cells)
    # M6: the grid's own WACC and growth values are numbers too (so prose quoting them can be verified)
    axes = {n.quantity: sorted(round(x.value, 2) for x in sens if x.quantity == n.quantity) for n in sens
            if n.quantity != "value_per_share"}
    assert axes == {"wacc": [11.0, 11.5, 12.0, 12.5, 13.0], "terminal_growth": [3.0, 3.5, 4.0, 4.5, 5.0]}
    base = {n.quantity: n for n in r.numbers if not n.variant}
    assert base["wacc"].display == "12.00%" and base["value_per_share"].quantity == "value_per_share"


def test_dcf_without_assumptions_file_is_an_error(env, tmp_path):
    env.dcf_assumptions = tmp_path / "missing.yaml"
    r = call(env, "run_dcf", scenario="base")
    assert not r.ok and "does not exist" in r.error


def test_dcf_unknown_scenario_is_an_error(env):
    env.conn.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    env.ticker = "TOY"
    assert not call(env, "run_dcf", scenario="moonshot").ok


# ---------- search_documents ----------

def test_search_result_has_chunk_evidence_and_passages(env):
    r = call(env, "search_documents", query="cyber attacks security")
    assert r.ok and r.numbers == []
    top = r.evidence[0]
    assert top.evidence_id == "chunk:c-cyber" and top.kind == "doc_chunk"
    assert (top.source_id, top.page, top.page_label, top.period) == (1, 64, "94", "FY26")
    assert top.basis is None
    assert [p.evidence_id for p in r.passages] == [e.evidence_id for e in r.evidence]


def test_empty_search_query_is_refused(env):
    assert not call(env, "search_documents", query="").ok


@pytest.mark.parametrize("args,expected", [({}, True), ({"prefer_latest": False}, False)])
def test_search_tool_prefers_latest_report_unless_told_not_to(env, monkeypatch, args, expected):
    # R1: the router turns the preference off when the question names a year; default is on.
    seen = {}

    def spy(query, **kw):
        seen.update(kw)
        return []

    monkeypatch.setattr("erp.agent.tools.search_documents", spy)
    call(env, "search_documents", query="attrition", **args)
    assert seen["prefer_latest"] is expected
