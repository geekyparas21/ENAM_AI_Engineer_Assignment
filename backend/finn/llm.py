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
    "promise_verdict": "strong",   # promised vs delivered
    "bull_bear": "strong",
    "qa": "strong",                # cited answers over retrieved excerpts
}

# Starting points only: `python -m finn.llm --check` lists what the key can actually use.
DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "gemini": {"cheap": "gemini-2.5-flash-lite", "strong": "gemini-2.5-pro"},
    "groq": {"cheap": "llama-3.1-8b-instant", "strong": "llama-3.3-70b-versatile"},
}
KEY_ENV = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY"}

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
        retry_after = resp.headers.get("retry-after")
        raise Transient(f"HTTP {resp.status_code}: {resp.text[:200]}",
                        float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else None)
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
    raw = os.environ.get("FINN_MODEL_PRICES", "").strip()
    if not raw:
        return {}
    try:
        return {k: (float(v[0]), float(v[1])) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError, IndexError):
        return {}


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
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            text, tokens_in, tokens_out = PROVIDERS[provider](model, system, prompt, json_mode, max_tokens)
            data = parse_json(text) if json_mode else None
            break
        except Transient as exc:
            last = exc
            if attempt < MAX_ATTEMPTS - 1:
                sleep(exc.retry_after if exc.retry_after is not None else 2.0 * (2 ** attempt))
        except LLMError as exc:
            last = exc  # malformed or empty reply: one more try is cheap, a wrong card is not
            if attempt < MAX_ATTEMPTS - 1:
                sleep(1.0)
    else:
        raise LLMError(f"{task} failed after {MAX_ATTEMPTS} attempts on {model}: {last}")

    result = Result(text, data, task, tier, model, False, tokens_in, tokens_out,
                    cost_usd(model, tokens_in, tokens_out))
    conn.execute("INSERT OR REPLACE INTO llm_cache (key, task, model, response, created_at) VALUES (?, ?, ?, ?, ?)",
                 (key, task, model, text, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    _log(conn, result, int((time.time() - started) * 1000))
    return result


def stats(conn: sqlite3.Connection) -> dict:
    """Totals plus a per-task breakdown, for the Brief footer, /api/stats and the README table."""
    rate = float(os.environ.get("FINN_USD_INR", "0") or 0)
    rows = conn.execute(
        "SELECT task, tier, model, COUNT(*) calls, SUM(cached) cached, SUM(prompt_tokens) tin, "
        "SUM(completion_tokens) tout, SUM(cost_usd) cost, SUM(cost_usd IS NULL AND cached = 0) unpriced "
        "FROM llm_calls GROUP BY task, tier, model ORDER BY task").fetchall()
    by_task = [{
        "task": r["task"], "tier": r["tier"], "model": r["model"], "calls": r["calls"], "cached": r["cached"] or 0,
        "prompt_tokens": r["tin"] or 0, "completion_tokens": r["tout"] or 0,
        "cost_usd": r["cost"], "unpriced_calls": r["unpriced"] or 0,
    } for r in rows]
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
