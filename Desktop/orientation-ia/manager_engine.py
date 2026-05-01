from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from manager_journal import discipline_reminders
from mt5_connection import initialize_mt5

BRIDGE_MARKET_FILE = Path("knowledge/live/bridge_market_data.json")


@dataclass
class ManagerDecision:
    symbol: str
    decision: str
    context: str
    entry: float | None
    sl: float | None
    tp: float | None
    rr: float | None
    lot: float | None
    discipline: str
    valid: bool
    reasons: list[str]
    mode: str
    execution: dict[str, Any]


def _tf_map(mt5, tf: str):
    mapping = {
        "MN": mt5.TIMEFRAME_MN1,
        "W1": mt5.TIMEFRAME_W1,
        "D1": mt5.TIMEFRAME_D1,
        "H4": mt5.TIMEFRAME_H4,
        "H1": mt5.TIMEFRAME_H1,
        "M15": mt5.TIMEFRAME_M15,
    }
    return mapping[tf]


def _fetch_df(mt5, symbol: str, tf: str, bars: int) -> pd.DataFrame:
    rates = mt5.copy_rates_from_pos(symbol, _tf_map(mt5, tf), 0, bars)
    if rates is None or len(rates) < 60:
        raise RuntimeError(f"Donnees insuffisantes {symbol} {tf}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def _swing_highs(df: pd.DataFrame, look: int = 2) -> list[float]:
    highs = df["high"].astype(float).tolist()
    out = []
    for i in range(look, len(highs) - look):
        h = highs[i]
        if all(h > highs[i - j] for j in range(1, look + 1)) and all(h >= highs[i + j] for j in range(1, look + 1)):
            out.append(h)
    return out


def _swing_lows(df: pd.DataFrame, look: int = 2) -> list[float]:
    lows = df["low"].astype(float).tolist()
    out = []
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

    bullish_choch = trend_hint == "DOWN" and bullish_bos
    bearish_choch = trend_hint == "UP" and bearish_bos

    return {
        "bullish_bos": bullish_bos,
        "bearish_bos": bearish_bos,
        "bullish_choch": bullish_choch,
        "bearish_choch": bearish_choch,
    }


def _fake_breakout(df: pd.DataFrame, support: float, resistance: float) -> dict[str, bool]:
    c = df.iloc[-1]
    low = float(c["low"])
    high = float(c["high"])
    close = float(c["close"])
    return {
        "bullish_fake_breakout": low < support and close > support,
        "bearish_fake_breakout": high > resistance and close < resistance,
    }


def _calc_lot_for_risk(mt5, symbol: str, entry: float, sl: float, direction: str, risk_pct: float, balance: float) -> float:
    risk_money = max(0.0, balance * (risk_pct / 100.0))
    if risk_money <= 0:
        return 0.0

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL
    p = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)
    if p is None:
        return 0.0
    risk_per_lot = abs(float(p))
    if risk_per_lot <= 0:
        return 0.0

    raw = risk_money / risk_per_lot
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0

    vmin = float(info.volume_min)
    vmax = float(info.volume_max)
    step = float(info.volume_step or 0.01)
    raw = max(vmin, min(vmax, raw))
    steps = round((raw - vmin) / step)
    lot = vmin + steps * step
    return round(lot, 2)


def _format_output(d: ManagerDecision) -> str:
    if d.decision == "WAIT":
        return (
            f"SYMBOL: {d.symbol}\n\n"
            f"Decision: WAIT\n\n"
            f"Raison:\n{d.context}\n\n"
            f"Rappel discipline:\n{d.discipline}"
        )

    return (
        f"SYMBOL: {d.symbol}\n\n"
        f"Decision: {d.decision}\n\n"
        f"Contexte:\n{d.context}\n\n"
        f"Entree: {d.entry:.5f}\n"
        f"SL: {d.sl:.5f}\n"
        f"TP: {d.tp:.5f}\n"
        f"RR: 1:{d.rr:.2f}\n"
        f"Lot: {d.lot:.2f}\n\n"
        f"Rappel discipline:\n{d.discipline}"
    )


def analyze_symbol_manager(
    symbol: str,
    risk_pct: float = 1.0,
    rr_min: float = 2.5,
    mode: str = "manual",
    auto_enabled: bool = False,
    spread_max_pct: float = 0.0015,
) -> dict[str, Any]:
    symbol = symbol.strip()
    mode = mode.strip().lower()
    if mode not in {"manual", "semi", "auto"}:
        mode = "manual"

    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        return {"ok": False, "message": f"MetaTrader5 indisponible: {exc}"}

    ok, err = initialize_mt5(mt5)
    if not ok:
        return {"ok": False, "message": f"MT5 init failed: {err}"}

    try:
        if not mt5.symbol_select(symbol, True):
            return {"ok": False, "message": f"symbol_select failed: {symbol}"}

        mn = _fetch_df(mt5, symbol, "MN", 140)
        w1 = _fetch_df(mt5, symbol, "W1", 180)
        d1 = _fetch_df(mt5, symbol, "D1", 220)
        h4 = _fetch_df(mt5, symbol, "H4", 220)
        h1 = _fetch_df(mt5, symbol, "H1", 260)
        m15 = _fetch_df(mt5, symbol, "M15", 260)

        trend_mn = _trend_from_swings(mn.tail(100))
        trend_w1 = _trend_from_swings(w1.tail(120))
        trend_h4 = _trend_from_swings(h4.tail(120))

        support_h4, resistance_h4 = _latest_levels(h4.tail(140))
        support_d1, resistance_d1 = _latest_levels(d1.tail(140))

        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick is None or info is None:
            return {"ok": False, "message": "tick/info indisponible"}

        ask = float(tick.ask)
        bid = float(tick.bid)
        mid = (ask + bid) / 2.0
        spread = max(0.0, ask - bid)
        spread_ok = spread <= max(mid * spread_max_pct, float(info.point) * 8)

        sig_h1 = _bos_choch(h1, trend_h4)
        sig_m15 = _bos_choch(m15, trend_h4)
        fake_h1 = _fake_breakout(h1, support_h4, resistance_h4)

        near_support = abs(mid - support_h4) / max(mid, 1e-9) <= 0.004
        near_resistance = abs(mid - resistance_h4) / max(mid, 1e-9) <= 0.004

        reasons: list[str] = []
        decision = "WAIT"
        entry = sl = tp = rr = lot = None
        valid = False
        execution: dict[str, Any] = {"mode": mode, "sent": False}

        if trend_h4 == "RANGE":
            reasons.append("Structure H4 non claire (range).")

        if trend_w1 in {"UP", "DOWN"} and trend_h4 != trend_w1:
            reasons.append("Conflit de tendance entre W1 et H4.")

        if trend_mn in {"UP", "DOWN"} and trend_h4 != trend_mn:
            reasons.append("Conflit de tendance entre MN et H4.")

        if not spread_ok:
            reasons.append("Spread trop large.")

        buy_confirm = (sig_h1["bullish_bos"] or sig_h1["bullish_choch"] or fake_h1["bullish_fake_breakout"]) and (
            sig_m15["bullish_bos"] or sig_m15["bullish_choch"]
        )
        sell_confirm = (sig_h1["bearish_bos"] or sig_h1["bearish_choch"] or fake_h1["bearish_fake_breakout"]) and (
            sig_m15["bearish_bos"] or sig_m15["bearish_choch"]
        )

        if trend_h4 == "UP" and near_support and buy_confirm:
            decision = "BUY"
            entry = ask
            sl = min(support_h4, support_d1) * 0.9995
            risk = max(entry - sl, entry * 0.0007)
            tp = entry + rr_min * risk
            rr = abs((tp - entry) / risk)
        elif trend_h4 == "DOWN" and near_resistance and sell_confirm:
            decision = "SELL"
            entry = bid
            sl = max(resistance_h4, resistance_d1) * 1.0005
            risk = max(sl - entry, entry * 0.0007)
            tp = entry - rr_min * risk
            rr = abs((entry - tp) / risk)
        else:
            reasons.append("Pas de confluence zone D1/H4 + confirmation H1/M15.")

        if decision != "WAIT":
            if rr is None or rr < rr_min:
                reasons.append(f"RR inferieur a 1:{rr_min}")
            if sl is None or entry is None:
                reasons.append("SL/entry invalide")
            else:
                if abs(entry - sl) <= spread * 3:
                    reasons.append("SL non logique vs spread")

            valid = len(reasons) == 0
            if not valid:
                decision = "WAIT"

        ai = mt5.account_info()
        balance = float(ai.balance) if ai is not None else 0.0
        if decision != "WAIT" and entry is not None and sl is not None:
            lot = _calc_lot_for_risk(mt5, symbol, entry, sl, decision, float(risk_pct), balance)
            if lot <= 0:
                reasons.append("Lot calcule invalide")
                decision = "WAIT"
                valid = False

        reminders = discipline_reminders()
        discipline = reminders[0] if reminders else "Respecte strictement zone H4, RR >= 1:2.5, et zero overtrading."

        ctx_lines = [
            f"Tendance MN: {trend_mn}",
            f"Tendance W1: {trend_w1}",
            f"Tendance H4: {trend_h4}",
            f"Zone H4 support={support_h4:.5f} resistance={resistance_h4:.5f}",
            f"Fake breakout H1 bullish={fake_h1['bullish_fake_breakout']} bearish={fake_h1['bearish_fake_breakout']}",
            f"Confirmation H1/M15 bullish={buy_confirm} bearish={sell_confirm}",
        ]
        if reasons:
            ctx_lines.append("Raisons blocage: " + " | ".join(reasons))

        md = ManagerDecision(
            symbol=symbol,
            decision=decision,
            context="\n".join(ctx_lines),
            entry=entry,
            sl=sl,
            tp=tp,
            rr=rr,
            lot=lot,
            discipline=discipline,
            valid=valid,
            reasons=reasons,
            mode=mode,
            execution=execution,
        )

        if decision in {"BUY", "SELL"} and valid and mode in {"semi", "auto"}:
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(lot),
                "type": mt5.ORDER_TYPE_BUY if decision == "BUY" else mt5.ORDER_TYPE_SELL,
                "price": float(ask if decision == "BUY" else bid),
                "sl": float(sl),
                "tp": float(tp),
                "deviation": 20,
                "magic": 940502,
                "comment": "AFR_MANAGER",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            md.execution["preview"] = req

            if mode == "auto" and auto_enabled:
                sent = mt5.order_send(req)
                md.execution["sent"] = sent is not None
                if sent is not None:
                    md.execution["result"] = {
                        "retcode": int(getattr(sent, "retcode", -1)),
                        "comment": str(getattr(sent, "comment", "")),
                        "order": int(getattr(sent, "order", 0)),
                        "deal": int(getattr(sent, "deal", 0)),
                    }

        return {
            "ok": True,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "mode": mode,
            "auto_enabled": bool(auto_enabled),
            "decision": md.__dict__,
            "formatted": _format_output(md),
        }
    finally:
        mt5.shutdown()


def save_bridge_market_data(payload: dict[str, Any]) -> Path:
    BRIDGE_MARKET_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIDGE_MARKET_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return BRIDGE_MARKET_FILE