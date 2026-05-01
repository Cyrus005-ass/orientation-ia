from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from agent_config import AgentConfig, SYSTEM_PROMPT
from llm_provider import build_client, load_llm_settings
from manager_engine import analyze_symbol_manager
from manager_journal import add_trade_review, summary as manager_summary
from mt5_account import analyze_mt5_report
from mt5_signals import build_live_signal_pack
from screenshot_analyzer import analyze_chart_screenshot


class TradingAgent:
    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        load_dotenv()
        self.config = config or AgentConfig()
        self.llm = load_llm_settings()

        self.client: Optional[OpenAI] = build_client(self.llm)
        self.model: str = self.llm.text_model or self.config.model

        self.knowledge_text = self._load_file(self.config.knowledge_file)

    @staticmethod
    def _load_file(path: str) -> str:
        file_path = Path(path)
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8", errors="ignore").strip()

    def build_system_prompt(self) -> str:
        live_brief = self._load_file(self.config.live_context_file)
        snapshot = self._load_file(self.config.snapshot_file)

        sections = [SYSTEM_PROMPT]

        if self.knowledge_text:
            sections.append(
                "CONNAISSANCES INTERNES (documents utilisateur):\n"
                "- Utilise en priorite ces informations si pertinentes.\n"
                "- Cite explicitement la source locale quand tu l utilises.\n\n"
                + self.knowledge_text[:90000]
            )

        if snapshot:
            sections.append(
                "SNAPSHOT MARCHE RECENT:\n"
                "- Donnees de scraping recentes (prix/news/sentiment).\n\n"
                + snapshot[:15000]
            )

        if live_brief:
            sections.append(
                "FLUX TEMPS REEL (realtime brief):\n"
                "- Ce bloc est prioritaire pour le contexte court terme.\n\n"
                + live_brief[:15000]
            )

        return "\n\n".join(sections)

    def _chat(self, user_prompt: str) -> str:
        if self.client is None:
            return "Mode LLM indisponible: configure une API key (GROK_API_KEY ou OPENAI_API_KEY/API_KEY)."
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.build_system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or "Aucune reponse generee."

    def manager_analyze_symbol(self, symbol: str, risk_pct: float = 1.0, mode: str = "manual", rr_min: float = 2.5) -> dict:
        import os

        auto_enabled = os.getenv("AFR_AUTO_ENABLED", "0").strip() == "1"
        return analyze_symbol_manager(symbol=symbol, risk_pct=risk_pct, mode=mode, rr_min=rr_min, auto_enabled=auto_enabled)

    def manager_analyze_screenshot(self, image_path: str, context: str = "") -> str:
        return analyze_chart_screenshot(image_path, context)

    def manager_add_journal(self, payload: dict) -> dict:
        return add_trade_review(payload)

    def manager_journal_summary(self) -> dict:
        return manager_summary()

    def analyze(
        self,
        asset: str,
        horizon: str,
        risk_pct: str,
        user_level: str = "intermediaire",
        extra_context: str = "",
    ) -> str:
        user_prompt = (
            f"Actif: {asset}\n"
            f"Horizon: {horizon}\n"
            f"Risque max: {risk_pct}\n"
            f"Niveau utilisateur: {user_level}\n"
            f"Contexte complementaire: {extra_context or 'Aucun'}\n\n"
            "Donne une analyse complete selon le format demande."
        )
        return self._chat(user_prompt)

    def analyze_mt5(
        self,
        risk_pct: str,
        report_path: Optional[str] = None,
        terminal_days: Optional[int] = None,
        user_level: str = "intermediaire",
    ) -> str:
        payload = analyze_mt5_report(path=report_path, from_terminal_days=terminal_days)
        stats = payload["stats"]

        user_prompt = (
            "Analyse ce compte MetaTrader 5 comme un coach de performance trading.\n"
            f"Niveau utilisateur: {user_level}\n"
            f"Risque max defini: {risk_pct}\n"
            f"Source des donnees: {payload['source']}\n"
            f"Stats JSON: {stats}\n\n"
            "Fournis:\n"
            "1) Diagnostic (forces/faiblesses)\n"
            "2) Erreurs probables de discipline\n"
            "3) Plan d amelioration concret sur 30 jours\n"
            "4) Regles de gestion du risque personnalisees\n"
            "5) Point cle + avertissement legal"
        )
        return self._chat(user_prompt)

    def analyze_mt5_live_signals(
        self,
        symbols: list[str],
        timeframes: list[str],
        risk_pct: str,
        user_level: str = "intermediaire",
    ) -> str:
        payload = build_live_signal_pack(symbols=symbols, timeframes=timeframes)

        user_prompt = (
            "Tu recois des signaux MT5 lives structures (avec entry/sl/tp).\n"
            f"Niveau utilisateur: {user_level}\n"
            f"Risque max: {risk_pct}\n"
            f"Payload signaux: {payload}\n\n"
            "Produis un plan de decision clair:\n"
            "1) Quels signaux prioriser maintenant et pourquoi\n"
            "2) Directives d execution (ordre, timing, invalidation)\n"
            "3) Position sizing coherent avec le risque max\n"
            "4) Quels signaux ignorer\n"
            "5) Rappel strict de discipline + avertissement legal\n"
            "N execute aucun trade en mode manuel."
        )
        return self._chat(user_prompt)




