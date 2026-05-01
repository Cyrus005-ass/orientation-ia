from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from mt5_connection import initialize_mt5

STATE_FILE = Path("knowledge/live/simple_agent_state.json")


@dataclass
class TradeRecord:
    id: str
    symbol: str
    side: str
    entry_price: float
    sl_price: float
    tp_price: float
    status: str
    opened_utc: str
    closed_utc: str | None = None
    close_price: float | None = None
    pnl_pct: float | None = None
    source: str = "manual"
    mt5_symbol: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"trades": [], "last_signal": {}}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8", errors="ignore"))
        if isinstance(data, dict):
            data.setdefault("trades", [])
            data.setdefault("last_signal", {})
            return data
    except Exception:
        pass
    return {"trades": [], "last_signal": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _binance_get(path: str, params: dict[str, Any]) -> Any:
    url = "https://api.binance.com" + path
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_latest_price(symbol: str) -> float:
    data = _binance_get("/api/v3/ticker/price", {"symbol": symbol.upper()})
    return _safe_float(data.get("price"))


def _fetch_closes(symbol: str, interval: str = "1h", limit: int = 200) -> list[float]:
    rows = _binance_get(
        "/api/v3/klines",
        {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": max(30, min(int(limit), 1000)),
        },
    )
    closes: list[float] = []
    for row in rows:
        if isinstance(row, list) and len(row) >= 5:
            closes.append(_safe_float(row[4]))
    return [c for c in closes if c > 0]


def _rsi(closes: list[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        raise RuntimeError("Donnees insuffisantes pour RSI")

    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def strategy_status(symbol: str, interval: str = "1h") -> dict[str, Any]:
    closes = _fetch_closes(symbol=symbol, interval=interval, limit=200)
    last_price = closes[-1]
    rsi_value = _rsi(closes, period=14)

    signal = {
        "symbol": symbol.upper(),
        "interval": interval,
        "last_price": round(last_price, 8),
        "rsi": round(rsi_value, 2),
        "rule": "RSI < 30 => BUY, SL -2%, TP +5%",
        "should_buy": rsi_value < 30.0,
        "sl_pct": -2.0,
        "tp_pct": 5.0,
        "generated_utc": _now(),
    }

    state = _load_state()
    state["last_signal"] = signal
    _save_state(state)
    return signal


def list_trades(status: str = "ALL") -> list[dict[str, Any]]:
    state = _load_state()
    trades = state.get("trades", [])
    if status.upper() == "ALL":
        return trades
    return [t for t in trades if str(t.get("status", "")).upper() == status.upper()]


def open_trade(
    symbol: str,
    side: str,
    source: str = "manual",
    mt5_symbol: str | None = None,
) -> dict[str, Any]:
    side = side.upper().strip()
    if side not in {"BUY", "SELL"}:
        raise RuntimeError("side invalide: BUY ou SELL")

    entry = get_latest_price(symbol)
    if entry <= 0:
        raise RuntimeError("Prix invalide")

    if side == "BUY":
        sl = entry * 0.98
        tp = entry * 1.05
    else:
        sl = entry * 1.02
        tp = entry * 0.95

    rec = TradeRecord(
        id=str(uuid.uuid4()),
        symbol=symbol.upper(),
        side=side,
        entry_price=round(entry, 8),
        sl_price=round(sl, 8),
        tp_price=round(tp, 8),
        status="OPEN",
        opened_utc=_now(),
        source=source,
        mt5_symbol=mt5_symbol,
    )

    state = _load_state()
    state.setdefault("trades", []).append(rec.__dict__)
    _save_state(state)
    return rec.__dict__


def close_trade(trade_id: str, reason: str = "manual_close") -> dict[str, Any]:
    state = _load_state()
    trades = state.get("trades", [])

    for t in trades:
        if str(t.get("id")) != str(trade_id):
            continue
        if str(t.get("status")).upper() != "OPEN":
            raise RuntimeError("Trade deja cloture")

        price = get_latest_price(str(t["symbol"]))
        side = str(t.get("side", "BUY")).upper()
        entry = _safe_float(t.get("entry_price"))

        if side == "BUY":
            pnl = ((price - entry) / max(entry, 1e-9)) * 100.0
        else:
            pnl = ((entry - price) / max(entry, 1e-9)) * 100.0

        t["status"] = "CLOSED"
        t["closed_utc"] = _now()
        t["close_price"] = round(price, 8)
        t["pnl_pct"] = round(pnl, 4)
        t["close_reason"] = reason
        _save_state(state)
        return t

    raise RuntimeError("Trade introuvable")


def sync_trades() -> dict[str, Any]:
    state = _load_state()
    trades = state.get("trades", [])
    updated = 0

    for t in trades:
        if str(t.get("status", "")).upper() != "OPEN":
            continue

        symbol = str(t.get("symbol", "")).upper()
        side = str(t.get("side", "BUY")).upper()
        sl = _safe_float(t.get("sl_price"))
        tp = _safe_float(t.get("tp_price"))

        try:
            price = get_latest_price(symbol)
        except Exception:
            continue

        hit_tp = (side == "BUY" and price >= tp) or (side == "SELL" and price <= tp)
        hit_sl = (side == "BUY" and price <= sl) or (side == "SELL" and price >= sl)

        if hit_tp or hit_sl:
            entry = _safe_float(t.get("entry_price"))
            pnl = ((price - entry) / max(entry, 1e-9)) * 100.0 if side == "BUY" else ((entry - price) / max(entry, 1e-9)) * 100.0
            t["status"] = "CLOSED"
            t["closed_utc"] = _now()
            t["close_price"] = round(price, 8)
            t["pnl_pct"] = round(pnl, 4)
            t["close_reason"] = "tp_hit" if hit_tp else "sl_hit"
            updated += 1

    _save_state(state)
    return {"updated": updated, "open_trades": len([x for x in trades if str(x.get("status", "")).upper() == "OPEN"])}


def run_strategy_cycle(symbol: str, interval: str = "1h") -> dict[str, Any]:
    signal = strategy_status(symbol=symbol, interval=interval)
    state = _load_state()
    open_same_symbol = [
        t for t in state.get("trades", [])
        if str(t.get("status", "")).upper() == "OPEN" and str(t.get("symbol", "")).upper() == symbol.upper()
    ]

    opened = None
    if signal.get("should_buy") and not open_same_symbol:
        opened = open_trade(symbol=symbol, side="BUY", source="strategy")

    sync_info = sync_trades()

    return {
        "signal": signal,
        "opened_trade": opened,
        "sync": sync_info,
    }


def _clamp_volume(vol: float, vmin: float, vmax: float, vstep: float) -> float:
    if vstep <= 0:
        vstep = 0.01
    vol = max(vmin, min(vmax, vol))
    steps = round((vol - vmin) / vstep)
    return round(vmin + steps * vstep, 2)


def _calc_volume_for_risk(mt5, symbol: str, side: str, entry: float, sl: float, risk_pct: float, balance: float) -> float:
    risk_money = max(0.0, balance * (risk_pct / 100.0))
    if risk_money <= 0:
        return 0.0

    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    profit = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)
    if profit is None:
        return 0.0

    risk_per_lot = abs(float(profit))
    if risk_per_lot <= 0:
        return 0.0

    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0

    raw_lot = risk_money / risk_per_lot
    return _clamp_volume(raw_lot, float(info.volume_min), float(info.volume_max), float(info.volume_step or 0.01))


def execute_trade_on_mt5(trade_id: str, risk_pct: float = 1.0, confirm: str = "") -> dict[str, Any]:
    state = _load_state()
    trade = None
    for t in state.get("trades", []):
        if str(t.get("id")) == str(trade_id):
            trade = t
            break

    if trade is None:
        return {"ok": False, "message": "Trade introuvable", "payload": {}}

    if str(trade.get("status", "")).upper() != "OPEN":
        return {"ok": False, "message": "Trade deja cloture", "payload": {}}

    mt5_symbol = (trade.get("mt5_symbol") or trade.get("symbol") or "").strip()
    side = str(trade.get("side", "BUY")).upper()
    sl = _safe_float(trade.get("sl_price"))
    tp = _safe_float(trade.get("tp_price"))

    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        return {"ok": False, "message": f"MetaTrader5 indisponible: {exc}", "payload": {}}

    ok, err = initialize_mt5(mt5)
    if not ok:
        return {"ok": False, "message": f"MT5 init failed: {err}", "payload": {}}

    try:
        if not mt5.symbol_select(mt5_symbol, True):
            return {"ok": False, "message": f"symbol_select failed: {mt5_symbol}", "payload": {}}

        tick = mt5.symbol_info_tick(mt5_symbol)
        ai = mt5.account_info()
        if tick is None or ai is None:
            return {"ok": False, "message": "tick/account indisponible", "payload": {}}

        price = float(tick.ask if side == "BUY" else tick.bid)
        volume = _calc_volume_for_risk(mt5, mt5_symbol, side, price, sl, risk_pct, float(ai.balance))
        if volume <= 0:
            return {"ok": False, "message": "Volume calcule invalide", "payload": {}}

        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": mt5_symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": 950101,
            "comment": "AFR_SIMPLE_AGENT",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        preview = {"trade_id": trade_id, "request": req, "risk_pct": risk_pct}

        if confirm.strip().upper() != "EXECUTE":
            return {"ok": False, "message": "Confirmation invalide. Utilise confirm=EXECUTE", "payload": preview}

        sent = mt5.order_send(req)
        if sent is None:
            return {"ok": False, "message": "order_send a retourne None", "payload": preview}

        retcode = int(getattr(sent, "retcode", -1))
        result = {
            "retcode": retcode,
            "comment": str(getattr(sent, "comment", "")),
            "order": int(getattr(sent, "order", 0)),
            "deal": int(getattr(sent, "deal", 0)),
        }

        if retcode != getattr(mt5, "TRADE_RETCODE_DONE", 10009):
            return {"ok": False, "message": f"Ordre refuse retcode={retcode}", "payload": {**preview, "mt5_result": result}}

        return {"ok": True, "message": "Ordre envoye sur MT5", "payload": {**preview, "mt5_result": result}}
    finally:
        mt5.shutdown()
