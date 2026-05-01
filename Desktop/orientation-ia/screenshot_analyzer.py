from __future__ import annotations

import base64
from pathlib import Path

from dotenv import load_dotenv

from llm_provider import build_client, load_llm_settings


def analyze_chart_screenshot(image_path: str, context: str = "") -> str:
    load_dotenv()
    settings = load_llm_settings()
    client = build_client(settings)
    if client is None:
        return "Analyse screenshot indisponible: API key manquante (GROK_API_KEY ou OPENAI_API_KEY/API_KEY)."

    p = Path(image_path)
    if not p.exists():
        return f"Image introuvable: {image_path}"

    prompt = (
        "Tu es lecteur de screenshot MT5 et manager pro. Aucun indicateur.\n"
        "Analyse en contexte multi-timeframe (MN/W1/D1/H4/H1/M15 si visible).\n"
        "Identifie zones, structure, BOS/CHOCH, fake breakout, piege liquidite, entree, SL, TP.\n"
        "Conditions strictes: zone D1/H4, structure H4, confirmation H1/M15, RR >= 1:2.5, SL/spread logiques.\n"
        "Format strict: SYMBOL, Decision, Contexte, Entree, SL, TP, RR, Lot, Rappel discipline.\n"
        "Si setup non valide: Decision WAIT et ecris explicitement NE TRADE PAS.\n"
        f"Contexte utilisateur: {context or 'Aucun'}"
    )

    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    ext = p.suffix.lower()
    mime = "image/png" if ext == ".png" else "image/jpeg"

    resp = client.chat.completions.create(
        model=settings.vision_model,
        messages=[
            {"role": "system", "content": "Lecteur de screenshots trading professionnel."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": "data:" + mime + ";base64," + b64}},
                ],
            },
        ],
    )
    return resp.choices[0].message.content or "Aucune reponse screenshot."
