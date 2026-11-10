"""Validation around the model steps: what the model returns is never trusted as-is."""
import json
import sqlite3

import pytest

from finn import db, llm, llm_tasks
from finn.enrich import people_line
from finn.results import build_card, card_from_screener, cross_check, period_to_column, summary_line


@pytest.fixture
def conn():
    return db.init(sqlite3.connect(":memory:"))


@pytest.fixture
def reply(monkeypatch):
    """Make the model answer with a fixed JSON value."""
    box: dict = {}

    def provider(model, system, prompt, json_mode, max_tokens):
        box["prompt"] = prompt
        return json.dumps(box["value"]), 50, 10

    monkeypatch.setitem(llm.PROVIDERS, "fake", provider)
    monkeypatch.setenv("FINN_CHEAP_MODEL", "fake:small")
    return box


class TestClassifyStage2:
    items = [{"id": "NSE-1", "exch_category": "General Updates", "subject": "Proposed IPO of Jio Platforms"},
             {"id": "NSE-2", "exch_category": "Updates", "subject": "Award winners announced"},
             {"id": "NSE-3", "exch_category": "Updates", "subject": "Something else"}]

    def test_labels_map_back_to_exchange_ids(self, conn, reply):
        reply["value"] = {"labels": [{"id": "1", "category": "M&A"}, {"id": "2", "category": "press_release"},
                                     {"id": "3", "category": "unclassified"}]}
        assert llm_tasks.classify_batch(conn, self.items) == {
            "NSE-1": "M&A", "NSE-2": "press_release", "NSE-3": "unclassified"}

    def test_invented_category_and_skipped_item_become_unclassified(self, conn, reply):
        reply["value"] = {"labels": [{"id": "1", "category": "ipo_news"}, {"id": "2", "category": "press_release"}]}
        out = llm_tasks.classify_batch(conn, self.items)
        assert out["NSE-1"] == "unclassified" and out["NSE-3"] == "unclassified"

    def test_only_the_subject_is_sent(self, conn, reply):
        reply["value"] = {"labels": []}
        llm_tasks.classify_batch(conn, self.items)
        sent = json.loads(reply["prompt"])
        assert set(sent[0]) == {"id", "exchange_category", "subject"}


class TestResultsExtraction:
    def test_printed_figures_are_coerced(self):
        assert llm_tasks.to_number("16,909.66") == 16909.66
        assert llm_tasks.to_number("(101.94)") == -101.94
        assert llm_tasks.to_number("{101.94)") == -101.94   # OCR turns a bracket into a brace
        assert llm_tasks.to_number(214.46) == 214.46

    def test_ocr_garbage_becomes_empty_not_a_wrong_number(self):
        assert llm_tasks.to_number("11.102.55") is None
        assert llm_tasks.to_number("n/a") is None

    def test_extraction_without_revenue_is_rejected(self):
        with pytest.raises(llm.LLMError):
            llm_tasks.clean_results({"basis": "Consolidated", "unit": "crore", "cur": {"pat": 10}}, None)

    def test_extractor_feeds_the_card_maths(self, conn, reply):
        col = {"revenue": "16,909.66", "other_income": "81.32", "finance_costs": "214.46", "depreciation": "859.13",
               "pbt": "1,680.37", "tax": "473.80", "pat": "1,206.57"}
        reply["value"] = {"basis": "Consolidated", "unit": "million", "cur": col, "prev": col, "yoy": col}
        card = build_card(llm_tasks.results_extractor(conn)("page text", "Consolidated"), "Q2 FY27", 9)
        assert card["metrics"]["revenue"]["cur"] == 1690.97 and card["source"] == "filing"


class TestScreenerLeg:
    company = {"basis": "Consolidated", "quarters": {
        "columns": ["Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"],
        "rows": {"Sales": [1588.0, 1617.0, 1711.0, 1675.0, 1691.0],
                 "Operating Profit": [298.0, 311.0, 317.0, 257.0, 267.0],
                 "Profit before tax": [231.0, 181.0, 225.0, 160.0, 168.0],
                 "Net Profit": [169.0, 133.0, 163.0, 116.0, 121.0]}}}

    def test_period_maps_to_screener_column(self):
        assert period_to_column("Q2 FY27") == "Sep 2026"
        assert period_to_column("Q4 FY27") == "Mar 2027"
        assert period_to_column("Q3 FY26") == "Dec 2025"

    def test_fallback_card_says_where_its_numbers_came_from(self):
        card = card_from_screener(self.company, "Q2 FY27", "The results filing is an image-only scan.")
        assert card["source"] == "screener" and "image-only scan" in card["source_note"]
        assert card["metrics"]["revenue"]["yoy_pct"] == 6.5 and card["metrics"]["revenue"]["qoq_pct"] == 1.0

    def test_quarter_missing_from_screener_gives_no_card(self):
        assert card_from_screener(self.company, "Q3 FY27", "x") is None

    def test_cross_check_passes_on_rounding_and_fails_on_a_real_gap(self):
        good = {"basis": "Consolidated", "metrics": {"revenue": {"cur": 1690.97}, "pat": {"cur": 120.66}}}
        bad = {"basis": "Consolidated", "metrics": {"revenue": {"cur": 1690.97}, "pat": {"cur": 220.66}}}
        assert all(c["ok"] for c in cross_check(good, self.company, "Q2 FY27"))
        assert [c["ok"] for c in cross_check(bad, self.company, "Q2 FY27")] == [True, False]

    def test_takeaway_names_the_divergence(self):
        card = card_from_screener(self.company, "Q2 FY27", "x")
        line = summary_line(card)
        assert line.startswith("Q2 FY27: Revenue up 6.5% YoY but PAT down 28.4%")
        assert "EBITDA margin compressed" in line


class TestPeople:
    def test_honorifics_stripped_and_unknown_action_not_invented(self, conn, reply):
        reply["value"] = {"people": [
            {"name": "Mr. Noel N. Tata", "role": "Director and Vice-Chairman", "action": "retired",
             "effective": "November 5, 2026", "bio": None},
            {"name": "", "role": "CFO", "action": "appointed"},
            {"name": "Dr. A. Rao", "role": None, "action": "promoted sideways", "bio": "30 years at X."}]}
        people = llm_tasks.extract_people(conn, "Change in Directors", "text")
        assert [p["name"] for p in people] == ["Noel N. Tata", "A. Rao"]
        assert people[1]["action"] == "changed" and people[1]["role"] == "Role not stated"
        assert people[0]["bio"] is None and people[1]["bio_source"] == "the filing"

    def test_people_line(self):
        people = [{"name": "A", "action": "appointed", "role": "CFO"}, {"name": "B", "action": "resigned", "role": "CEO"},
                  {"name": "C", "action": "retired", "role": "Director"}]
        assert people_line(people) == "A appointed as CFO; B resigned as CEO (+1 more)"


def test_summary_null_means_no_summary(conn, reply):
    reply["value"] = {"summary": None, "amount_cr": None}
    assert llm_tasks.summarise(conn, "M&A", "Disclosure under Regulation 30", "text") is None
    reply["value"] = {"summary": "Acquires 51% of X for Rs 240 crore", "amount_cr": "240"}
    assert llm_tasks.summarise(conn, "M&A", "Acquisition", "other text") == {
        "summary": "Acquires 51% of X for Rs 240 crore", "amount_cr": 240.0}
