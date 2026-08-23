from __future__ import annotations

from typing import Protocol


class AIProvider(Protocol):
    name: str

    def transcribe(self, filename: str, content: bytes) -> list[dict]: ...

    def translate(self, items: list[dict]) -> list[dict]: ...
