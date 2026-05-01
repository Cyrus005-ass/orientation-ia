from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from mt5_connection import initialize_mt5


@dataclass
class MT5Stats:
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    gross_profit: float
    gross_loss: float
    net_profit: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    expectancy: float
    max_drawdown: float
    best_trade: float
    worst_trade: float


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renames = {}
    for c in df.columns:
        key = str(c).strip().lower()
        if key in {"profit", "profit/loss", "gain", "result", "resultat"}:
            renames[c] = "profit"
        elif key in {"close time", "time", "date", "date/heure", "fermeture", "time close"}:
            renames[c] = "close_time"
        elif key in {"symbol", "symbole"}:
            renames[c] = "symbol"
        elif key in {"type", "deal", "transaction"}:
            renames[c] = "type"
        elif key in {"volume", "lots", "lot"}:
            renames[c] = "volume"

    return df.rename(columns=renames)


def _coerce_profit(df: pd.DataFrame) -> pd.DataFrame:
    if "profit" not in df.columns:
        raise ValueError("Colonne profit introuvable dans le rapport MT5.")

    s = (
        df["profit"].astype(str)
        .str.replace("\u202f", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    df["profit"] = pd.to_numeric(s, errors="coerce")
    return df.dropna(subset=["profit"])


def _equity_curve_drawdown(profits: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in profits:
        equity += p
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_stats(df: pd.DataFrame) -> MT5Stats:
    profits = df["profit"].tolist()
    if not profits:
        raise ValueError("Aucun trade exploitable trouve dans le rapport MT5.")

    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]

    total = len(profits)
    wins_n = len(wins)
    losses_n = len(losses)
    gross_profit = float(sum(wins))
    gross_loss = float(abs(sum(losses)))
    net = float(sum(profits))
    pf = gross_profit / gross_loss if gross_loss > 0 else math.inf

    avg_win = float(sum(wins) / wins_n) if wins_n else 0.0
    avg_loss = float(abs(sum(losses) / losses_n)) if losses_n else 0.0
    expectancy = net / total if total else 0.0
    max_dd = _equity_curve_drawdown(profits)

    return MT5Stats(
        total_trades=total,
        wins=wins_n,
        losses=losses_n,
        win_rate_pct=(wins_n / total) * 100.0 if total else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net,
        profit_factor=pf,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        max_drawdown=max_dd,
        best_trade=max(profits),
        worst_trade=min(profits),
    )


def load_mt5_report(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Rapport introuvable: {path}")

    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p, sep=None, engine="python")
    elif p.suffix.lower() in {".htm", ".html"}:
        tables = pd.read_html(p)
        if not tables:
            raise ValueError("Aucun tableau detecte dans le rapport HTML MT5.")
        df = max(tables, key=lambda t: t.shape[0])
    else:
        raise ValueError("Format non supporte. Utilise CSV ou HTML exporte par MT5.")

    return _coerce_profit(_normalize_columns(df))


def load_mt5_from_terminal(days: int = 90) -> pd.DataFrame:
    try:
        import MetaTrader5 as mt5
    except Exception as exc:
        raise RuntimeError("Module MetaTrader5 indisponible. Installe-le et connecte ton terminal.") from exc

    ok, err = initialize_mt5(mt5)
    if not ok:
        raise RuntimeError(f"Impossible d initialiser MT5: {err}")

    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        deals = mt5.history_deals_get(start, end)
        if deals is None:
            raise RuntimeError(f"Erreur MT5 history_deals_get: {mt5.last_error()}")

        rows = []
        for d in deals:
            rows.append(
                {
                    "close_time": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                    "symbol": d.symbol,
                    "type": d.type,
                    "volume": d.volume,
                    "profit": d.profit,
                }
            )

        if not rows:
            raise ValueError("Aucun deal recupere depuis le terminal MT5.")

        return pd.DataFrame(rows)
    finally:
        mt5.shutdown()


def analyze_mt5_report(path: Optional[str] = None, from_terminal_days: Optional[int] = None) -> dict:
    if from_terminal_days is not None:
        df = load_mt5_from_terminal(days=from_terminal_days)
        source = f"MT5 terminal (history_deals_get, {from_terminal_days} jours)"
    else:
        if not path:
            raise ValueError("Fournis un chemin de rapport MT5 ou from_terminal_days.")
        df = load_mt5_report(path)
        source = f"Rapport MT5: {path}"

    if "close_time" in df.columns:
        try:
            df["_ct"] = pd.to_datetime(df["close_time"], errors="coerce")
            df = df.sort_values("_ct")
        except Exception:
            pass

    stats = _compute_stats(df)
    return {
        "source": source,
        "stats": stats.__dict__,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def save_analysis_json(payload: dict, out_path: str = "knowledge/live/mt5_account_analysis.json") -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def save_analysis_text(payload: dict, out_path: str = "knowledge/live/mt5_account_analysis.txt") -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    s = payload["stats"]
    lines = [
        f"[generated_utc] {payload['generated_utc']}",
        f"[source] {payload['source']}",
        "",
        f"total_trades={s['total_trades']}",
        f"wins={s['wins']}",
        f"losses={s['losses']}",
        f"win_rate_pct={s['win_rate_pct']:.2f}",
        f"gross_profit={s['gross_profit']:.2f}",
        f"gross_loss={s['gross_loss']:.2f}",
        f"net_profit={s['net_profit']:.2f}",
        f"profit_factor={s['profit_factor']:.3f}",
        f"avg_win={s['avg_win']:.2f}",
        f"avg_loss={s['avg_loss']:.2f}",
        f"expectancy={s['expectancy']:.2f}",
        f"max_drawdown={s['max_drawdown']:.2f}",
        f"best_trade={s['best_trade']:.2f}",
        f"worst_trade={s['worst_trade']:.2f}",
    ]
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyse un compte MetaTrader 5 depuis rapport ou terminal.")
    parser.add_argument("--report", type=str, help="Chemin du rapport MT5 (CSV/HTML)")
    parser.add_argument("--terminal-days", type=int, help="Recupere les deals depuis MT5 terminal sur N jours")
    args = parser.parse_args()

    payload = analyze_mt5_report(path=args.report, from_terminal_days=args.terminal_days)
    json_file = save_analysis_json(payload)
    txt_file = save_analysis_text(payload)

    print("Analyse MT5 terminee")
    print(f"JSON: {json_file}")
    print(f"TXT : {txt_file}")



