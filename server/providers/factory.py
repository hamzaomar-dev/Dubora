from __future__ import annotations

import os

from server.providers.base import AIProvider


def create_provider() -> AIProvider:
    provider_name = (os.getenv("DUBORA_AI_PROVIDER") or "groq").strip().lower()
    if provider_name == "groq":
        from server.providers.groq_provider import GroqProvider

        return GroqProvider()
    raise RuntimeError(f"Unsupported AI provider: {provider_name}")
