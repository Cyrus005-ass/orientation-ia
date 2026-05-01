from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mt5_connection import initialize_mt5


@dataclass
class ExecutionResult:
    ok: bool
    mode: str
    message: str
    payload: dict[str, Any]


def shutdown_mt5(mt5) -> None:
    try:
        mt5.shutdown()
    except Exception:
        pass


def fetch_rates(mt5, symbol: str, timeframe: str, bars: int = 320):
    mapping = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
        "W1": mt5.TIMEFRAME_W1,
        "MN": mt5.TIMEFRAME_MN1,
    }
    rates = mt5.copy_rates_from_pos(symbol, mapping.get(timeframe.upper(), mt5.TIMEFRAME_M15), 0, bars)
    import pandas as pd

    if rates is None:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
    df = pd.DataFrame(rates)
    if not df.empty and "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    return df


def _clamp_volume(vol: float, vmin: float, vmax: float, vstep: float) -> float:
    if vstep <= 0:
        vstep = 0.01
    vol = max(vmin, min(vmax, vol))
    steps = round((vol - vmin) / vstep)
    return round(vmin + steps * vstep, 2)


def _calc_volume_for_risk(mt5, symbol: str, direction: str, entry: float, sl: float, risk_pct: float, balance: float) -> float:
    risk_money = max(0.0, balance * (risk_pct / 100.0))
    if risk_money <= 0:
        return 0.0
    order_type = mt5.ORDER_TYPE_BUY if direction == "LONG" else mt5.ORDER_TYPE_SELL
    profit = mt5.order_calc_profit(order_type, symbol, 1.0, entry, sl)
    if profit is None:
        return 0.0
    risk_per_lot = abs(float(profit))
    if risk_per_lot <= 0:
        return 0.0
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    return _clamp_volume(risk_money / risk_per_lot, float(info.volume_min), float(info.volume_max), float(info.volume_step or 0.01))


def _build_order_request(mt5, signal: dict[str, Any], volume: float, comment: str = "AFR_AGENT") -> dict[str, Any]:
    symbol = str(signal["symbol"])
    direction = str(signal["direction"]).upper()
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"Aucun tick pour {symbol}")
    is_long = direction == "LONG"
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL,
        "price": float(tick.ask if is_long else tick.bid),
        "sl": float(signal["stop_loss"]),
        "tp": float(signal["tp1"]),
        "deviation": 20,
        "magic": 940501,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }


def execute_signal(signal_id: int, risk_pct: float, live: bool = False, confirm: str = "") -> ExecutionResult:
    from core.signals import read_cached_signals

    signals = [x for x in read_cached_signals().get("signals", []) if isinstance(x, dict) and x.get("status") == "TRADE"]
    if not signals:
        return ExecutionResult(False, "none", "Aucun signal disponible.", {})
    if signal_id < 1 or signal_id > len(signals):
        return ExecutionResult(False, "none", f"signal_id invalide. 1..{len(signals)}", {})

    signal = signals[signal_id - 1]
    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        return ExecutionResult(False, "none", f"MetaTrader5 indisponible: {exc}", {})

    ok, err = initialize_mt5(mt5)
    if not ok:
        return ExecutionResult(False, "none", f"MT5 init failed: {err}", {})

    try:
        symbol = str(signal["symbol"])
        if not mt5.symbol_select(symbol, True):
            return ExecutionResult(False, "none", f"symbol_select failed: {symbol}", {})

        ai = mt5.account_info()
        if ai is None:
            return ExecutionResult(False, "none", "account_info indisponible", {})

        balance = float(ai.balance)
        volume = _calc_volume_for_risk(mt5, symbol, str(signal["direction"]), float(signal["entry"]), float(signal["stop_loss"]), risk_pct, balance)
        if volume <= 0:
            return ExecutionResult(False, "none", "Volume calcule invalide (0).", {})

        req = _build_order_request(mt5, signal, volume)
        preview = {"signal": signal, "risk_pct": risk_pct, "balance": balance, "volume": volume, "request": req}

        if not live:
            return ExecutionResult(True, "preview", "Preview generee. Aucune execution reelle.", preview)
        if confirm.strip().upper() != "EXECUTE":
            return ExecutionResult(False, "live", "Confirmation invalide. Utilise confirm=EXECUTE", preview)

        result = mt5.order_send(req)
        if result is None:
            return ExecutionResult(False, "live", "order_send a retourne None", preview)

        retcode = int(getattr(result, "retcode", -1))
        data = {k: getattr(result, k) for k in dir(result) if not k.startswith("_") and k in {"retcode", "comment", "order", "deal", "request_id", "volume", "price", "bid", "ask"}}
        if retcode != getattr(mt5, "TRADE_RETCODE_DONE", 10009):
            return ExecutionResult(False, "live", f"Ordre refuse retcode={retcode}", {**preview, "mt5_result": data})
        return ExecutionResult(True, "live", "Ordre execute avec succes.", {**preview, "mt5_result": data})
    finally:
        shutdown_mt5(mt5)
