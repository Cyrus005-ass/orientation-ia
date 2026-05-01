from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT_DIR = Path("knowledge/live")
OUT_FILE = OUT_DIR / "agent_intel.json"


def _http_get_json(url: str, timeout: int = 20) -> Any:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _binance_ratio(endpoint: str, symbol: str, period: str = "5m", limit: int = 30) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"symbol": symbol, "period": period, "limit": limit})
    url = f"https://fapi.binance.com/futures/data/{endpoint}?{qs}"
    rows = _http_get_json(url)
    if not isinstance(rows, list) or not rows:
        return {"symbol": symbol, "endpoint": endpoint, "ok": False, "error": "empty"}

    latest = rows[-1]
    try:
        ratio = float(latest.get("longShortRatio") or 0.0)
        long_account = float(latest.get("longAccount") or 0.0)
        short_account = float(latest.get("shortAccount") or 0.0)
    except Exception:
        ratio = 0.0
        long_account = 0.0
        short_account = 0.0

    bias = "NEUTRAL"
    if ratio >= 1.15:
        bias = "LONG_CROWDED"
    elif ratio <= 0.87:
        bias = "SHORT_CROWDED"

    return {
        "symbol": symbol,
        "endpoint": endpoint,
        "ok": True,
        "period": period,
        "samples": len(rows),
        "long_short_ratio": round(ratio, 4),
        "long_account": round(long_account, 4),
        "short_account": round(short_account, 4),
        "crowd_bias": bias,
        "source": "Binance Futures data API",
        "timestamp": latest.get("timestamp"),
    }


def build_agent_intel(symbols: list[str] | None = None) -> dict[str, Any]:
    symbols = symbols or ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": symbols,
        "sources": {
            "global": "futures/data/globalLongShortAccountRatio",
            "top_positions": "futures/data/topLongShortPositionRatio",
            "taker": "futures/data/takerlongshortRatio",
        },
        "intel": [],
        "errors": [],
    }

    for symbol in symbols:
        try:
            global_ratio = _binance_ratio("globalLongShortAccountRatio", symbol)
            top_ratio = _binance_ratio("topLongShortPositionRatio", symbol)
            taker_ratio = _binance_ratio("takerlongshortRatio", symbol)

            if not global_ratio.get("ok"):
                payload["errors"].append({"symbol": symbol, "where": "global", "detail": global_ratio})
            if not top_ratio.get("ok"):
                payload["errors"].append({"symbol": symbol, "where": "top", "detail": top_ratio})
            if not taker_ratio.get("ok"):
                payload["errors"].append({"symbol": symbol, "where": "taker", "detail": taker_ratio})

            payload["intel"].append(
                {
                    "symbol": symbol,
                    "global": global_ratio,
                    "top_positions": top_ratio,
                    "taker_flow": taker_ratio,
                }
            )
        except Exception as exc:
            payload["errors"].append({"symbol": symbol, "error": str(exc)})

    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = build_agent_intel()
    print(json.dumps({"ok": True, "intel": len(result.get("intel", [])), "errors": len(result.get("errors", []))}, ensure_ascii=False))
