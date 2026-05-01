from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JOURNAL_FILE = Path("knowledge/live/trader_journal.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iter_rows() -> list[dict[str, Any]]:
    if not JOURNAL_FILE.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in JOURNAL_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def add_trade_review(row: dict[str, Any]) -> dict[str, Any]:
    JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_utc": _now(),
        "symbol": str(row.get("symbol", "")).upper(),
        "timeframe": str(row.get("timeframe", "")),
        "decision": str(row.get("decision", "")),
        "result": str(row.get("result", "")).upper(),
        "rr": float(row.get("rr", 0.0) or 0.0),
        "reason": str(row.get("reason", "")),
        "mistakes": row.get("mistakes", []),
        "notes": str(row.get("notes", "")),
    }
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def summary() -> dict[str, Any]:
    rows = _iter_rows()
    wins = 0
    losses = 0
    by_symbol: dict[str, dict[str, int]] = {}
    mistakes: dict[str, int] = {}
    by_tf: dict[str, dict[str, int]] = {}

    for r in rows:
        sym = str(r.get("symbol", "N/A"))
        tf = str(r.get("timeframe", "N/A"))
        res = str(r.get("result", "")).upper()

        by_symbol.setdefault(sym, {"wins": 0, "losses": 0, "total": 0})
        by_symbol[sym]["total"] += 1

        by_tf.setdefault(tf, {"wins": 0, "losses": 0, "total": 0})
        by_tf[tf]["total"] += 1

        if res == "WIN":
            wins += 1
            by_symbol[sym]["wins"] += 1
            by_tf[tf]["wins"] += 1
        elif res == "LOSS":
            losses += 1
            by_symbol[sym]["losses"] += 1
            by_tf[tf]["losses"] += 1

        for m in r.get("mistakes", []) or []:
            key = str(m).strip().lower()
            if not key:
                continue
            mistakes[key] = mistakes.get(key, 0) + 1

    top_mistakes = sorted(mistakes.items(), key=lambda x: x[1], reverse=True)[:8]

    best_symbol = None
    best_score = -10**9
    for sym, st in by_symbol.items():
        score = st["wins"] - st["losses"]
        if score > best_score:
            best_score = score
            best_symbol = sym

    best_tf = None
    best_tf_score = -10**9
    for tf, st in by_tf.items():
        score = st["wins"] - st["losses"]
        if score > best_tf_score:
            best_tf_score = score
            best_tf = tf

    total = wins + losses
    win_rate = (wins / total * 100.0) if total else 0.0

    return {
        "total_reviews": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(win_rate, 2),
        "best_symbol": best_symbol,
        "best_timeframe": best_tf,
        "top_mistakes": [{"mistake": k, "count": v} for k, v in top_mistakes],
        "by_symbol": by_symbol,
        "by_timeframe": by_tf,
    }


def discipline_reminders() -> list[str]:
    s = summary()
    reminders: list[str] = []

    for m in s.get("top_mistakes", []):
        txt = m["mistake"]
        if "hors zone" in txt or "outside zone" in txt:
            reminders.append("Tu perds souvent quand tu trades hors zone H4.")
        if "overtrad" in txt:
            reminders.append("Stop overtrading: attends uniquement les setups valides.")
        if "sl move" in txt or "deplacer sl" in txt:
            reminders.append("Ne deplace pas ton SL contre toi.")

    if s.get("best_symbol"):
        reminders.append(f"Tes meilleurs resultats recents sont sur {s['best_symbol']}.")
    if s.get("best_timeframe"):
        reminders.append(f"Ton meilleur timeframe recent est {s['best_timeframe']}.")

    seen = set()
    uniq: list[str] = []
    for r in reminders:
        if r in seen:
            continue
        seen.add(r)
        uniq.append(r)
    return uniq[:5]
