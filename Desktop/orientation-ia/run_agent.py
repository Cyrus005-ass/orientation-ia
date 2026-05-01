from agent_config import ONBOARDING_MESSAGE
from trading_agent import TradingAgent

class InputAborted(Exception):
    pass


def _safe_input(prompt: str) -> str:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt) as exc:
        raise InputAborted from exc


def run_market(agent: TradingAgent) -> None:
    print(ONBOARDING_MESSAGE)
    asset = _safe_input("\nActif: ").strip()
    horizon = _safe_input("Horizon: ").strip()
    risk = _safe_input("Risque max (%): ").strip()
    level = _safe_input("Niveau (debutant/intermediaire/avance/pro): ").strip() or "intermediaire"
    context = _safe_input("Contexte optionnel (news/prix/niveaux): ").strip()

    if not asset or not horizon or not risk:
        print("Parametres manquants: actif, horizon et risque sont obligatoires.")
        return

    result = agent.analyze(
        asset=asset,
        horizon=horizon,
        risk_pct=risk,
        user_level=level,
        extra_context=context,
    )
    print("\n" + "=" * 72)
    print(result)
    print("=" * 72)


def run_manager_symbol(agent: TradingAgent) -> None:
    symbol = _safe_input("Symbole (ex: XAUUSDm): ").strip() or "XAUUSDm"
    mode = _safe_input("Mode (manual/semi/auto): ").strip() or "manual"
    risk = float((_safe_input("Risque max % (ex: 1): ").strip() or "1").replace(",", "."))
    rr_min = float((_safe_input("RR minimum (ex: 2.5): ").strip() or "2.5").replace(",", "."))

    result = agent.manager_analyze_symbol(symbol=symbol, risk_pct=risk, mode=mode, rr_min=rr_min)
    print("\n" + "=" * 72)
    if result.get("ok"):
        print(result.get("formatted", ""))
        if result.get("decision", {}).get("execution"):
            print("\nExecution:")
            print(result["decision"]["execution"])
    else:
        print(result)
    print("=" * 72)


def run_manager_screenshot(agent: TradingAgent) -> None:
    path = _safe_input("Chemin screenshot: ").strip()
    context = _safe_input("Contexte strategy (optionnel): ").strip()
    if not path:
        print("Chemin screenshot requis.")
        return
    result = agent.manager_analyze_screenshot(path, context)
    print("\n" + "=" * 72)
    print(result)
    print("=" * 72)


def run_manager_journal(agent: TradingAgent) -> None:
    print("\nAjout revue trade")
    symbol = _safe_input("Symbol: ").strip().upper()
    tf = _safe_input("Timeframe: ").strip().upper()
    decision = _safe_input("Decision prise (BUY/SELL/WAIT): ").strip().upper()
    result = _safe_input("Resultat (WIN/LOSS): ").strip().upper()
    rr = float((_safe_input("RR obtenu: ").strip() or "0").replace(",", "."))
    reason = _safe_input("Pourquoi gagne/perdu: ").strip()
    mistakes = _safe_input("Erreurs (separees par virgule): ").strip()

    payload = {
        "symbol": symbol,
        "timeframe": tf,
        "decision": decision,
        "result": result,
        "rr": rr,
        "reason": reason,
        "mistakes": [m.strip() for m in mistakes.split(",") if m.strip()],
    }
    agent.manager_add_journal(payload)
    s = agent.manager_journal_summary()

    print("\n" + "=" * 72)
    print("Journal mis a jour")
    print(s)
    print("=" * 72)


def run_mt5_account(agent: TradingAgent) -> None:
    print("\nMode analyse compte MT5")
    risk = _safe_input("Risque max (%): ").strip() or "1%"
    level = _safe_input("Niveau (debutant/intermediaire/avance/pro): ").strip() or "intermediaire"
    source = _safe_input("Source donnees MT5 (1=rapport CSV/HTML, 2=terminal): ").strip() or "1"

    if source == "2":
        days_raw = _safe_input("Historique terminal en jours (ex: 90): ").strip() or "90"
        days = int(days_raw)
        result = agent.analyze_mt5(risk_pct=risk, terminal_days=days, user_level=level)
    else:
        report = _safe_input("Chemin rapport MT5 CSV/HTML: ").strip()
        if not report:
            print("Chemin rapport obligatoire.")
            return
        result = agent.analyze_mt5(risk_pct=risk, report_path=report, user_level=level)

    print("\n" + "=" * 72)
    print(result)
    print("=" * 72)


def main() -> None:
    agent = TradingAgent()

    print("\n=== AGENT TRADING IA ===")
    print("1) Analyse marche")
    print("2) Analyse compte MetaTrader 5")
    print("3) Signaux live MT5 + directives de decision")
    print("4) Manager symbol strict (BUY/SELL/WAIT)")
    print("5) Manager screenshot MT5")
    print("6) Journal manager (ajouter revue)")

    try:
        mode = _safe_input("Choix (1/2/3/4/5/6): ").strip() or "1"

        if mode == "2":
            run_mt5_account(agent)
        elif mode == "4":
            run_manager_symbol(agent)
        elif mode == "5":
            run_manager_screenshot(agent)
        elif mode == "6":
            run_manager_journal(agent)
        elif mode == "3":
            symbols_raw = _safe_input("Symboles (ex: EURUSDm,XAUUSDm,BTCUSDm): ").strip() or "EURUSDm,XAUUSDm,BTCUSDm"
            tfs_raw = _safe_input("Timeframes (ex: M5,M15,H1): ").strip() or "M5,M15,H1"
            risk = _safe_input("Risque max (%): ").strip() or "1%"
            level = _safe_input("Niveau (debutant/intermediaire/avance/pro): ").strip() or "intermediaire"
            symbols = [s.strip() for s in symbols_raw.split(",") if s.strip()]
            tfs = [t.strip().upper() for t in tfs_raw.split(",") if t.strip()]
            result = agent.analyze_mt5_live_signals(symbols=symbols, timeframes=tfs, risk_pct=risk, user_level=level)
            print("\n" + "=" * 72)
            print(result)
            print("=" * 72)
        else:
            run_market(agent)
    except InputAborted:
        print("Mode interactif requis: execution interrompue proprement.")


if __name__ == "__main__":
    main()


