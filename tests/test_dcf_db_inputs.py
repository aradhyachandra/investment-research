"""D2: the DCF reads base-year revenue and bridge items from the facts database.

Inputs fetched with get_financial_fact (consolidated, the fiscal year ending on the valuation date):
    base_year_revenue     = revenue_from_operations
    cash_and_investments  = cash_and_equivalents + other_balances_with_banks + current_investments
                            + non_current_investments, plus YAML adjustments (-609 earmarked balances,
                            -2,289 TCS Foundation deposits; note on PDF p.185)
    lease_liabilities     = lease_liabilities_current + lease_liabilities_non_current, x 0 while
                            the assumptions treat leases as an operating cost
    minority_interest     = non_controlling_interests, plus YAML adjustment +126 (Class B CCPS, p.166)
    diluted_shares        = shares_outstanding (SHARES_CRORE)

Expected figures (INR crore, FY26, data/manual/financials_tcs.csv, AR PDF p.166/167/196):
    cash 6,417 + 6,491 + 33,770 + 218 = 46,896; - 609 - 2,289 = 43,998   (the old typed value)
    leases 1,830 + 9,453 = 11,283; used in the bridge: 0                    (old typed value 0)
    minority 1,238 + 126 = 1,364                                            (old typed value)
    shares 3,618,087,518 shares = 361.8087518 crore   (old typed value 361.80875, rounded)

PINNED (no change in results): engine output BEFORE D2, with the typed YAML values, recorded on
2026-10-08 at commit b0358b7:
    base 1914.8185251855948   equity 692798.0970742435
    bear 1445.1121760470942   equity 522854.230025379
    bull 2351.66131697048     equity 850851.6415164431
Equity value does not depend on the share count, so it must be identical to the bit. Per share
moves by about 5e-9 relative (the old YAML rounded the share count to 361.80875 crore); at two
decimals (as shown everywhere) it is identical.
"""
import json

import pytest
import yaml

from conftest import REPO
from erp.agent.tools import ToolCall, ToolEnv, run_tool
from erp.db.load_facts import load_rows
from erp.dcf.assumptions import AssumptionError, load_scenario
from erp.dcf.engine import DCFError
from erp.dcf.run import run_dcf
from erp.ui import dcf_view
from erp.ui import view_model as vm
from test_agent_tools import DISPLAY
from test_d1_facts import manual_rows
from test_ui import FOOTER, UI_CFG

TCS_YAML = REPO / "data" / "manual" / "dcf_inputs.yaml"
DB_INPUTS = {"base_year_revenue", "cash_and_investments", "lease_liabilities", "minority_interest",
             "diluted_shares"}
# base re-pinned 2026-10-10 after the author lowered base revenue growth to a flat 6% (was 1914.82)
PINNED = {"base": (1880.5285611688391, 680391.6914407477, 1880.53),
          "bear": (1445.1121760470942, 522854.230025379, 1445.11),
          "bull": (2351.66131697048, 850851.6415164431, 2351.66)}


def _load(conn, ctx, rows):
    load_rows(conn, rows, ctx, entry_method="llm_extracted")
    return conn


@pytest.fixture
def tcs(conn, ctx):
    """In-memory DB with the whole manual CSV (as committed: every row signed off)."""
    return _load(conn, ctx, manual_rows())


def _unverify(rows, metrics):
    out = []
    for r in rows:
        r = dict(r)
        if r["metric_id"] in metrics and r["period"] == "FY26":
            r["verified_by"] = r["verified_on"] = ""
        out.append(r)
    return out


def tcs_yaml_data():
    return yaml.safe_load(TCS_YAML.read_text())


def write(tmp_path, data):
    p = tmp_path / "dcf_inputs.yaml"
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def by_name(result):
    return {i.assumption: i for i in result.db_inputs}


# ---------- 1. no change in results (pinned) ----------

@pytest.mark.parametrize("scenario", ["base", "bear", "bull"])
def test_results_unchanged_from_typed_values(tcs, scenario):
    per_share, equity, shown = PINNED[scenario]
    r = run_dcf(tcs, "TCS", scenario)
    assert r.valuation.equity_value == equity                    # bit-identical
    assert r.valuation.value_per_share == pytest.approx(per_share, rel=1e-8)
    assert round(r.valuation.value_per_share, 2) == shown
    assert all(c.status == "pass" for c in r.checks)


# ---------- 2. the real assumptions file reads these inputs from the database ----------

def test_real_file_takes_base_and_bridge_inputs_from_the_database():
    data = tcs_yaml_data()
    shared = data["shared"]
    assert data["facts_basis"] == "consolidated"
    expected = {
        "base_year_revenue": ["revenue_from_operations"],
        "cash_and_investments": ["cash_and_equivalents", "other_balances_with_banks", "current_investments",
                                 "non_current_investments"],
        "lease_liabilities": ["lease_liabilities_current", "lease_liabilities_non_current"],
        "minority_interest": ["non_controlling_interests"],
        "diluted_shares": ["shares_outstanding"],
    }
    for name, metrics in expected.items():
        assert shared[name]["from_db"] == metrics, name
        assert "value" not in shared[name], f"{name} must not also carry a typed number"
    assert shared["lease_liabilities"]["treat_as"] == "operating_cost"
    # Scenarios do not override database inputs with typed numbers.
    for scen, block in data["scenarios"].items():
        assert not DB_INPUTS & set(block or {}), scen


def test_real_file_adjustments_have_value_rationale_and_source():
    shared = tcs_yaml_data()["shared"]
    cash = shared["cash_and_investments"]["adjustments"]
    assert [a["value"] for a in cash] == [-609, -2289]
    assert all("185" in a["source"] for a in cash)
    minority = shared["minority_interest"]["adjustments"]
    assert [a["value"] for a in minority] == [126]
    assert "166" in minority[0]["source"]
    for a in cash + minority:
        assert a["rationale"].strip() and a["source"].strip()


# ---------- 3. what run_dcf fetched, and where it is recorded ----------

def test_db_inputs_resolved_with_facts_and_adjustments(tcs):
    r = run_dcf(tcs, "TCS", "base")
    i = by_name(r)
    assert set(i) == DB_INPUTS
    assert all(x.period == "FY26" and x.basis == "consolidated" for x in i.values())

    cash = i["cash_and_investments"]
    assert [f.metric_id for f in cash.facts] == ["cash_and_equivalents", "other_balances_with_banks",
                                                 "current_investments", "non_current_investments"]
    assert [f.value for f in cash.facts] == [6417, 6491, 33770, 218]
    assert {f.source_page for f in cash.facts} == {166}
    assert cash.facts_total == 46896
    assert [a.value for a in cash.adjustments] == [-609, -2289]
    assert cash.value == 43998
    assert r.valuation.bridge.cash_and_investments == 43998

    leases = i["lease_liabilities"]
    assert leases.facts_total == 11283
    assert leases.treat_as == "operating_cost"
    assert leases.value == 0
    assert r.valuation.bridge.lease_liabilities == 0

    minority = i["minority_interest"]
    assert minority.facts_total == 1238 and minority.value == 1364

    revenue = i["base_year_revenue"]
    assert revenue.value == 267021 and revenue.facts[0].source_page == 167
    assert r.fcff_build[0].revenue_prior == 267021

    shares = i["diluted_shares"]
    assert shares.facts[0].unit == "SHARES_CRORE"
    assert shares.facts[0].reported_value == 3618087518
    assert shares.value == pytest.approx(361.8087518, rel=1e-12)
    assert shares.facts[0].source_page == 196
    # The engine sees the resolved numbers as the assumptions' values.
    assert r.assumptions["cash_and_investments"].value == 43998
    assert r.assumptions["cash_and_investments"].from_db


def test_dcf_run_row_records_fact_ids_and_pages(tcs):
    r = run_dcf(tcs, "TCS", "base")
    row = tcs.execute("SELECT assumptions_json FROM dcf_run WHERE run_id = ?", (r.run_id,)).fetchone()
    stored = json.loads(row[0])["db_inputs"]
    cash = next(x for x in stored if x["assumption"] == "cash_and_investments")
    assert [f["fact_id"] for f in cash["facts"]] == [f.fact_id for f in by_name(r)["cash_and_investments"].facts]
    assert [f["source_page"] for f in cash["facts"]] == [166] * 4
    assert cash["value"] == 43998
    assert [a["value"] for a in cash["adjustments"]] == [-609, -2289]
    assert json.loads(row[0])["unverified_fact_ids"] == []


def test_shares_in_a_different_unit_give_the_same_value_per_share(tcs, tmp_path):
    data = tcs_yaml_data()
    data["units"]["shares"] = "SHARES"
    p = write(tmp_path, data)
    r = run_dcf(tcs, "TCS", "base", assumptions_path=p)
    assert by_name(r)["diluted_shares"].value == pytest.approx(3618087518, rel=1e-12)
    assert r.valuation.value_per_share == pytest.approx(PINNED["base"][0], rel=1e-8)


# ---------- 4. unverified facts ----------

def test_all_verified_gives_no_unverified_note(tcs):
    r = run_dcf(tcs, "TCS", "base")
    assert r.unverified_fact_ids == []
    assert not any("not yet verified" in n for n in r.notes)


def test_unverified_inputs_are_noted_but_the_run_works(conn, ctx):
    db = _load(conn, ctx, _unverify(manual_rows(), {"current_investments", "non_controlling_interests"}))
    r = run_dcf(db, "TCS", "base")
    assert round(r.valuation.value_per_share, 2) == 1880.53
    assert len(r.unverified_fact_ids) == 2
    assert any("uses 2 facts not yet verified by a human" in n for n in r.notes)

    env = ToolEnv(conn=db, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    t = run_tool(ToolCall(tool="run_dcf", args={"scenario": "base"}), env)
    assert t.ok
    assert any("uses 2 facts not yet verified by a human" in n for n in t.notes)
    facts = {e.evidence_id: e for e in t.evidence if e.kind == "fact"}
    assert sum(1 for e in facts.values() if e.verified is False) == 2


def test_one_unverified_fact_is_singular(conn, ctx):
    db = _load(conn, ctx, _unverify(manual_rows(), {"shares_outstanding"}))
    r = run_dcf(db, "TCS", "base")
    assert any("uses 1 fact not yet verified by a human" in n for n in r.notes)


def test_unverified_note_reaches_the_answer(conn, ctx):
    from erp.agent.loop import answer_question
    from test_ui import scripted
    db = _load(conn, ctx, _unverify(manual_rows(), {"current_investments"}))
    env = ToolEnv(conn=db, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    a = answer_question("What is the base-case DCF value per share?", env,
                        scripted([{"tool": "run_dcf", "scenario": "base"}], question_type="valuation"))
    assert any("uses 1 fact not yet verified by a human" in x for x in a.limitations)


# ---------- 5. tool output: citations to the facts ----------

def test_tool_cites_the_input_facts_with_pages(tcs):
    env = ToolEnv(conn=tcs, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    t = run_tool(ToolCall(tool="run_dcf", args={"scenario": "base"}), env)
    assert t.ok
    dcf_ev = next(e for e in t.evidence if e.kind == "dcf_run")
    facts = [e for e in t.evidence if e.kind == "fact"]
    assert len(facts) == 9                                         # 1 + 4 + 2 + 1 + 1
    assert dcf_ev.input_evidence_ids == [e.evidence_id for e in facts]
    assert {e.page for e in facts} == {166, 167, 196}
    assert all(e.period == "FY26" and e.basis == "consolidated" for e in facts)
    # Each input fact and each resolved input is a number an answer may quote.
    nums = {n.number_id: n for n in t.numbers}
    assert any(n.evidence_id.startswith("fact:") and n.value == 6417 for n in nums.values())
    cash = next(n for n in nums.values() if n.number_id.endswith("#input_cash_and_investments"))
    assert cash.display == "INR 43,998 crore"
    assert any(n.number_id.endswith("#input_cash_and_investments_adjustment_1") and n.value == -609
               for n in nums.values())


def test_answer_citations_include_the_input_facts(tcs):
    from erp.agent.loop import answer_question
    from test_ui import scripted
    env = ToolEnv(conn=tcs, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    a = answer_question("What is the base-case DCF value per share?", env,
                        scripted([{"tool": "run_dcf", "scenario": "base"}], question_type="valuation"))
    kinds = [c.kind for c in a.citations]
    assert "dcf_run" in kinds and kinds.count("fact") == 9


# ---------- 6. missing facts: refuse, never fall back ----------

@pytest.mark.parametrize("metric", ["revenue_from_operations", "current_investments", "lease_liabilities_current",
                                    "non_controlling_interests", "shares_outstanding"])
def test_missing_fact_refuses_naming_metric_and_period(conn, ctx, metric):
    rows = [r for r in manual_rows() if not (r["metric_id"] == metric and r["period"] == "FY26")]
    db = _load(conn, ctx, rows)
    with pytest.raises(DCFError) as e:
        run_dcf(db, "TCS", "base")
    assert metric in str(e.value) and "FY26" in str(e.value)
    assert db.execute("SELECT COUNT(*) FROM dcf_run").fetchone()[0] == 0

    env = ToolEnv(conn=db, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    t = run_tool(ToolCall(tool="run_dcf", args={"scenario": "base"}), env)
    assert not t.ok and metric in t.error and "FY26" in t.error


def test_valuation_date_must_be_a_fiscal_year_end(tcs, tmp_path):
    data = tcs_yaml_data()
    data["shared"]["valuation_date"]["value"] = "2026-06-30"
    with pytest.raises(DCFError, match="fiscal year end"):
        run_dcf(tcs, "TCS", "base", assumptions_path=write(tmp_path, data))


def test_valuation_year_without_facts_refuses(tcs, tmp_path):
    data = tcs_yaml_data()
    data["shared"]["valuation_date"]["value"] = "2027-03-31"
    with pytest.raises(DCFError, match="FY27"):
        run_dcf(tcs, "TCS", "base", assumptions_path=write(tmp_path, data))


def test_unknown_metric_refuses(tcs, tmp_path):
    data = tcs_yaml_data()
    data["shared"]["cash_and_investments"]["from_db"].append("treasury_bills")
    with pytest.raises(DCFError, match="treasury_bills"):
        run_dcf(tcs, "TCS", "base", assumptions_path=write(tmp_path, data))


# ---------- 7. the YAML shape is checked when loading ----------

def _bad(tmp_path, mutate):
    data = tcs_yaml_data()
    mutate(data["shared"])
    return write(tmp_path, data)


@pytest.mark.parametrize("mutate,message", [
    (lambda s: s["cash_and_investments"]["adjustments"][0].pop("rationale"), "rationale"),
    (lambda s: s["cash_and_investments"]["adjustments"][0].update(source="  "), "source"),
    (lambda s: s["cash_and_investments"]["adjustments"][0].update(value="609"), "number"),
    (lambda s: s["cash_and_investments"]["adjustments"][0].update(page=185), "unexpected keys"),
    (lambda s: s["cash_and_investments"].update(value=43998), "both"),
    (lambda s: s["cash_and_investments"].update(from_db=[]), "from_db"),
    (lambda s: s["cash_and_investments"].update(from_db="cash_and_equivalents"), "from_db"),
    (lambda s: s["cash_and_investments"].update(from_db=["cash_and_equivalents", "cash_and_equivalents"]), "twice"),
    (lambda s: s["cash_and_investments"].pop("rationale"), "rationale"),
    (lambda s: s["lease_liabilities"].pop("treat_as"), "treat_as"),
    (lambda s: s["lease_liabilities"].update(treat_as="maybe"), "treat_as"),
    (lambda s: s["cash_and_investments"].update(treat_as="operating_cost"), "treat_as"),
    (lambda s: s["beta"].update(from_db=["revenue_from_operations"]), "from_db"),
    (lambda s: s["debt"].update(adjustments=[{"value": 1, "rationale": "x", "source": "y"}]), "adjustments"),
])
def test_bad_db_entries_are_refused(tmp_path, mutate, message):
    with pytest.raises(AssumptionError, match=message):
        load_scenario(_bad(tmp_path, mutate), "base")


def test_facts_basis_required_when_using_the_database(tmp_path):
    data = tcs_yaml_data()
    del data["facts_basis"]
    with pytest.raises(AssumptionError, match="facts_basis"):
        load_scenario(write(tmp_path, data), "base")


def test_typed_values_still_work_for_files_without_from_db(db_toy):
    # The toy fixture types every input; it still runs (tests/test_dcf_run.py has the arithmetic).
    from test_dcf_run import TOY_YAML
    r = run_dcf(db_toy, "TOY", "base", assumptions_path=TOY_YAML)
    assert r.db_inputs == [] and r.unverified_fact_ids == []


@pytest.fixture
def db_toy():
    from erp.db.load_facts import create_db
    c = create_db(":memory:")
    c.execute("INSERT INTO company (ticker_nse, name) VALUES ('TOY', 'Toy company (test fixture, not real)')")
    yield c
    c.close()


# ---------- 8. UI: which inputs came from the database ----------

def test_dcf_path_shows_database_inputs_with_page_chips(tcs):
    env = ToolEnv(conn=tcs, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    t = run_tool(ToolCall(tool="run_dcf", args={"scenario": "base"}), env)
    p = vm.dcf_path(t, DISPLAY, TCS_YAML, FOOTER, ui_cfg=UI_CFG)
    inputs = {i.name: i for i in p.inputs}
    cash = inputs["cash_and_investments"]
    assert cash.origin == "database"
    assert cash.value_display == "INR 43,998 crore"
    assert [f.display for f in cash.facts] == ["INR 6,417 crore", "INR 6,491 crore", "INR 33,770 crore",
                                               "INR 218 crore"]
    assert all(f.citation.page_text == "PDF p.166 (printed p.196)" for f in cash.facts)
    assert all(f.citation.badge == vm.FILING for f in cash.facts)
    assert [a.display for a in cash.adjustments] == ["INR -609 crore", "INR -2,289 crore"]
    assert all("185" in a.source for a in cash.adjustments)
    leases = inputs["lease_liabilities"]
    assert leases.value_display == "INR 0 crore" and "operating cost" in leases.treatment
    assert inputs["debt"].origin == "assumptions file" and inputs["debt"].facts == []
    assert inputs["diluted_shares"].value_display == "361.81 crore shares"
    # Assumptions table says where each value came from.
    rows = {a.name: a for a in p.assumptions}
    assert rows["cash_and_investments"].origin.startswith("database")
    assert "fact:" in rows["cash_and_investments"].origin
    assert rows["beta"].origin == "assumptions file"


def test_dcf_path_for_an_old_saved_run_without_db_inputs(tcs):
    """Saved answers from before D2 (--demo) carry no db_inputs: everything shows as the assumptions file."""
    env = ToolEnv(conn=tcs, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    t = run_tool(ToolCall(tool="run_dcf", args={"scenario": "base"}), env)
    old = t.model_copy(deep=True)
    old.detail.pop("db_inputs")
    old.detail.pop("unverified_fact_ids")
    old.evidence = [e for e in old.evidence if e.kind != "fact"]
    p = vm.dcf_path(old, DISPLAY, TCS_YAML, FOOTER, ui_cfg=UI_CFG)
    assert all(i.origin == "assumptions file" for i in p.inputs)


def test_dcf_tab_carries_the_input_sources(tcs):
    env = ToolEnv(conn=tcs, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    v = dcf_view.build_dcf_tab(env, ["bear", "base", "bull"], base="base", assumptions_file=TCS_YAML, footer=FOOTER)
    assert [b.display for b in v.scenarios] == ["INR 1,445.11 per share", "INR 1,880.53 per share",
                                                "INR 2,351.66 per share"]
    assert {i.name for i in v.base.inputs if i.origin == "database"} == DB_INPUTS


def test_answer_preview_targets_include_dcf_input_pages(tcs):
    from erp.agent.loop import answer_question
    from test_ui import scripted
    env = ToolEnv(conn=tcs, ticker="TCS", display=DISPLAY, dcf_assumptions=TCS_YAML)
    a = answer_question("What is the base-case DCF value per share?", env,
                        scripted([{"tool": "run_dcf", "scenario": "base"}], question_type="valuation"))
    view = vm.build_view(a, display=DISPLAY, ui_cfg=UI_CFG, assumptions_file=TCS_YAML, dcf_footer=FOOTER)
    fact_cites = [c for c in view.citations if c.kind == "fact"]
    assert len(fact_cites) == 9 and all(c.badge == vm.FILING and c.reported_value is not None for c in fact_cites)
