"""The router's own behaviour, tested against a fake provider: no network, no key."""
import sqlite3

import pytest

from finn import db, llm


@pytest.fixture
def conn():
    return db.init(sqlite3.connect(":memory:"))


@pytest.fixture
def fake(monkeypatch):
    """A provider that records calls and replies with whatever the test queues up."""
    calls: list[tuple] = []
    replies: list = []

    def provider(model, system, prompt, json_mode, max_tokens):
        calls.append((model, prompt))
        reply = replies.pop(0) if replies else ('{"ok": true}', 100, 20)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setitem(llm.PROVIDERS, "fake", provider)
    monkeypatch.setenv("FINN_CHEAP_MODEL", "fake:small")
    monkeypatch.setenv("FINN_STRONG_MODEL", "fake:large")
    monkeypatch.delenv("FINN_MODEL_PRICES", raising=False)
    return calls, replies


def test_task_routes_to_its_tier(conn, fake):
    assert llm.complete(conn, "classify", "p").model == "small"
    assert llm.complete(conn, "promise_verdict", "p").model == "large"


def test_unknown_task_is_refused(conn, fake):
    with pytest.raises(ValueError):
        llm.complete(conn, "write_poem", "p")


def test_identical_call_is_served_from_cache_and_costs_nothing(conn, fake):
    calls, _ = fake
    first = llm.complete(conn, "classify", "same prompt")
    second = llm.complete(conn, "classify", "same prompt")
    assert len(calls) == 1
    assert (first.cached, second.cached) == (False, True)
    assert (second.prompt_tokens, second.completion_tokens) == (0, 0)
    assert second.data == {"ok": True}


def test_cache_is_per_task_and_per_prompt(conn, fake):
    calls, _ = fake
    llm.complete(conn, "classify", "a")
    llm.complete(conn, "classify", "b")
    llm.complete(conn, "summarise", "a")
    assert len(calls) == 3


def test_transient_failure_is_retried_with_backoff(conn, fake):
    calls, replies = fake
    replies.extend([llm.Transient("HTTP 429"), llm.Transient("HTTP 503"), ('{"n": 1}', 10, 5)])
    waits: list[float] = []
    result = llm.complete(conn, "classify", "p", sleep=waits.append)
    assert result.data == {"n": 1} and len(calls) == 3
    assert waits == [2.0, 4.0]


def test_rate_limit_retry_after_is_honoured(conn, fake):
    _, replies = fake
    replies.extend([llm.Transient("HTTP 429", retry_after=7.0), ('{"n": 1}', 10, 5)])
    waits: list[float] = []
    llm.complete(conn, "classify", "p", sleep=waits.append)
    assert waits == [7.0]


def test_gives_up_after_max_attempts_and_caches_nothing(conn, fake):
    calls, replies = fake
    replies.extend([llm.Transient("down")] * llm.MAX_ATTEMPTS)
    with pytest.raises(llm.LLMError):
        llm.complete(conn, "classify", "p", sleep=lambda s: None)
    assert len(calls) == llm.MAX_ATTEMPTS
    assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0


def test_malformed_json_is_retried_then_accepted(conn, fake):
    _, replies = fake
    replies.extend([("not json at all", 10, 5), ('```json\n{"n": 2}\n```', 10, 5)])
    assert llm.complete(conn, "classify", "p", sleep=lambda s: None).data == {"n": 2}


def test_cost_uses_the_configured_price_table(conn, fake, monkeypatch):
    monkeypatch.setenv("FINN_MODEL_PRICES", '{"small": [0.10, 0.40]}')
    monkeypatch.setenv("FINN_USD_INR", "90")
    result = llm.complete(conn, "classify", "p")  # 100 in, 20 out
    assert result.cost_usd == pytest.approx((100 * 0.10 + 20 * 0.40) / 1_000_000)
    totals = llm.stats(conn)
    assert totals["tokens"] == 120 and totals["calls"] == 1
    assert totals["cost_inr"] == pytest.approx(result.cost_usd * 90, abs=1e-4)


def test_unpriced_model_reports_tokens_but_no_invented_cost(conn, fake):
    llm.complete(conn, "classify", "p")
    totals = llm.stats(conn)
    assert totals["tokens"] == 120 and totals["cost_usd"] is None


def test_stats_count_cache_hits(conn, fake):
    llm.complete(conn, "classify", "p")
    llm.complete(conn, "classify", "p")
    totals = llm.stats(conn)
    assert (totals["calls"], totals["cached"], totals["tokens"]) == (2, 1, 120)


def test_no_key_means_unavailable_not_a_crash(monkeypatch):
    for name in ("FINN_CHEAP_MODEL", "FINN_STRONG_MODEL", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert llm.available("cheap") is False
    with pytest.raises(llm.LLMUnavailable):
        llm.resolve("cheap")


def test_strong_tier_outage_falls_back_to_the_cheap_model(conn, fake):
    calls, replies = fake
    replies.extend([llm.Transient("HTTP 503")] * llm.MAX_ATTEMPTS + [('{"from": "cheap"}', 30, 5)])
    result = llm.complete(conn, "qa", "question", sleep=lambda s: None)
    assert result.data == {"from": "cheap"} and result.model == "small"
    assert [m for m, _ in calls] == ["large"] * llm.MAX_ATTEMPTS + ["small"]
    # not cached: the next call should try the strong model again
    assert conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0] == 0


def test_cheap_tier_has_no_fallback(conn, fake):
    _, replies = fake
    replies.extend([llm.Transient("HTTP 503")] * llm.MAX_ATTEMPTS)
    with pytest.raises(llm.LLMError):
        llm.complete(conn, "classify", "p", sleep=lambda s: None)


def test_exhausted_daily_quota_skips_retries_and_goes_to_fallback(conn, fake):
    calls, replies = fake
    llm._exhausted_until.clear()
    replies.extend([llm.QuotaExhausted("HTTP 429", retry_after=36000), ('{"from": "cheap"}', 30, 5)])
    waits: list[float] = []
    result = llm.complete(conn, "qa", "q1", sleep=waits.append)
    assert result.model == "small" and waits == []          # no pointless waiting on a per-day limit
    assert [m for m, _ in calls] == ["large", "small"]
    # while the cooldown lasts, the exhausted model is not even tried
    replies.append(('{"from": "cheap"}', 30, 5))
    llm.complete(conn, "qa", "q2", sleep=waits.append)
    assert [m for m, _ in calls] == ["large", "small", "small"]
    llm._exhausted_until.clear()
