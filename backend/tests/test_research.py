"""Research engine: the parts that decide what is shown, tested without network or model."""
import json
import sqlite3

import pytest

from finn import db, llm
from finn.research import ask, corpus, financials, promises

COMPANY = {
    "basis": "Consolidated", "url": "https://example.test", "ratios": {"ROCE": 26.3},
    "quarters": {
        "columns": ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026", ],
        "rows": {"Sales": [1588.0, 1617.0, 1711.0, 1675.0, 1691.0],
                 "Operating Profit": [298.0, 311.0, 317.0, 257.0, 267.0],
                 "Net Profit": [169.0, 133.0, 163.0, 116.0, 121.0]},
    },
    "profit_loss": {
        "columns": ["Mar 2024", "Mar 2025", "Mar 2026", "TTM"],
        "rows": {"Sales": [4872.0, 5842.0, 6455.0, 6694.0], "Operating Profit": [991.0, 1230.0, 1220.0, 1152.0],
                 "Net Profit": [599.0, 840.0, 637.0, 533.0], "EPS in Rs": [21.7, 30.6, 23.3, 19.5]},
    },
    "cash_flow": {"columns": ["Mar 2025", "Mar 2026"],
                  "rows": {"Cash from Operating Activity": [1390.0, 1195.0], "Free Cash Flow": [1262.0, 1056.0]}},
    "balance_sheet": {"columns": ["Mar 2025", "Mar 2026", "Sep 2026"],
                      "rows": {"Equity Capital": [272.0, 272.0, 273.0], "Reserves": [2640.0, 3269.0, 3414.0],
                               "Borrowings": [345.0, 838.0, 764.0], "Total Assets": [4964.0, 7121.0, 7058.0]}},
    "ratio_table": {"columns": ["Mar 2025", "Mar 2026"], "rows": {"Debtor Days": [56.0, 61.0], "ROCE %": [40.0, 26.0]}},
}


class TestFinancials:
    def test_period_labels(self):
        assert financials.fiscal_year("Mar 2026") == "FY26"
        assert financials.fiscal_quarter("Sep 2026") == "Q2 FY27"
        assert financials.fiscal_quarter("Mar 2026") == "Q4 FY26"

    def test_growth_and_margins_are_computed_from_values(self):
        annual = financials.annual_series(COMPANY)
        assert annual["years"] == ["FY24", "FY25", "FY26"]
        assert annual["revenue_growth"] == [None, 19.9, 10.5]
        assert annual["ebitda_margin"][-1] == 18.9

    def test_actuals_table_keys(self):
        a = financials.actuals(COMPANY)
        assert a["FY26.revenue_growth"]["value"] == 10.5 and a["FY26.revenue_growth"]["partial"] is False
        assert a["Q2FY27.revenue_yoy"]["value"] == 6.5
        assert a["FY26.cash_conversion"]["value"] == 188.0
        assert financials.format_actual(a["FY26.fcf"]) == "₹1,056 cr"

    def test_year_to_date_needs_last_years_same_quarters(self):
        # Only 5 quarters here, so H1 FY27 has no complete comparison base: no YTD figure is invented.
        assert financials.year_to_date(COMPANY) is None


PAGES = [
    {"doc": "T1", "page": 4, "text": "Management: We will maintain 21% EBITDA margin for the full year. Demand in Europe is stable."},
    {"doc": "T1", "page": 5, "text": "Analyst: you had said margins would be 21 percent. Management: capex will be Rs 500 crore next year."},
    {"doc": "AR1", "page": 49, "text": "Revenue by geography: Europe 48.0%, US 27.4%, Asia 24.6%. Passenger cars 79.0% of revenue."},
]


class TestRetrieval:
    index = corpus.Index(PAGES)

    def test_bm25_finds_the_page_with_the_terms(self):
        hits = self.index.search("revenue by geography Europe share", k=2)
        assert (hits[0]["doc"], hits[0]["page"]) == ("AR1", 49)

    def test_search_can_be_limited_to_some_documents(self):
        assert all(h["doc"] == "T1" for h in self.index.search("Europe", k=3, docs={"T1"}))

    def test_call_month_maps_to_the_quarter_discussed(self):
        assert corpus.call_quarter("Nov 2026") == "Q2 FY27"
        assert corpus.call_quarter("May 2026") == "Q4 FY26"


class TestQuoteVerification:
    def test_verbatim_quote_is_located(self):
        assert promises.locate_quote("We will maintain 21% EBITDA margin for the full year", PAGES[:2], 4) == 4

    def test_wrong_page_claim_is_corrected(self):
        assert promises.locate_quote("capex will be Rs 500 crore next year", PAGES[:2], 4) == 5

    def test_invented_quote_is_rejected(self):
        assert promises.locate_quote("We will double revenue in three years with certainty", PAGES[:2], 4) is None

    def test_analyst_restating_guidance_is_not_management_guidance(self):
        assert promises.is_analyst_speech("you had said margins would be 21 percent")
        assert not promises.is_analyst_speech("We will maintain 21% EBITDA margin for the full year")


class TestNumericVerdicts:
    def test_at_least_and_range_targets(self):
        assert promises._met({"low": 21.0, "high": 21.0, "direction": "at_least"}, 18.9) is False
        assert promises._met({"low": 18.0, "high": 22.0, "direction": "range"}, 18.9) is True
        assert promises._met({"low": None, "high": None, "direction": "qualitative"}, 5.0) is None

    def test_rounding_tolerance(self):
        assert promises._met({"low": 19.0, "high": 19.0, "direction": "at_least"}, 18.6) is True

    def test_progress_against_a_range(self):
        target = {"low": 20.5, "high": 21.2, "direction": "range"}
        assert promises._progress(target, 15.6) == "behind"
        assert promises._progress(target, 20.9) == "on_track"
        assert promises._progress(target, 23.0) == "ahead"

    def test_a_figure_only_counts_for_its_own_period(self):
        assert promises.same_period("FY27_YTD.ebitda_margin", "FY27")
        assert not promises.same_period("FY27_YTD.ebitda_margin", "FY29")
        assert not promises.same_period("FY26.revenue_growth", "next 2-3 years")


@pytest.fixture
def conn():
    return db.init(sqlite3.connect(":memory:"))


@pytest.fixture
def reply(monkeypatch):
    box: dict = {"queue": []}

    def provider(model, system, prompt, json_mode, max_tokens):
        return json.dumps(box["queue"].pop(0) if box["queue"] else box["value"]), 40, 10

    monkeypatch.setitem(llm.PROVIDERS, "fake", provider)
    monkeypatch.setenv("FINN_CHEAP_MODEL", "fake:small")
    monkeypatch.setenv("FINN_STRONG_MODEL", "fake:large")
    return box


DOCS = [{"id": "T1", "kind": "transcript", "label": "Q2 FY26 concall (Nov 2025)", "short": "Q2 FY26 call",
         "period": "Nov 2025", "url": "https://example.test/t1.pdf"}]
STATEMENT = {"id": "T1-1", "call": "T1", "metric": "ebitda_margin", "label": "FY26 EBITDA margin", "period": "FY26",
             "target": "21%", "low": 21.0, "high": 21.0, "unit": "%", "direction": "at_least", "basis": "reported",
             "status": None, "speaker": "CFO", "quote": "We will maintain 21% EBITDA margin for the full year", "page": 4}
ACTUALS = {"FY26.ebitda_margin": {"value": 18.9, "unit": "%", "label": "FY26 EBITDA margin", "partial": False},
           "FY27_YTD.ebitda_margin": {"value": 15.6, "unit": "%", "label": "H1 FY27 EBITDA margin", "partial": True}}


def thread(**over):
    base = {"title": "FY26 EBITDA margin", "metric": "ebitda_margin", "period": "FY26", "statement_ids": ["T1-1"],
            "initial_target": "21%", "basis": "reported", "actual_keys": ["FY26.ebitda_margin"], "verdict": "delivered",
            "progress": None, "evidence": "Margin was {FY26.ebitda_margin} against 21%.",
            "final_target": {"text": "21%", "low": 21, "high": 21, "unit": "%", "direction": "at_least"}}
    return {**base, **over}


class TestJudge:
    def test_code_overrules_a_wrong_delivered_verdict_and_fills_in_the_figure(self, conn, reply):
        reply["value"] = {"threads": [thread()]}
        (t,) = promises.judge(conn, DOCS, [STATEMENT], ACTUALS)
        assert t["verdict"] == "missed" and t["checked_by_code"] is True
        assert t["evidence"] == "Margin was 18.9% against 21%."
        assert t["history"][0]["url"].endswith("#page=4")

    def test_thread_without_a_verified_statement_is_dropped(self, conn, reply):
        reply["value"] = {"threads": [thread(statement_ids=["T9-9"])]}
        assert promises.judge(conn, DOCS, [STATEMENT], ACTUALS) == []

    def test_part_year_figure_cannot_settle_a_full_year_target(self, conn, reply):
        reply["value"] = {"threads": [thread(title="FY27 EBITDA margin", period="FY27",
                                             actual_keys=["FY27_YTD.ebitda_margin"], verdict="missed")]}
        (t,) = promises.judge(conn, DOCS, [STATEMENT], ACTUALS)
        assert (t["verdict"], t["progress"]) == ("in_progress", "behind")

    def test_figure_from_another_period_gives_no_ahead_or_behind(self, conn, reply):
        reply["value"] = {"threads": [thread(title="FY29 EBITDA margin", period="FY29", verdict="in_progress",
                                             progress="behind", actual_keys=["FY27_YTD.ebitda_margin"])]}
        (t,) = promises.judge(conn, DOCS, [STATEMENT], ACTUALS)
        assert t["verdict"] == "in_progress" and t["progress"] is None and t["checked_by_code"] is False

    def test_unknown_figure_key_is_never_shown_as_a_number(self, conn, reply):
        reply["value"] = {"threads": [thread(actual_keys=["FY26.made_up"], verdict="unverifiable",
                                             evidence="Capex was {FY26.made_up}.")]}
        (t,) = promises.judge(conn, DOCS, [STATEMENT], ACTUALS)
        assert t["delivered"] == [] and "made_up" not in t["evidence"]

    def test_scorecard_counts_only_settled_promises(self):
        card = promises.scorecard([{"verdict": "delivered"}, {"verdict": "missed"}, {"verdict": "in_progress"}])
        assert (card["settled"], card["kept_pct"]) == (2, 50)


class TestAsk:
    corpus_ = {"symbol": "TEST", "docs": DOCS + [{"id": "AR1", "kind": "annual_report", "label": "Annual report FY26",
                                                  "short": "AR FY26", "url": "https://example.test/ar.pdf"}],
               "pages": PAGES}

    def test_uncited_sentences_are_stripped(self, conn, reply):
        reply["queue"] = [{"queries": ["revenue geography split"]},
                          {"not_disclosed": False, "sentences": [
                              {"text": "Europe is 48.0% of revenue.", "cites": [1]},
                              {"text": "The company is the market leader.", "cites": []},
                              {"text": "It will surely grow.", "cites": [99]}]}]
        out = ask.answer(conn, self.corpus_, ["FY26 revenue growth 10.5%."], "What is the revenue split by geography?")
        assert [s["text"] for s in out["sentences"]] == ["Europe is 48.0% of revenue."]
        assert out["sentences"][0]["cites"][0]["url"].endswith("#page=49")

    def test_nothing_supported_means_not_disclosed(self, conn, reply):
        reply["queue"] = [{"queries": []}, {"not_disclosed": False, "sentences": [{"text": "Guess.", "cites": []}]}]
        out = ask.answer(conn, self.corpus_, [], "How many scooters were sold in Brazil?")
        assert out["not_disclosed"] is True and out["sentences"][0]["text"] == ask.NOT_DISCLOSED
