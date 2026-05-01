from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _news_red_within(minutes: int = 15) -> bool:
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        data = requests.get(url, timeout=10).json()
    except Exception:
        return False

    now = datetime.now(timezone.utc)
    end = now + timedelta(minutes=minutes)
    for item in data if isinstance(data, list) else []:
        if str(item.get("impact", "")).lower() != "high":
            continue
        date_str = str(item.get("date", "")).strip()
        time_str = str(item.get("time", "")).strip()
        if not date_str or not time_str:
            continue
        try:
            dt = datetime.fromisoformat(f"{date_str}T{time_str}:00+00:00")
        except Exception:
            continue
        if now <= dt <= end:
            return True
    return False


def can_trade(account: dict[str, Any], signal: dict[str, Any]) -> tuple[bool, str]:
    capital = _num(account.get("balance") or account.get("equity") or account.get("capital"), 0.0)
    if capital <= 0:
        return False, "Capital indisponible"

    daily_loss = _num(account.get("daily_loss_pct") or account.get("loss_today_pct"), 0.0)
    if daily_loss > 3.0:
        return False, "Perte jour > 3% du capital"

    open_risk = _num(account.get("open_risk_pct") or account.get("risk_open_pct"), 0.0)
    if open_risk > 6.0:
        return False, "Risque ouvert > 6%"

    margin_level = _num(account.get("margin_level") or account.get("free_margin_level"), 1000.0)
    if margin_level < 200.0:
        return False, "Marge < 200%"

    if signal.get("news_blackout") is True or _news_red_within(15):
        return False, "News rouge dans les 15 prochaines minutes"

    return True, "OK"
