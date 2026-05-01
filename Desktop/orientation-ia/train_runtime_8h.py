from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from mt5_signals import build_live_signal_pack
from realtime_monitor import run as run_realtime
from scrape_market_intensive import build_market_snapshot
from market_agent_intel import build_agent_intel
from signal_learning import evaluate_pending_signals
from train_agent import build_knowledge

LIVE_DIR = Path("knowledge/live")
LOG_FILE = LIVE_DIR / "training_runtime.log"
METRICS_FILE = LIVE_DIR / "training_metrics.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{_now()}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_training(
    hours: float,
    symbols: list[str],
    timeframes: list[str],
    signal_interval: int,
    market_interval: int,
    snapshot_interval: int,
    knowledge_interval: int,
    agent_intel_interval: int,
) -> dict:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)

    start = time.time()
    end = start + max(60, int(hours * 3600))

    next_signal = start
    next_market = start
    next_snapshot = start
    next_knowledge = start
    next_agent_intel = start

    stats = {
        "started_utc": _now(),
        "hours": hours,
        "symbols": symbols,
        "timeframes": timeframes,
        "signal_cycles": 0,
        "signals_generated": 0,
        "signal_errors": 0,
        "learning_updates": 0,
        "market_cycles": 0,
        "snapshot_cycles": 0,
        "knowledge_rebuilds": 0,
        "agent_intel_cycles": 0,
        "last_error": None,
    }

    _log("START 8H TRAINING LOOP")

    while time.time() < end:
        now = time.time()

        if now >= next_signal:
            try:
                payload = build_live_signal_pack(symbols=symbols, timeframes=timeframes)
                learning = evaluate_pending_signals()

                stats["signal_cycles"] += 1
                stats["signals_generated"] += len(payload.get("signals", []))
                stats["signal_errors"] += len(payload.get("errors", []))
                stats["learning_updates"] += int(learning.get("updated", 0))

                _log(
                    f"SIGNAL_CYCLE ok signals={len(payload.get('signals', []))} "
                    f"errors={len(payload.get('errors', []))} learning_updated={learning.get('updated', 0)}"
                )
            except Exception as exc:
                stats["last_error"] = str(exc)
                _log(f"ERROR SIGNAL {exc}")
            finally:
                next_signal = now + max(10, signal_interval)

        if now >= next_market:
            try:
                run_realtime(interval_sec=10, iterations=1)
                stats["market_cycles"] += 1
                _log("REALTIME_BRIEF updated")
            except Exception as exc:
                stats["last_error"] = str(exc)
                _log(f"ERROR MARKET {exc}")
            finally:
                next_market = now + max(10, market_interval)

        if now >= next_snapshot:
            try:
                out = build_market_snapshot()
                stats["snapshot_cycles"] += 1
                _log(f"SNAPSHOT updated {out}")
            except Exception as exc:
                stats["last_error"] = str(exc)
                _log(f"ERROR SNAPSHOT {exc}")
            finally:
                next_snapshot = now + max(30, snapshot_interval)

        if now >= next_knowledge:
            try:
                build_knowledge()
                stats["knowledge_rebuilds"] += 1
                _log("KNOWLEDGE rebuilt")
            except Exception as exc:
                stats["last_error"] = str(exc)
                _log(f"ERROR KNOWLEDGE {exc}")
            finally:
                next_knowledge = now + max(60, knowledge_interval)

        if now >= next_agent_intel:
            try:
                intel = build_agent_intel()
                stats["agent_intel_cycles"] += 1
                _log(f"AGENT_INTEL updated intel={len(intel.get('intel', []))} errors={len(intel.get('errors', []))}")
            except Exception as exc:
                stats["last_error"] = str(exc)
                _log(f"ERROR AGENT_INTEL {exc}")
            finally:
                next_agent_intel = now + max(30, agent_intel_interval)

        METRICS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(2)

    stats["finished_utc"] = _now()
    METRICS_FILE.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    _log("END TRAINING LOOP")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Boucle d entrainement continue de l agent trading.")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--symbols", type=str, default="EURUSDm,XAUUSDm,BTCUSDm")
    parser.add_argument("--timeframes", type=str, default="M5,M15")
    parser.add_argument("--signal-interval", type=int, default=60)
    parser.add_argument("--market-interval", type=int, default=60)
    parser.add_argument("--snapshot-interval", type=int, default=900)
    parser.add_argument("--knowledge-interval", type=int, default=1800)
    parser.add_argument("--agent-intel-interval", type=int, default=300)
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    run_training(
        hours=args.hours,
        symbols=symbols,
        timeframes=tfs,
        signal_interval=args.signal_interval,
        market_interval=args.market_interval,
        snapshot_interval=args.snapshot_interval,
        knowledge_interval=args.knowledge_interval,
        agent_intel_interval=args.agent_intel_interval,
    )


if __name__ == "__main__":
    main()



