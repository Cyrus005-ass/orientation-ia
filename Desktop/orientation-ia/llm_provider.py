from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    api_key: str | None
    base_url: str
    text_model: str
    vision_model: str


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is None:
            continue
        value = value.strip()
        if value:
            return value
    return None


def load_llm_settings() -> LLMSettings:
    provider = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()

    if provider == "grok":
        api_key = _first_non_empty(
            os.getenv("GROK_API_KEY"),
            os.getenv("XAI_API_KEY"),
            os.getenv("LLM_API_KEY"),
            os.getenv("API_KEY"),
            os.getenv("OPENAI_API_KEY"),
        )
        base_url = _first_non_empty(
            os.getenv("GROK_BASE_URL"),
            os.getenv("LLM_BASE_URL"),
            os.getenv("BASE_URL"),
        ) or "https://api.x.ai/v1"
        text_model = _first_non_empty(
            os.getenv("AFRI_MODEL_TEXT"),
            os.getenv("GROK_MODEL"),
            os.getenv("MODEL"),
        ) or "grok-2-latest"
        vision_model = _first_non_empty(
            os.getenv("AFRI_MODEL_VISION"),
            os.getenv("GROK_VISION_MODEL"),
            os.getenv("VISION_MODEL"),
            text_model,
        ) or text_model
        return LLMSettings(provider=provider, api_key=api_key, base_url=base_url, text_model=text_model, vision_model=vision_model)

    api_key = _first_non_empty(
        os.getenv("OPENAI_API_KEY"),
        os.getenv("API_KEY"),
        os.getenv("LLM_API_KEY"),
    )
    base_url = _first_non_empty(
        os.getenv("OPENAI_BASE_URL"),
        os.getenv("LLM_BASE_URL"),
        os.getenv("BASE_URL"),
    ) or "https://api.openai.com/v1"
    text_model = _first_non_empty(
        os.getenv("AFRI_MODEL_TEXT"),
        os.getenv("MODEL"),
    ) or "gpt-4o-mini"
    vision_model = _first_non_empty(
        os.getenv("AFRI_MODEL_VISION"),
        os.getenv("VISION_MODEL"),
        text_model,
    ) or text_model
    return LLMSettings(provider=provider, api_key=api_key, base_url=base_url, text_model=text_model, vision_model=vision_model)


def build_client(settings: LLMSettings) -> OpenAI | None:
    if not settings.api_key:
        return None
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url)

