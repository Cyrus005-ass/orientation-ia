from __future__ import annotations

import argparse
import time

from mt5_signals import build_live_signal_pack
from signal_learning import evaluate_pending_signals


def run(symbols: list[str], timeframes: list[str], interval_sec: int, iterations: int | None = None) -> None:
    i = 0
    while True:
        payload = build_live_signal_pack(symbols=symbols, timeframes=timeframes)
        learning = evaluate_pending_signals()
        i += 1
        print(
            f"[{i}] signal update ok | signals={len(payload.get('signals', []))} "
            f"errors={len(payload.get('errors', []))} learning_updated={learning.get('updated', 0)}"
        )

        if iterations is not None and i >= iterations:
            break

        time.sleep(interval_sec)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitoring live des signaux MT5.")
    parser.add_argument("--symbols", type=str, default="EURUSDm,XAUUSDm,BTCUSDm")
    parser.add_argument("--timeframes", type=str, default="M5,M15,H1")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--iterations", type=int)
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    run(symbols=symbols, timeframes=tfs, interval_sec=max(10, args.interval), iterations=args.iterations)
