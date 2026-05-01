from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_agent_intel import build_agent_intel
from mt5_execution import execute_signal, list_candidates
from mt5_signals import build_live_signal_pack
from scrape_market_intensive import build_market_snapshot
from signal_learning import evaluate_pending_signals
from train_agent import build_knowledge

LIVE_DIR = Path("knowledge/live")
STATE_FILE = LIVE_DIR / "profit_mode_state.json"
LOG_FILE = LIVE_DIR / "profit_mode.log"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(msg: str) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{_now()}] {msg}"
    print(line)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "started_utc": _now(),
            "cycles": 0,
            "executed_count": 0,
            "skipped_count": 0,
            "last_cycle_utc": None,
            "last_exec_utc": None,
            "last_exec_symbol": None,
            "last_exec_signal_id": None,
            "cooldown_by_symbol": {},
            "recent_fingerprints": [],
            "last_error": None,
        }
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {
            "started_utc": _now(),
            "cycles": 0,
            "executed_count": 0,
            "skipped_count": 0,
            "last_cycle_utc": None,
            "last_exec_utc": None,
            "last_exec_symbol": None,
            "last_exec_signal_id": None,
            "cooldown_by_symbol": {},
            "recent_fingerprints": [],
            "last_error": "state_read_error",
        }


def _save_state(state: dict[str, Any]) -> None:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _confidence_value(name: str) -> int:
    m = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    return m.get(str(name or "").strip().upper(), 0)


def _candidate_fingerprint(c: dict[str, Any]) -> str:
    return f"{c.get('symbol')}|{c.get('timeframe')}|{c.get('direction')}|{c.get('entry')}|{c.get('stop_loss')}|{c.get('tp1')}"


def _pick_best_signal(
    signals_payload: dict[str, Any],
    min_rr: float,
    min_confidence: str,
    symbol_cooldowns: dict[str, float],
    cooldown_min: int,
    recent_fingerprints: set[str],
) -> tuple[int | None, str]:
    target_conf = _confidence_value(min_confidence)
    now = time.time()

    trade_signals = [s for s in (signals_payload.get("signals") or []) if isinstance(s, dict) and s.get("status") == "TRADE"]
    if not trade_signals:
        return None, "Aucun TRADE dans le cycle"

    candidates = list_candidates()
    if not candidates:
        return None, "Aucun candidat execution"

    filtered: list[tuple[int, dict[str, Any], float]] = []
    for idx, sig in enumerate(trade_signals, start=1):
        try:
            rr = float(sig.get("rr") or 0.0)
        except Exception:
            rr = 0.0
        if rr < min_rr:
            continue

        conf = _confidence_value(sig.get("confidence", ""))
        if conf < target_conf:
            continue

        fp = _candidate_fingerprint(sig)
        if fp in recent_fingerprints:
            continue

        sym = str(sig.get("symbol") or "")
        cd_until = float(symbol_cooldowns.get(sym, 0.0) or 0.0)
        if cd_until > now:
            continue

        score = float(sig.get("confluence_score") or 0)
        filtered.append((idx, sig, score))

    if not filtered:
        return None, "Tous les signaux filtres (RR/confiance/cooldown/doublon)"

    best = max(filtered, key=lambda x: x[2])
    sid, sig, score = best
    return sid, f"signal_id={sid} {sig.get('symbol')} {sig.get('timeframe')} score={score}"


def run_profit_mode(
    symbols: list[str],
    timeframes: list[str],
    risk_pct: float,
    min_rr: float,
    min_confidence: str,
    cycle_sec: int,
    cooldown_min: int,
    market_interval: int,
    knowledge_interval: int,
    intel_interval: int,
    dry_run: bool,
) -> None:
    state = _load_state()
    _log(
        "PROFIT_MODE_START "
        f"symbols={symbols} timeframes={timeframes} risk_pct={risk_pct} min_rr={min_rr} "
        f"min_conf={min_confidence} dry_run={dry_run}"
    )

    next_market = 0.0
    next_knowledge = 0.0
    next_intel = 0.0

    while True:
        state["cycles"] = int(state.get("cycles", 0) or 0) + 1
        state["last_cycle_utc"] = _now()
        now = time.time()

        try:
            if now >= next_market:
                try:
                    out = build_market_snapshot()
                    _log(f"CYCLE_MARKET snapshot={out}")
                except Exception as exc:
                    state["last_error"] = f"market_snapshot: {exc}"
                    _log(f"CYCLE_MARKET_ERROR {exc}")
                finally:
                    next_market = now + max(60, market_interval)

            if now >= next_knowledge:
                try:
                    build_knowledge()
                    _log("CYCLE_KNOWLEDGE rebuilt")
                except Exception as exc:
                    state["last_error"] = f"knowledge: {exc}"
                    _log(f"CYCLE_KNOWLEDGE_ERROR {exc}")
                finally:
                    next_knowledge = now + max(300, knowledge_interval)

            if now >= next_intel:
                try:
                    intel = build_agent_intel()
                    _log(f"CYCLE_AGENT_INTEL intel={len(intel.get('intel', []))} errors={len(intel.get('errors', []))}")
                except Exception as exc:
                    state["last_error"] = f"agent_intel: {exc}"
                    _log(f"CYCLE_AGENT_INTEL_ERROR {exc}")
                finally:
                    next_intel = now + max(60, intel_interval)

            payload = build_live_signal_pack(symbols=symbols, timeframes=timeframes)
            learning = evaluate_pending_signals()
            _log(
                "CYCLE_SIGNAL "
                f"trades={len([s for s in payload.get('signals', []) if s.get('status') == 'TRADE'])} "
                f"errors={len(payload.get('errors', []))} learning_updated={learning.get('updated', 0)}"
            )

            cooldowns = state.setdefault("cooldown_by_symbol", {})
            recent = state.setdefault("recent_fingerprints", [])
            recent_set = set(str(x) for x in recent[-50:])

            signal_id, reason = _pick_best_signal(
                signals_payload=payload,
                min_rr=min_rr,
                min_confidence=min_confidence,
                symbol_cooldowns=cooldowns,
                cooldown_min=cooldown_min,
                recent_fingerprints=recent_set,
            )
            if signal_id is None:
                state["skipped_count"] = int(state.get("skipped_count", 0) or 0) + 1
                _log(f"CYCLE_SKIP {reason}")
                _save_state(state)
                time.sleep(max(15, cycle_sec))
                continue

            if dry_run:
                preview = execute_signal(signal_id=signal_id, risk_pct=risk_pct, live=False, confirm="")
                _log(f"DRY_RUN {reason} -> {preview.message}")
                state["skipped_count"] = int(state.get("skipped_count", 0) or 0) + 1
            else:
                result = execute_signal(signal_id=signal_id, risk_pct=risk_pct, live=True, confirm="EXECUTE")
                if result.ok:
                    signal = (result.payload or {}).get("signal", {})
                    sym = str(signal.get("symbol") or "")
                    if sym:
                        cooldowns[sym] = time.time() + cooldown_min * 60
                    fp = _candidate_fingerprint(signal)
                    recent.append(fp)
                    if len(recent) > 200:
                        del recent[:-200]

                    state["executed_count"] = int(state.get("executed_count", 0) or 0) + 1
                    state["last_exec_utc"] = _now()
                    state["last_exec_symbol"] = sym
                    state["last_exec_signal_id"] = signal_id
                    _log(f"LIVE_EXEC_OK {reason} -> {result.message}")
                else:
                    state["skipped_count"] = int(state.get("skipped_count", 0) or 0) + 1
                    _log(f"LIVE_EXEC_FAIL {reason} -> {result.message}")

            _save_state(state)
        except Exception as exc:
            state["last_error"] = str(exc)
            _save_state(state)
            _log(f"CYCLE_ERROR {exc}")

        time.sleep(max(15, cycle_sec))


def main() -> None:
    parser = argparse.ArgumentParser(description="Mode profit: signaux + apprentissage + intelligence + execution MT5 en boucle.")
    parser.add_argument("--symbols", type=str, default="EURUSDm,XAUUSDm,BTCUSDm")
    parser.add_argument("--timeframes", type=str, default="M5,M15")
    parser.add_argument("--risk-pct", type=float, default=0.5)
    parser.add_argument("--min-rr", type=float, default=2.5)
    parser.add_argument("--min-confidence", type=str, default="Medium", choices=["Low", "Medium", "High"])
    parser.add_argument("--cycle-sec", type=int, default=90)
    parser.add_argument("--cooldown-min", type=int, default=30)
    parser.add_argument("--market-interval", type=int, default=600)
    parser.add_argument("--knowledge-interval", type=int, default=1800)
    parser.add_argument("--intel-interval", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    tfs = [t.strip().upper() for t in args.timeframes.split(",") if t.strip()]

    run_profit_mode(
        symbols=symbols,
        timeframes=tfs,
        risk_pct=float(args.risk_pct),
        min_rr=float(args.min_rr),
        min_confidence=str(args.min_confidence),
        cycle_sec=int(args.cycle_sec),
        cooldown_min=int(args.cooldown_min),
        market_interval=int(args.market_interval),
        knowledge_interval=int(args.knowledge_interval),
        intel_interval=int(args.intel_interval),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    main()

