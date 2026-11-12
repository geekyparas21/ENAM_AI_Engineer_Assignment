"""Unit tests for the deterministic core: alerts, results maths, titles, rules."""
from finn import alerts
from finn.classify import AMBIGUOUS, classify
from finn.prioritise import reaction_day, score
from finn.results import build_card, pct_change
from finn.titles import clean_title, fiscal_period

# KPIT Technologies, consolidated, Q2 FY27 (Rs million), read from p.9 of the results
# filing dated 28 Oct 2026: KPITTECH_28102026124748_Outcome_NSE.pdf
KPIT = {
    "basis": "Consolidated", "unit": "million",
    "cur": {"revenue": 16909.66, "other_income": 81.32, "finance_costs": 214.46, "depreciation": 859.13,
            "pbt": 1680.37, "tax": 473.80, "pat": 1206.57},
    "prev": {"revenue": 16749.94, "other_income": 83.38, "finance_costs": 229.51, "depreciation": 825.37,
             "pbt": 1602.98, "tax": 438.86, "pat": 1164.12},
    "yoy": {"revenue": 15877.11, "other_income": 235.79, "finance_costs": 162.51, "depreciation": 747.06,
            "pbt": 2305.65, "tax": 614.78, "pat": 1690.87},
}


def day(**kw):
    base = {"symbol": "X", "date": "2026-11-06", "close": 100.0, "prev_close": 100.0,
            "pct_change": 0.0, "volume": 1000, "avg_vol_20": 1000.0}
    return {**base, **kw}


class TestAlerts:
    def test_quiet_day_fires_nothing(self):
        assert alerts.evaluate([day()]) == []

    def test_price_threshold_is_inclusive_and_two_sided(self):
        assert [a["type"] for a in alerts.evaluate([day(pct_change=5.0)])] == ["price"]
        assert [a["type"] for a in alerts.evaluate([day(pct_change=-5.0)])] == ["price"]
        assert alerts.evaluate([day(pct_change=4.99)]) == []

    def test_volume_alert_reports_ratio_and_baseline(self):
        (a,) = alerts.evaluate([day(volume=2600, avg_vol_20=1000.0)])
        assert (a["type"], a["value"], a["baseline"], a["threshold"]) == ("volume", 2.6, 1000.0, 2.0)

    def test_user_thresholds_change_what_fires(self):
        rows = [day(pct_change=3.0, volume=1500)]
        assert alerts.evaluate(rows) == []
        assert {a["type"] for a in alerts.evaluate(rows, volume_multiple=1.5, price_move_pct=3.0)} == {"price", "volume"}

    def test_missing_baseline_never_fires_volume(self):
        assert alerts.evaluate([day(volume=5000, avg_vol_20=None)]) == []


class TestResultsMaths:
    card = build_card(KPIT, period="Q2 FY27", page=9)

    def test_converted_to_crore(self):
        assert self.card["metrics"]["revenue"]["cur"] == 1690.97
        assert self.card["metrics"]["pat"]["cur"] == 120.66

    def test_growth_rates(self):
        rev, pat = self.card["metrics"]["revenue"], self.card["metrics"]["pat"]
        assert (rev["qoq_pct"], rev["yoy_pct"]) == (1.0, 6.5)
        assert (pat["qoq_pct"], pat["yoy_pct"]) == (3.6, -28.6)

    def test_ebitda_is_pbt_plus_finance_plus_da_minus_other_income(self):
        # (1680.37 + 214.46 + 859.13 - 81.32) / 10 = 267.264
        assert self.card["metrics"]["ebitda"]["cur"] == 267.26
        assert self.card["margins"]["ebitda"]["cur"] == 15.8

    def test_margin_deltas_are_percentage_points(self):
        m = self.card["margins"]["pat"]
        assert m["yoy_pct"] == round(m["cur"] - m["yoy"], 1)

    def test_pbt_minus_tax_equals_pat_passes(self):
        assert all(c["ok"] for c in self.card["checks"])

    def test_misread_number_is_flagged_not_hidden(self):
        bad = {**KPIT, "cur": {**KPIT["cur"], "pat": 2206.57}}
        assert any(not c["ok"] for c in build_card(bad)["checks"])

    def test_lender_has_no_ebitda(self):
        bank = {"basis": "Consolidated", "unit": "crore",
                "cur": {"revenue": 100.0, "pbt": 30.0, "tax": 8.0, "pat": 22.0},
                "prev": {"revenue": 90.0, "pbt": 28.0, "tax": 7.0, "pat": 21.0},
                "yoy": {"revenue": 80.0, "pbt": 20.0, "tax": 5.0, "pat": 15.0}}
        assert build_card(bank)["metrics"]["ebitda"]["cur"] is None

    def test_growth_off_a_loss_is_undefined(self):
        assert pct_change(50.0, -10.0) is None
        assert pct_change(50.0, 0.0) is None


class TestTitles:
    def test_fiscal_period(self):
        assert fiscal_period("financial results for the period ended September 30, 2026") == "Q2 FY27"
        assert fiscal_period("quarter and half year ended 30 September 2026") == "Q2 FY27"
        assert fiscal_period("year ended March 31, 2027") == "Q4 FY27"
        assert fiscal_period("Board meeting held on November 02, 2026") is None

    def test_boilerplate_is_stripped(self):
        assert clean_title("Titan Company Limited has informed the Exchange about Redemption of Commercial Paper",
                           "General Updates") == "Redemption of Commercial Paper"
        assert clean_title("Bharti Airtel Limited has informed the Exchange regarding 'Updates'.", "Updates") == "Updates"


class TestRules:
    def test_results_filing_beats_newspaper_ad(self):
        filing = classify("Outcome of Board Meeting",
                          "X has submitted to the Exchange, the financial results for the period ended September 30, 2026.")
        ad = classify("Copy of Newspaper Publication", "Newspaper publication for Unaudited financial results")
        assert (filing.category, filing.kind) == ("results", "filing")
        assert (ad.category, ad.kind) == ("results", "newspaper_ad")

    def test_transcript_is_earnings_call_and_meet_is_investor_meeting(self):
        exch = "Analysts/Institutional Investor Meet/Con. Call Updates"
        assert classify(exch, "Transcript of the discussion on the results").category == "earnings_call"
        assert classify(exch, "X has informed the Exchange about Schedule of meet").category == "investor_meetings"

    def test_esop_allotment_is_paperwork_but_qip_is_fund_raise(self):
        assert classify("Allotment of Securities", "allotment of 37750 securities pursuant to ESOP/ESPS").category == "unclassified"
        assert classify("Allotment of Securities", "allotment of 7683981 securities pursuant to Qualified Institution Placement").category == "fund_raise"

    def test_unknown_goes_to_the_model_and_empty_boilerplate_does_not(self):
        assert classify("General Updates", "Proposed Initial Public Offer of Jio Platforms Limited").category == AMBIGUOUS
        assert classify("General Updates", "Tata Power Company Limited has informed the Exchange about General Updates").category == "unclassified"


class TestRanking:
    days = {"2026-11-05": {"pct_change": 0.2, "vol_ratio": 1.0}, "2026-11-06": {"pct_change": -9.7, "vol_ratio": 13.2}}

    def test_after_close_filing_reacts_next_session(self):
        assert reaction_day("2026-11-05T18:10:00+05:30", sorted(self.days)) == "2026-11-06"
        assert reaction_day("2026-11-05T11:00:00+05:30", sorted(self.days)) == "2026-11-05"
        assert reaction_day("2026-11-06T18:00:00+05:30", sorted(self.days)) is None

    def test_market_reaction_lifts_a_material_filing(self):
        s, reasons, move = score("results", "filing", "", "2026-11-05T18:10:00+05:30", self.days)
        assert s == 112.5 and move["date"] == "2026-11-06" and "Stock reacted" in reasons[-1]

    def test_newspaper_ad_is_routine_even_inside_results(self):
        s, _, _ = score("results", "newspaper_ad", "", "2026-11-05T18:10:00+05:30", self.days)
        assert s < 35


class TestSizeAwareRanking:
    def test_amounts_are_read_in_any_indian_unit(self):
        from finn.prioritise import largest_amount_crore
        assert largest_amount_crore("penalty notices totaling Rs. 2,62,000 from the DoT") == 0.0262
        assert largest_amount_crore("commercial paper worth Rs. 200 crores") == 200.0
        assert largest_amount_crore("tax of Rs. 1,91,873 and penalty of Rs. 82,00,747") == 0.8200747
        assert largest_amount_crore("aggregating to INR 70 billion") == 7000.0
        assert largest_amount_crore("NCLAT set aside the order") is None

    def test_trivial_penalty_is_demoted_to_routine_but_a_large_one_is_not(self):
        small, reasons, _ = score("litigation", None, "", "2026-11-05T11:00:00+05:30", {}, "Received a penalty notice of Rs. 1,07,000.")
        large, _, _ = score("litigation", None, "", "2026-11-05T11:00:00+05:30", {}, "GST demand of Rs. 240 crore.")
        unknown, _, _ = score("litigation", None, "", "2026-11-05T11:00:00+05:30", {}, "NCLAT set aside the order.")
        assert small == 30.0 and "under ₹1 crore" in reasons[-1]
        assert large == 75.0 and unknown == 75.0


class TestPriceRows:
    """Yahoo publishes the newest session's volume before its close settles. That row has
    Volume > 0 and Close NaN, and storing it violates prices.close NOT NULL, which used to
    fail the whole symbol's executemany and so lose every price in the run."""

    @staticmethod
    def _frame(closes):
        import pandas as pd
        idx = pd.to_datetime([f"2026-11-{d:02d} 00:00:00+05:30" for d in range(2, 2 + len(closes))])
        return pd.DataFrame(
            {"Open": [100.0] * len(closes), "High": [101.0] * len(closes),
             "Low": [99.0] * len(closes), "Close": closes, "Adj Close": closes,
             "Volume": [1_000] * len(closes), "Dividends": [0.0] * len(closes),
             "Stock Splits": [0.0] * len(closes)},
            index=idx,
        )

    def _fetch(self, monkeypatch, closes):
        from finn.sources import prices
        frame = self._frame(closes)
        monkeypatch.setattr(prices.yf, "Ticker",
                            lambda _sym: type("T", (), {"history": lambda _s, **_k: frame})())
        return prices.fetch_prices("RELIANCE")

    def test_an_unsettled_close_is_dropped_not_stored_as_null(self, monkeypatch):
        rows = self._fetch(monkeypatch, [100.0, 102.0, float("nan")])
        assert [r["date"] for r in rows] == ["2026-11-02", "2026-11-03"]
        assert all(r["close"] is not None and r["close"] == r["close"] for r in rows)

    def test_a_dropped_row_does_not_become_the_next_days_prev_close(self, monkeypatch):
        rows = self._fetch(monkeypatch, [100.0, float("nan"), 110.0])
        last = rows[-1]
        assert last["date"] == "2026-11-04" and last["prev_close"] == 100.0
        assert last["pct_change"] == 10.0

    def test_every_close_missing_yields_no_rows_rather_than_null_rows(self, monkeypatch):
        assert self._fetch(monkeypatch, [float("nan"), float("nan")]) == []
