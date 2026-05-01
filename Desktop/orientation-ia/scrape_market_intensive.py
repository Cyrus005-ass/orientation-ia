from __future__ import annotations

import json
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT_DIR = Path("knowledge/live")
SNAPSHOT_FILE = OUT_DIR / "market_snapshot.txt"


def _http_get_json(url: str, timeout: int = 20) -> Any:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _http_get_text(url: str, timeout: int = 20) -> str:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_binance_ticker(symbol: str) -> dict[str, Any]:
    url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
    data = _http_get_json(url)
    return {
        "symbol": data.get("symbol"),
        "lastPrice": data.get("lastPrice"),
        "priceChangePercent": data.get("priceChangePercent"),
        "highPrice": data.get("highPrice"),
        "lowPrice": data.get("lowPrice"),
        "quoteVolume": data.get("quoteVolume"),
        "source": "Binance /api/v3/ticker/24hr",
    }


def fetch_yahoo_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    query = urllib.parse.quote(",".join(symbols), safe=",")
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={query}"
    data = _http_get_json(url)
    results = data.get("quoteResponse", {}).get("result", [])

    out = []
    for item in results:
        out.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("shortName") or item.get("longName") or "N/A",
                "price": item.get("regularMarketPrice"),
                "changePct": item.get("regularMarketChangePercent"),
                "high": item.get("regularMarketDayHigh"),
                "low": item.get("regularMarketDayLow"),
                "source": "Yahoo Finance quote API",
            }
        )
    return out


def fetch_fear_greed() -> dict[str, Any]:
    url = "https://api.alternative.me/fng/?limit=1"
    data = _http_get_json(url)
    first = (data.get("data") or [{}])[0]
    return {
        "value": first.get("value"),
        "classification": first.get("value_classification"),
        "timestamp": first.get("timestamp"),
        "source": "alternative.me Fear & Greed Index API",
    }


def fetch_rss_items(url: str, limit: int = 8) -> list[dict[str, str]]:
    xml_data = _http_get_text(url)
    root = ET.fromstring(xml_data)

    items = []
    for node in root.findall(".//item")[:limit]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        pub_date = (node.findtext("pubDate") or "").strip()
        if title:
            items.append({"title": title, "link": link, "pubDate": pub_date})
    return items


def build_market_snapshot() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []
    lines.append(f"[snapshot_generated_utc] {now}")

    lines.append("\n=== CRYPTO SPOT ===")
    for sym in ["BTCUSDT", "ETHUSDT", "BNBUSDT"]:
        try:
            d = fetch_binance_ticker(sym)
            lines.append(json.dumps(d, ensure_ascii=False))
        except Exception as exc:
            lines.append(json.dumps({"symbol": sym, "error": str(exc), "source": "Binance"}, ensure_ascii=False))

    lines.append("\n=== CROSS-ASSET QUOTES ===")
    try:
        symbols = ["^GSPC", "^DJI", "^IXIC", "GC=F", "CL=F", "EURUSD=X", "DX-Y.NYB"]
        for q in fetch_yahoo_quotes(symbols):
            lines.append(json.dumps(q, ensure_ascii=False))
    except Exception as exc:
        lines.append(json.dumps({"error": str(exc), "source": "Yahoo Finance"}, ensure_ascii=False))

    lines.append("\n=== SENTIMENT ===")
    try:
        lines.append(json.dumps(fetch_fear_greed(), ensure_ascii=False))
    except Exception as exc:
        lines.append(json.dumps({"error": str(exc), "source": "alternative.me"}, ensure_ascii=False))

    lines.append("\n=== NEWS FLOW (RSS) ===")
    rss_feeds = {
        "Reuters Markets": "https://feeds.reuters.com/reuters/marketsNews",
        "CNBC Top News": "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    }

    for name, url in rss_feeds.items():
        lines.append(f"\n[{name}] source={url}")
        try:
            for item in fetch_rss_items(url, limit=8):
                lines.append(json.dumps(item, ensure_ascii=False))
        except Exception as exc:
            lines.append(json.dumps({"error": str(exc), "source": url}, ensure_ascii=False))

    SNAPSHOT_FILE.write_text("\n".join(lines), encoding="utf-8")
    return SNAPSHOT_FILE


if __name__ == "__main__":
    out = build_market_snapshot()
    print(f"Snapshot marche genere: {out}")
