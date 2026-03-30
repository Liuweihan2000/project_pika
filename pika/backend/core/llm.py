import json
import time
import threading
import anthropic
from urllib import request as urlrequest
from backend.core.config import config

# ---------------------------------------------------------------------------
# Global LLM rate limiter (token bucket)
# Gemini free tier: 15 RPM — we stay under configured RPM to leave headroom
# ---------------------------------------------------------------------------

_rate_lock      = threading.Lock()
_rate_last_call = 0.0

def _rate_wait():
    """Block until it's safe to make another LLM call."""
    global _rate_last_call
    min_gap = 60.0 / config.llm_rate_limit_rpm  # seconds between calls
    with _rate_lock:
        now  = time.time()
        wait = min_gap - (now - _rate_last_call)
        if wait > 0:
            time.sleep(wait)
        _rate_last_call = time.time()

# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _llm_gemini(system: str, user: str, temperature: float) -> str:
    """Call Gemini. Raises on any error."""
    if not config.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    url = (
        f"https://generativelanguage.googleapis.com/{config.gemini_model}"
        f"?key={config.gemini_api_key}"
    )
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 400,
        },
    }
    req = urlrequest.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=config.llm_timeout) as r:
        data = json.loads(r.read().decode())
    parts = (
        (data.get("candidates") or [{}])[0]
        .get("content", {})
        .get("parts") or []
    )
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError("empty response")
    return text

# ---------------------------------------------------------------------------
# MiniMax
# ---------------------------------------------------------------------------

def _llm_minimax(system: str, user: str, temperature: float) -> str:
    """Call MiniMax via Anthropic SDK (base_url pointed at MiniMax). Raises on any error."""
    if not config.minimax_api_key:
        raise RuntimeError("MINIMAX_API_KEY not set")
    client = anthropic.Anthropic(
        api_key=config.minimax_api_key
    )
    message = client.messages.create(
        model=config.minimax_model,
        max_tokens=1500,
        system=system,
        messages=[
            {"role": "user", "content": [{"type": "text", "text": user}]}
        ],
        temperature=temperature
    )
    blocks = getattr(message, "content", None) or []
    parts = []
    for b in blocks:
        t = getattr(b, "text", None)
        if isinstance(t, str) and t:
            parts.append(t)
            continue
        if isinstance(b, dict):
            if b.get("type") == "text" and isinstance(b.get("text"), str) and b.get("text"):
                parts.append(b["text"])
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError("empty response from MiniMax")
    return text

# ---------------------------------------------------------------------------
# General LLM Call
# ---------------------------------------------------------------------------

def llm(system: str, user: str, temperature: float = 0.9) -> str:
    """Try Gemini first; fall back to MiniMax if Gemini fails for any reason."""
    _rate_wait()
    errors = []

    if config.gemini_api_key:
        try:
            return _llm_gemini(system, user, temperature)
        except Exception as e:
            errors.append(f"Gemini: {e}")
            print(f"[llm] Gemini failed ({e}), falling back to MiniMax...")

    if config.minimax_api_key:
        try:
            return _llm_minimax(system, user, temperature)
        except Exception as e:
            print("Minimax err: ", e)
            errors.append(f"MiniMax: {e}")

    raise RuntimeError("All LLM backends failed (Gemini → MiniMax) — " + " | ".join(errors))
