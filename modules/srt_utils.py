from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

_TIMESTAMP_RE = re.compile(
    r"^(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})(?:\s+.*)?$"
)


@dataclass(frozen=True)
class SubtitleBlock:
    index: int
    start: str
    end: str
    text: str


def parse_srt(content: str) -> list[SubtitleBlock]:
    """Parse SRT while preserving original indices and timestamps exactly."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip("\ufeff\n ")
    if not normalized:
        return []

    raw_blocks = re.split(r"\n\s*\n", normalized)
    blocks: list[SubtitleBlock] = []

    for raw in raw_blocks:
        lines = raw.split("\n")
        if len(lines) < 2:
            raise ValueError(f"Invalid SRT block: {raw[:80]!r}")

        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"Invalid subtitle index: {lines[0]!r}") from exc

        match = _TIMESTAMP_RE.match(lines[1].strip())
        if not match:
            raise ValueError(f"Invalid SRT timestamp line: {lines[1]!r}")

        text = "\n".join(lines[2:]).strip()
        if any(existing.index == index for existing in blocks):
            raise ValueError(f"Duplicate subtitle index: {index}")
        blocks.append(
            SubtitleBlock(
                index=index,
                start=match.group("start"),
                end=match.group("end"),
                text=text,
            )
        )

    return blocks


def build_srt(blocks: Iterable[SubtitleBlock]) -> str:
    parts: list[str] = []
    for block in blocks:
        parts.extend(
            [
                str(block.index),
                f"{block.start} --> {block.end}",
                block.text,
                "",
            ]
        )
    return "\n".join(parts).rstrip() + "\n"


def replace_text(
    original_blocks: list[SubtitleBlock],
    translations: dict[int, str],
) -> list[SubtitleBlock]:
    """Rebuild blocks using only original metadata and translated text."""
    output: list[SubtitleBlock] = []
    for block in original_blocks:
        translated = translations.get(block.index)
        if translated is None:
            raise ValueError(f"Missing translation for subtitle {block.index}")
        translated = str(translated).strip()
        if not translated and block.text.strip():
            raise ValueError(f"Empty translation for subtitle {block.index}")
        output.append(
            SubtitleBlock(
                index=block.index,
                start=block.start,
                end=block.end,
                text=translated,
            )
        )
    return output


def assert_integrity(
    original_blocks: list[SubtitleBlock],
    translated_blocks: list[SubtitleBlock],
) -> None:
    if len(original_blocks) != len(translated_blocks):
        raise ValueError(
            f"Subtitle block count mismatch: {len(original_blocks)} != {len(translated_blocks)}"
        )

    for original, translated in zip(original_blocks, translated_blocks):
        if original.index != translated.index:
            raise ValueError(f"Subtitle index changed at {original.index}")
        if original.start != translated.start or original.end != translated.end:
            raise ValueError(f"Subtitle timestamp changed at {original.index}")
