from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from mt5_connection import initialize_mt5

JOURNAL_FILE = Path("knowledge/live/mt5_signal_journal.jsonl")
STATE_FILE = Path("knowledge/live/learning_state.json")


def _tf_to_minutes(tf: str) -> int:
    mapping = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
    }
    return mapping.get(tf.upper(), 15)


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"bias": {}, "stats": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"bias": {}, "stats": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _iter_journal() -> list[dict[str, Any]]:
    if not JOURNAL_FILE.exists():
        return []
    out = []
    for line in JOURNAL_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _write_journal(items: list[dict[str, Any]]) -> None:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL_FILE.open("w", encoding="utf-8") as f:
        for x in items:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def _update_learning(state: dict[str, Any], item: dict[str, Any], outcome: str) -> None:
    key = f"{item['symbol']}|{item['timeframe']}|{item['direction']}"
    stats = state.setdefault("stats", {}).setdefault(key, {"wins": 0, "losses": 0, "total": 0})
    bias = state.setdefault("bias", {}).get(key, 0)

    stats["total"] += 1
    if outcome == "WIN":
        stats["wins"] += 1
        bias = min(20, bias + 2)
    elif outcome == "LOSS":
        stats["losses"] += 1
        bias = max(-20, bias - 2)

    state["bias"][key] = bias


def evaluate_pending_signals() -> dict[str, Any]:
    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        raise RuntimeError("Module MetaTrader5 indisponible.") from exc

    ok, err = initialize_mt5(mt5)
    if not ok:
        raise RuntimeError(f"Impossible d initialiser MT5: {err}")

    items = _iter_journal()
    state = _load_state()

    now = datetime.now(timezone.utc)
    updated = 0

    try:
        for item in items:
            if item.get("status") != "PENDING":
                continue

            symbol = item["symbol"]
            tf = item["timeframe"]
            issued = datetime.fromisoformat(item["issued_utc"])
            minutes = _tf_to_minutes(tf)
            horizon = issued + timedelta(minutes=minutes * 12)

            if now < horizon:
                continue

            if not mt5.symbol_select(symbol, True):
                item["status"] = "ERROR"
                item["error"] = "symbol_select failed"
                updated += 1
                continue

            tf_map = {
                "M1": mt5.TIMEFRAME_M1,
                "M5": mt5.TIMEFRAME_M5,
                "M15": mt5.TIMEFRAME_M15,
                "M30": mt5.TIMEFRAME_M30,
                "H1": mt5.TIMEFRAME_H1,
                "H4": mt5.TIMEFRAME_H4,
                "D1": mt5.TIMEFRAME_D1,
            }
            tf_const = tf_map.get(tf.upper(), mt5.TIMEFRAME_M15)
            rates = mt5.copy_rates_range(symbol, tf_const, issued, horizon)
            if rates is None or len(rates) == 0:
                item["status"] = "NO_DATA"
                updated += 1
                continue

            direction = item["direction"]
            sl = float(item["stop_loss"])
            tp1 = float(item["tp1"])
            outcome = "OPEN"

            for r in rates:
                h = float(r["high"])
                l = float(r["low"])
                if direction == "LONG":
                    if l <= sl:
                        outcome = "LOSS"
                        break
                    if h >= tp1:
                        outcome = "WIN"
                        break
                else:
                    if h >= sl:
                        outcome = "LOSS"
                        break
                    if l <= tp1:
                        outcome = "WIN"
                        break

            if outcome in {"WIN", "LOSS"}:
                item["status"] = outcome
                item["resolved_utc"] = now.isoformat()
                _update_learning(state, item, outcome)
                updated += 1
            else:
                item["status"] = "EXPIRED"
                item["resolved_utc"] = now.isoformat()
                updated += 1
    finally:
        mt5.shutdown()

    _write_journal(items)
    _save_state(state)

    return {
        "updated": updated,
        "journal_count": len(items),
        "state_file": str(STATE_FILE),
        "journal_file": str(JOURNAL_FILE),
    }


def get_bias(symbol: str, timeframe: str, direction: str) -> int:
    state = _load_state()
    key = f"{symbol}|{timeframe}|{direction}"
    return int(state.get("bias", {}).get(key, 0))


if __name__ == "__main__":
    result = evaluate_pending_signals()
    print(json.dumps(result, ensure_ascii=False))
