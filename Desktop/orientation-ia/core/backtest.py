from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from mt5_adapter.broker import fetch_rates, initialize_mt5, shutdown_mt5


@dataclass
class Trade:
    side: str
    entry: float
    sl: float
    tp: float
    open_index: int


def _default_strategy(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if len(frame) < 30:
        return []
    fast = frame["close"].rolling(9).mean()
    slow = frame["close"].rolling(21).mean()
    if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
        price = float(frame["close"].iloc[-1])
        return [{"side": "BUY", "entry": price, "sl": price * 0.99, "tp": price * 1.02}]
    if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]:
        price = float(frame["close"].iloc[-1])
        return [{"side": "SELL", "entry": price, "sl": price * 1.01, "tp": price * 0.98}]
    return []


def run(
    symbol: str,
    start,
    end,
    strategy_func: Callable[[pd.DataFrame], list[dict[str, Any]]] | None = None,
    timeframe: str = "H1",
) -> dict:
    strategy_func = strategy_func or _default_strategy
    import MetaTrader5 as mt5

    ok, err = initialize_mt5(mt5)
    if not ok:
        return {"ok": False, "message": f"MT5 init failed: {err}"}

    try:
        df = fetch_rates(mt5, symbol, timeframe, 2000)
        if df.empty:
            return {"ok": False, "message": "Aucune donnee historique"}
        df = df[(df["time"] >= pd.to_datetime(start, utc=True)) & (df["time"] <= pd.to_datetime(end, utc=True))].copy()
        if len(df) < 50:
            return {"ok": False, "message": "Donnees insuffisantes"}

        active: list[Trade] = []
        results: list[float] = []

        for i in range(30, len(df)):
            window = df.iloc[: i + 1]
            if not active:
                for sig in strategy_func(window):
                    active.append(Trade(side=str(sig["side"]).upper(), entry=float(sig["entry"]), sl=float(sig["sl"]), tp=float(sig["tp"]), open_index=i))
                    break

            bar = df.iloc[i]
            next_active: list[Trade] = []
            for tr in active:
                high = float(bar["high"])
                low = float(bar["low"])
                if tr.side == "BUY":
                    if low <= tr.sl:
                        results.append(-1.0)
                        continue
                    if high >= tr.tp:
                        results.append(abs((tr.tp - tr.entry) / max(tr.entry - tr.sl, 1e-9)))
                        continue
                else:
                    if high >= tr.sl:
                        results.append(-1.0)
                        continue
                    if low <= tr.tp:
                        results.append(abs((tr.entry - tr.tp) / max(tr.sl - tr.entry, 1e-9)))
                        continue
                next_active.append(tr)
            active = next_active

        wins = sum(1 for r in results if r > 0)
        gross_profit = sum(r for r in results if r > 0)
        gross_loss = abs(sum(r for r in results if r <= 0))
        peak = 0.0
        equity = 0.0
        max_dd = 0.0
        for r in results:
            equity += r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)

        return {
            "ok": True,
            "winrate": round((wins / max(len(results), 1)) * 100, 2),
            "profit_factor": round(gross_profit / max(gross_loss, 1e-9), 2),
            "max_dd": round(max_dd, 2),
            "nb_trades": len(results),
        }
    finally:
        shutdown_mt5(mt5)
