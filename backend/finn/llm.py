"""The one door every model call goes through.

What it does, in order:
  1. routes the task to a tier (cheap or strong) and the tier to a provider:model;
  2. returns a cached response if this exact (task, model, prompt) was answered before;
  3. otherwise calls the provider with retry and backoff;
  4. logs tokens, cost and latency for every call, cached or not.

Deterministic work (percentages, ratios, thresholds, ranking) never comes here.

Configuration is by environment, so swapping a model is a one-line change:
  GEMINI_API_KEY / GROQ_API_KEY        provider keys (either is enough)
  FINN_CHEAP_MODEL, FINN_STRONG_MODEL  "provider:model", e.g. "gemini:gemini-2.5-flash"
  FINN_MODEL_PRICES                    JSON {"model": [usd_per_1M_input, usd_per_1M_output]}
  FINN_USD_INR                         rate used to show cost in rupees

Check what a key can reach:  python -m finn.llm --check
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import requests

# Which tier each task uses. Cheap is the default; strong only where reasoning is the job.
TASK_TIER: dict[str, str] = {
    "classify": "cheap",           # ambiguous filings, subject line only, batched
    "summarise": "cheap",          # one-line summary of a material filing
    "extract_results": "cheap",    # line items off a P&L page, strict JSON
    "extract_people": "cheap",     # who, role, joining/leaving, profile from the filing
    "extract_guidance": "cheap",   # guidance statements from a transcript
    "expand_query": "cheap",       # search phrasings for a question (retrieval support)
    "promise_verdict": "strong",   # promised vs delivered
    "bull_bear": "strong",         # business snapshot plus the case each way, every point cited
    "qa": "strong",                # cited answers over retrieved excerpts
}

# Starting points only: `python -m finn.llm --check` lists what the key can actually use.
DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "gemini": {"cheap": "gemini-3.5-flash-lite", "strong": "gemini-3.5-flash"},
    "groq": {"cheap": "llama-3.1-8b-instant", "strong": "llama-3.3-70b-versatile"},
}
KEY_ENV = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}

# List prices in USD per 1M tokens (input, output), read from ai.google.dev/gemini-api/docs/pricing
# on 11 Nov 2026. gemini-3.5-flash is inferred from Google's 3.6 release note ("$7.50 versus $9.00 for
# 3.5 Flash; input remains $1.50"). Both are free of charge on the free tier used here; the list price
# is what the same work would cost on a paid key. FINN_MODEL_PRICES overrides this table.
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.5-flash": (1.50, 9.00),
}

MAX_ATTEMPTS = 4
RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class LLMUnavailable(RuntimeError):
    """No provider key configured. Callers skip the model step and degrade gracefully."""


class LLMError(RuntimeError):
    """The provider answered, but not usably (after retries)."""


class Transient(RuntimeError):
    """A failure worth retrying: rate limit, timeout, 5xx."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExhausted(Transient):
    """The provider says to come back much later (a per-day free-tier limit). Retrying now is pointless."""


# A model that reported an exhausted quota is skipped until this time (per process),
# so one daily limit does not cost every later call four doomed attempts.
_exhausted_until: dict[str, float] = {}
QUOTA_COOLDOWN_SECONDS = 15 * 60
LONG_RETRY_SECONDS = 60


@dataclass
class Result:
    text: str
    data: Any            # parsed JSON when json_mode, else None
    task: str
    tier: str
    model: str
    cached: bool
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None


# --- providers: (model, system, prompt, json_mode, max_tokens) -> (text, in_tokens, out_tokens)

def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=120)
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise Transient(str(exc)) from exc
    if resp.status_code in RETRY_STATUS:
        header = resp.headers.get("retry-after")
        retry_after = float(header) if header and header.replace(".", "").isdigit() else None
        if resp.status_code == 429:
            # Gemini puts the wait in the error body: {"retryDelay": "36609s"}.
            try:
                for detail in resp.json().get("error", {}).get("details", []):
                    delay = str(detail.get("retryDelay", ""))
                    if delay.endswith("s") and delay[:-1].replace(".", "").isdigit():
                        retry_after = float(delay[:-1])
            except ValueError:
                pass
            if retry_after is not None and retry_after > LONG_RETRY_SECONDS:
                raise QuotaExhausted(f"HTTP 429: quota exhausted, retry in {retry_after:.0f}s", retry_after)
        raise Transient(f"HTTP {resp.status_code}: {resp.text[:200]}", retry_after)
    if resp.status_code != 200:
        raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _gemini(model: str, system: str | None, prompt: str, json_mode: bool, max_tokens: int) -> tuple[str, int, int]:
    config: dict[str, Any] = {"temperature": 0, "maxOutputTokens": max_tokens}
    if json_mode:
        config["responseMimeType"] = "application/json"
    body: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": config}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                 {"x-goog-api-key": os.environ[KEY_ENV["gemini"]]}, body)
    candidates = data.get("candidates") or []
    parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
    text = "".join(p.get("text", "") for p in parts)
    if not text:
        raise LLMError(f"Empty response from {model}: {json.dumps(data)[:300]}")
    usage = data.get("usageMetadata") or {}
    out_tokens = usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0)
    return text, usage.get("promptTokenCount", 0), out_tokens


def _groq(model: str, system: str | None, prompt: str, json_mode: bool, max_tokens: int) -> tuple[str, int, int]:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = _post("https://api.groq.com/openai/v1/chat/completions",
                 {"Authorization": f"Bearer {os.environ[KEY_ENV['groq']]}"}, body)
    text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
    if not text:
        raise LLMError(f"Empty response from {model}: {json.dumps(data)[:300]}")
    usage = data.get("usage") or {}
    return text, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)


Provider = Callable[[str, "str | None", str, bool, int], "tuple[str, int, int]"]
PROVIDERS: dict[str, Provider] = {"gemini": _gemini, "groq": _groq}


# --- routing --------------------------------------------------------------------------------

def resolve(tier: str) -> tuple[str, str]:
    """(provider, model) for a tier. Explicit env wins; otherwise the first provider with a key."""
    spec = os.environ.get(f"FINN_{tier.upper()}_MODEL", "").strip()
    if spec:
        provider, _, model = spec.partition(":")
        if provider not in PROVIDERS or not model:
            raise LLMUnavailable(f"FINN_{tier.upper()}_MODEL must look like 'provider:model', got {spec!r}")
    else:
        provider = next((p for p, env in KEY_ENV.items() if os.environ.get(env)), "")
        if not provider:
            raise LLMUnavailable("No model key set (GEMINI_API_KEY or GROQ_API_KEY).")
        model = DEFAULT_MODELS[provider][tier]
    env = KEY_ENV.get(provider)
    if env and not os.environ.get(env):
        raise LLMUnavailable(f"{env} is not set.")
    return provider, model


def available(tier: str = "cheap") -> bool:
    try:
        resolve(tier)
        return True
    except LLMUnavailable:
        return False


def prices() -> dict[str, tuple[float, float]]:
    table = dict(DEFAULT_PRICES)
    raw = os.environ.get("FINN_MODEL_PRICES", "").strip()
    if raw:
        try:
            table.update({k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()})
        except (ValueError, TypeError, IndexError):
            pass
    return table


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    price = prices().get(model)
    if price is None:
        return None
    return (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000


def parse_json(text: str) -> Any:
    """Parse a JSON reply, tolerating code fences or prose around the object."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            pass
    raise LLMError(f"Reply was not valid JSON: {text[:200]!r}")


def _log(conn: sqlite3.Connection, r: Result, latency_ms: int) -> None:
    conn.execute(
        "INSERT INTO llm_calls (ts, task, tier, model, cached, prompt_tokens, completion_tokens, cost_usd, latency_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), r.task, r.tier, r.model, int(r.cached),
         r.prompt_tokens, r.completion_tokens, r.cost_usd, latency_ms))
    conn.commit()


def complete(conn: sqlite3.Connection, task: str, prompt: str, *, system: str | None = None,
             json_mode: bool = True, max_tokens: int = 1024,
             sleep: Callable[[float], None] = time.sleep) -> Result:
    if task not in TASK_TIER:
        raise ValueError(f"Unknown task {task!r}; add it to TASK_TIER so its tier is a deliberate choice.")
    tier = TASK_TIER[task]
    provider, model = resolve(tier)
    key = hashlib.sha256("\x1f".join([task, provider, model, system or "", prompt]).encode("utf-8")).hexdigest()

    row = conn.execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
    if row is not None:
        text = row[0]
        result = Result(text, parse_json(text) if json_mode else None, task, tier, model, True, 0, 0, 0.0)
        _log(conn, result, 0)
        return result

    started = time.time()

    def attempt(prov: str, mod: str, attempts: int) -> tuple[str, int, int, Any]:
        """Call one model with retry and backoff; raises the last error when every attempt fails."""
        if _exhausted_until.get(mod, 0) > time.time():
            raise QuotaExhausted(f"{mod} quota was exhausted moments ago; not retrying yet")
        last: Exception = LLMError("no attempt made")
        for n in range(attempts):
            try:
                text, tokens_in, tokens_out = PROVIDERS[prov](mod, system, prompt, json_mode, max_tokens)
                return text, tokens_in, tokens_out, (parse_json(text) if json_mode else None)
            except QuotaExhausted as exc:
                _exhausted_until[mod] = time.time() + QUOTA_COOLDOWN_SECONDS
                raise exc
            except Transient as exc:
                last = exc
                if n < attempts - 1:
                    sleep(min(exc.retry_after, 30.0) if exc.retry_after is not None else 2.0 * (2 ** n))
            except LLMError as exc:
                last = exc  # malformed or empty reply: one more try is cheap, a wrong card is not
                if n < attempts - 1:
                    sleep(1.0)
        raise last

    used = model
    try:
        text, tokens_in, tokens_out, data = attempt(provider, model, MAX_ATTEMPTS)
    except (Transient, LLMError) as first:
        # The strong model is overloaded or out of quota: answer with the cheap model rather
        # than fail the user. The result records which model actually answered, and it is not
        # cached, so a later call tries the strong model again.
        fallback = _fallback(tier, provider, model) if isinstance(first, Transient) else None
        if fallback is None:
            raise LLMError(f"{task} failed after {MAX_ATTEMPTS} attempts on {model}: {first}") from first
        try:
            text, tokens_in, tokens_out, data = attempt(fallback[0], fallback[1], 3)
        except (Transient, LLMError) as second:
            raise LLMError(f"{task} failed on {model} ({str(first)[:80]}) and on fallback {fallback[1]} "
                           f"({str(second)[:120]})") from second
        used = fallback[1]

    result = Result(text, data, task, tier, used, False, tokens_in, tokens_out, cost_usd(used, tokens_in, tokens_out))
    if used == model:
        conn.execute("INSERT OR REPLACE INTO llm_cache (key, task, model, response, created_at) VALUES (?, ?, ?, ?, ?)",
                     (key, task, model, text, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    _log(conn, result, int((time.time() - started) * 1000))
    return result


def _fallback(tier: str, provider: str, model: str) -> tuple[str, str] | None:
    """The cheap tier's model, when a strong-tier call has exhausted its retries."""
    if tier != "strong":
        return None
    try:
        cheap = resolve("cheap")
    except LLMUnavailable:
        return None
    return None if cheap == (provider, model) else cheap


def stats(conn: sqlite3.Connection) -> dict:
    """Totals plus a per-task breakdown, for the Brief footer, /api/stats and the README table."""
    rate = float(os.environ.get("FINN_USD_INR", "0") or 0)
    rows = conn.execute(
        "SELECT task, tier, model, COUNT(*) calls, SUM(cached) cached, SUM(prompt_tokens) tin, "
        "SUM(completion_tokens) tout, SUM(cost_usd) cost, SUM(cost_usd IS NULL AND cached = 0) unpriced "
        "FROM llm_calls GROUP BY task, tier, model ORDER BY task").fetchall()
    table = prices()
    by_task = []
    for r in rows:
        price = table.get(r["model"])
        tin, tout = r["tin"] or 0, r["tout"] or 0
        by_task.append({
            "task": r["task"], "tier": r["tier"], "model": r["model"], "calls": r["calls"], "cached": r["cached"] or 0,
            "prompt_tokens": tin, "completion_tokens": tout,
            # Priced from tokens and the current list-price table; None when the model has no listed price.
            "cost_usd": round((tin * price[0] + tout * price[1]) / 1_000_000, 6) if price else None,
            "unpriced_calls": 0 if price or (tin + tout) == 0 else r["calls"],
        })
    total_cost = sum(t["cost_usd"] or 0.0 for t in by_task)
    priced = all(t["unpriced_calls"] == 0 for t in by_task)
    return {
        "calls": sum(t["calls"] for t in by_task),
        "cached": sum(t["cached"] for t in by_task),
        "tokens": sum(t["prompt_tokens"] + t["completion_tokens"] for t in by_task),
        "cost_usd": round(total_cost, 6) if priced else None,
        "cost_inr": round(total_cost * rate, 4) if priced and rate else None,
        "usd_inr": rate or None,
        "by_task": by_task,
    }


def check() -> int:
    """List the models each configured key can reach and whether the routed ones are among them."""
    found = False
    for provider, env in KEY_ENV.items():
        key = os.environ.get(env)
        if not key:
            print(f"{provider}: {env} not set")
            continue
        found = True
        try:
            if provider == "gemini":
                resp = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                                    headers={"x-goog-api-key": key}, params={"pageSize": 200}, timeout=30)
                names = [m["name"].split("/")[-1] for m in resp.json().get("models", [])
                         if "generateContent" in m.get("supportedGenerationMethods", [])]
            else:
                resp = requests.get("https://api.groq.com/openai/v1/models",
                                    headers={"Authorization": f"Bearer {key}"}, timeout=30)
                names = [m["id"] for m in resp.json().get("data", [])]
        except Exception as exc:  # noqa: BLE001
            print(f"{provider}: could not list models ({exc})")
            continue
        print(f"{provider}: HTTP {resp.status_code}, {len(names)} models: {', '.join(sorted(names))}")
    for tier in ("cheap", "strong"):
        try:
            provider, model = resolve(tier)
            print(f"routed {tier}: {provider}:{model}")
        except LLMUnavailable as exc:
            print(f"routed {tier}: unavailable ({exc})")
    return 0 if found else 1


if __name__ == "__main__":
    if "--check" in sys.argv:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass
        raise SystemExit(check())
