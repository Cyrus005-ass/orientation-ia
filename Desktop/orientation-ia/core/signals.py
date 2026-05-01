from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from mt5_adapter.broker import fetch_rates, initialize_mt5, shutdown_mt5

SIGNALS_FILE = Path("knowledge/live/mt5_live_signals.json")
JOURNAL_FILE = Path("knowledge/live/mt5_signal_journal.jsonl")


@dataclass
class SignalPlan:
    symbol: str
    timeframe: str
    direction: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    rr: float
    confidence: str
    trigger: str
    invalidation: str
    confluence_score: int


def _higher_tf(tf: str) -> str:
    return {"M1": "M5", "M5": "M15", "M15": "H1", "M30": "H1", "H1": "H4", "H4": "D1", "D1": "W1", "W1": "MN"}.get(tf.upper(), "H1")


def _swing_highs(df: pd.DataFrame, look: int = 2) -> list[float]:
    highs = df["high"].astype(float).tolist()
    out: list[float] = []
    for i in range(look, len(highs) - look):
        h = highs[i]
        if all(h > highs[i - j] for j in range(1, look + 1)) and all(h >= highs[i + j] for j in range(1, look + 1)):
            out.append(h)
    return out


def _swing_lows(df: pd.DataFrame, look: int = 2) -> list[float]:
    lows = df["low"].astype(float).tolist()
    out: list[float] = []
    for i in range(look, len(lows) - look):
        l = lows[i]
        if all(l < lows[i - j] for j in range(1, look + 1)) and all(l <= lows[i + j] for j in range(1, look + 1)):
            out.append(l)
    return out


def _trend_from_swings(df: pd.DataFrame) -> str:
    hs = _swing_highs(df)
    ls = _swing_lows(df)
    if len(hs) < 2 or len(ls) < 2:
        return "RANGE"
    if hs[-1] > hs[-2] and ls[-1] > ls[-2]:
        return "UP"
    if hs[-1] < hs[-2] and ls[-1] < ls[-2]:
        return "DOWN"
    return "RANGE"


def _latest_levels(df: pd.DataFrame) -> tuple[float, float]:
    hs = _swing_highs(df)
    ls = _swing_lows(df)
    if hs and ls:
        return float(ls[-1]), float(hs[-1])
    tail = df.tail(40)
    return float(tail["low"].min()), float(tail["high"].max())


def _bos_choch(df: pd.DataFrame, trend_hint: str) -> dict[str, bool]:
    hs = _swing_highs(df)
    ls = _swing_lows(df)
    close = float(df["close"].iloc[-1])
    prev_h = hs[-1] if hs else float(df["high"].tail(20).max())
    prev_l = ls[-1] if ls else float(df["low"].tail(20).min())
    bullish_bos = close > prev_h
    bearish_bos = close < prev_l
    return {"bullish_bos": bullish_bos, "bearish_bos": bearish_bos, "bullish_choch": trend_hint == "DOWN" and bullish_bos, "bearish_choch": trend_hint == "UP" and bearish_bos}


def _fake_breakout(df: pd.DataFrame, support: float, resistance: float) -> dict[str, bool]:
    c = df.iloc[-1]
    return {"bullish_fake_breakout": float(c["low"]) < support and float(c["close"]) > support, "bearish_fake_breakout": float(c["high"]) > resistance and float(c["close"]) < resistance}


def _confidence(score: int) -> str:
    return "High" if score >= 80 else "Medium" if score >= 60 else "Low"


def _build_plan(symbol: str, timeframe: str, df: pd.DataFrame, htf_df: pd.DataFrame, tick, spread_ok: bool, min_rr: float = 2.5) -> tuple[Optional[SignalPlan], str]:
    trend_htf = _trend_from_swings(htf_df.tail(180))
    support, resistance = _latest_levels(htf_df.tail(160))
    signal = _bos_choch(df.tail(160), trend_htf)
    fake = _fake_breakout(df.tail(30), support, resistance)

    ask = float(tick.ask)
    bid = float(tick.bid)
    mid = (ask + bid) / 2.0
    near_support = abs(mid - support) / max(mid, 1e-9) <= 0.004
    near_resistance = abs(mid - resistance) / max(mid, 1e-9) <= 0.004

    direction = ""
    entry = sl = tp1 = tp2 = 0.0
    reasons: list[str] = []
    if trend_htf == "RANGE":
        reasons.append("Structure HTF non claire")
    if not spread_ok:
        reasons.append("Spread trop large")

    buy_confirm = signal["bullish_bos"] or signal["bullish_choch"] or fake["bullish_fake_breakout"]
    sell_confirm = signal["bearish_bos"] or signal["bearish_choch"] or fake["bearish_fake_breakout"]

    if trend_htf == "UP" and near_support and buy_confirm:
        direction = "LONG"
        entry = ask
        sl = support * 0.9995
        risk = max(entry - sl, entry * 0.0007)
        tp1 = entry + risk
        tp2 = entry + (min_rr * risk)
    elif trend_htf == "DOWN" and near_resistance and sell_confirm:
        direction = "SHORT"
        entry = bid
        sl = resistance * 1.0005
        risk = max(sl - entry, entry * 0.0007)
        tp1 = entry - risk
        tp2 = entry - (min_rr * risk)
    else:
        reasons.append("Pas de confluence zone + structure + confirmation")
        return None, " | ".join(reasons)

    risk = abs(entry - sl)
    if risk <= 0:
        return None, "Risque invalide"
    rr = abs((tp2 - entry) / risk)
    if rr < min_rr:
        return None, f"RR inferieur a 1:{min_rr}"
    spread = max(0.0, ask - bid)
    if risk <= spread * 3:
        return None, "SL trop proche du spread"

    score = 0
    score += 25 if trend_htf in {"UP", "DOWN"} else 0
    score += 25 if near_support or near_resistance else 0
    score += 25 if buy_confirm or sell_confirm else 0
    score += 10 if fake["bullish_fake_breakout"] or fake["bearish_fake_breakout"] else 0
    score += 15 if rr >= min_rr else 0
    score = max(0, min(100, score))

    return SignalPlan(symbol=symbol, timeframe=timeframe, direction=direction, entry=round(entry, 5), stop_loss=round(sl, 5), tp1=round(tp1, 5), tp2=round(tp2, 5), rr=round(rr, 2), confidence=_confidence(score), trigger="Confluence zone HTF + confirmation BOS/CHOCH", invalidation="Cassure du SL ou invalidation structure", confluence_score=score), ""


def _append_journal(payload: dict) -> None:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    now = payload.get("generated_utc") or datetime.now(timezone.utc).isoformat()
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        for sig in payload.get("signals", []):
            if sig.get("status") != "TRADE":
                continue
            row = {"signal_id": str(uuid.uuid4()), "issued_utc": now, "status": "PENDING", "symbol": sig["symbol"], "timeframe": sig["timeframe"], "direction": sig["direction"], "entry": sig["entry"], "stop_loss": sig["stop_loss"], "tp1": sig["tp1"], "tp2": sig["tp2"], "confluence_score": sig["confluence_score"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def generate_live_signals(symbols: list[str], timeframes: list[str], min_rr: float = 2.5) -> dict:
    import MetaTrader5 as mt5
    ok, err = initialize_mt5(mt5)
    if not ok:
        raise RuntimeError(f"Impossible d initialiser MT5: {err}")

    generated = datetime.now(timezone.utc).isoformat()
    out = {"generated_utc": generated, "source": "MetaTrader5 live rates", "policy": {"logic": "price_action_only", "indicators": "disabled", "rr_min": min_rr}, "signals": [], "errors": []}
    try:
        for symbol in symbols:
            if not mt5.symbol_select(symbol, True):
                out["errors"].append({"symbol": symbol, "error": "symbol_select failed"})
                continue
            tick = mt5.symbol_info_tick(symbol)
            info = mt5.symbol_info(symbol)
            if tick is None or info is None:
                out["errors"].append({"symbol": symbol, "error": "tick/info indisponible"})
                continue
            ask = float(tick.ask)
            bid = float(tick.bid)
            mid = (ask + bid) / 2.0
            spread = max(0.0, ask - bid)
            spread_ok = spread <= max(mid * 0.0015, float(info.point) * 8)
            for tf in timeframes:
                try:
                    df = fetch_rates(mt5, symbol, tf)
                    htf = _higher_tf(tf)
                    htf_df = fetch_rates(mt5, symbol, htf)
                    plan, reason = _build_plan(symbol, tf, df, htf_df, tick=tick, spread_ok=spread_ok, min_rr=min_rr)
                    if not plan:
                        out["signals"].append({"symbol": symbol, "timeframe": tf, "status": "NO_TRADE", "reason": reason or "Confluences insuffisantes"})
                    else:
                        out["signals"].append({"status": "TRADE", **plan.__dict__})
                except Exception as exc:
                    out["errors"].append({"symbol": symbol, "timeframe": tf, "error": str(exc)})
    finally:
        shutdown_mt5(mt5)
    return out


def read_cached_signals(path: Path = SIGNALS_FILE) -> dict:
    if not path.exists():
        return {"signals": [], "errors": []}
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return {"signals": [], "errors": []}


def save_signals(payload: dict, out_json: str = str(SIGNALS_FILE), out_txt: str = "knowledge/live/mt5_live_signals.txt") -> tuple[Path, Path]:
    pj = Path(out_json)
    pt = Path(out_txt)
    pj.parent.mkdir(parents=True, exist_ok=True)
    pj.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"[generated_utc] {payload.get('generated_utc')}", f"[source] {payload.get('source')}", f"[policy] {json.dumps(payload.get('policy', {}), ensure_ascii=False)}", "", "=== SIGNALS ==="]
    for sig in payload.get("signals", []):
        lines.append(json.dumps(sig, ensure_ascii=False))
    pt.write_text("\n".join(lines), encoding="utf-8")
    _append_journal(payload)
    return pj, pt


def build_live_signal_pack(symbols: list[str], timeframes: list[str], min_rr: float = 2.5) -> dict:
    payload = generate_live_signals(symbols=symbols, timeframes=timeframes, min_rr=min_rr)
    save_signals(payload)
    return payload


def list_candidates() -> list[dict[str, Any]]:
    items = read_cached_signals().get("signals", [])
    out = []
    for i, s in enumerate([x for x in items if isinstance(x, dict) and x.get("status") == "TRADE"], start=1):
        out.append({"id": i, "symbol": s.get("symbol"), "timeframe": s.get("timeframe"), "direction": s.get("direction"), "entry": s.get("entry"), "stop_loss": s.get("stop_loss"), "tp1": s.get("tp1"), "tp2": s.get("tp2"), "rr": s.get("rr"), "confidence": s.get("confidence"), "trigger": s.get("trigger"), "invalidation": s.get("invalidation"), "confluence_score": s.get("confluence_score")})
    return out
