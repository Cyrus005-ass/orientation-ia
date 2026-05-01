from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from scrape_market_intensive import fetch_binance_ticker, fetch_fear_greed

OUT_DIR = Path("knowledge/live")
BRIEF_FILE = OUT_DIR / "realtime_brief.txt"
TICKS_FILE = OUT_DIR / "realtime_ticks.jsonl"


def _safe_fetch() -> dict:
    now = datetime.now(timezone.utc).isoformat()
    payload = {"generated_utc": now, "sources": []}

    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
    ticker_block = []
    for sym in symbols:
        try:
            d = fetch_binance_ticker(sym)
            ticker_block.append(d)
        except Exception as exc:
            ticker_block.append({"symbol": sym, "error": str(exc), "source": "Binance"})

    payload["sources"].append({"name": "binance_ticker", "data": ticker_block})

    try:
        fng = fetch_fear_greed()
    except Exception as exc:
        fng = {"error": str(exc), "source": "alternative.me"}

    payload["sources"].append({"name": "fear_greed", "data": fng})
    return payload


def _write_brief(payload: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines = [f"[generated_utc] {payload['generated_utc']}"]
    lines.append("=== LIVE TICKERS ===")

    tickers = []
    for src in payload.get("sources", []):
        if src.get("name") == "binance_ticker":
            tickers = src.get("data", [])
            break

    for t in tickers:
        if "error" in t:
            lines.append(json.dumps(t, ensure_ascii=False))
        else:
            lines.append(
                f"{t.get('symbol')} last={t.get('lastPrice')} change%={t.get('priceChangePercent')} "
                f"high={t.get('highPrice')} low={t.get('lowPrice')} vol={t.get('quoteVolume')} source={t.get('source')}"
            )

    lines.append("=== SENTIMENT ===")
    for src in payload.get("sources", []):
        if src.get("name") == "fear_greed":
            lines.append(json.dumps(src.get("data", {}), ensure_ascii=False))

    BRIEF_FILE.write_text("\n".join(lines), encoding="utf-8")


def run(interval_sec: int, iterations: int | None = None) -> None:
    count = 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    while True:
        payload = _safe_fetch()
        _write_brief(payload)
        with TICKS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        count += 1
        print(f"[{count}] update ok: {payload['generated_utc']}")

        if iterations is not None and count >= iterations:
            break

        time.sleep(interval_sec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitoring marche quasi temps reel pour l agent.")
    parser.add_argument("--interval", type=int, default=60, help="Intervalle en secondes")
    parser.add_argument("--iterations", type=int, help="Nombre de cycles (si absent: infini)")
    args = parser.parse_args()

    run(interval_sec=max(10, args.interval), iterations=args.iterations)
