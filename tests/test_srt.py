from __future__ import annotations

from pathlib import Path

import pytest

from modules.srt_utils import SubtitleBlock, assert_integrity, build_srt, parse_srt, replace_text
from modules.transcriber import format_timestamp
from modules.translator import _should_retry, translate_srt, validate_translation_payload


SAMPLE = """1\r\n00:00:01,500 --> 00:00:04,200\r\nHello\r\nworld\r\n\r\n2\r\n00:00:05,000 --> 00:00:06,250\r\nHow are you?\r\n"""


class FakeGateway:
    def translate(self, items, cancel_event=None):
        return [{"id": int(item["id"]), "translation": f"AR:{item['text']}"} for item in items]


def test_parse_and_build_multiline_crlf_preserves_metadata():
    blocks = parse_srt(SAMPLE)
    assert len(blocks) == 2
    assert blocks[0].index == 1
    assert blocks[0].start == "00:00:01,500"
    assert blocks[0].end == "00:00:04,200"
    assert blocks[0].text == "Hello\nworld"
    rebuilt = parse_srt(build_srt(blocks))
    assert_integrity(blocks, rebuilt)


def test_replace_text_preserves_all_indices_and_timestamps():
    original = parse_srt(SAMPLE)
    translated = replace_text(original, {1: "مرحبًا\nبالعالم", 2: "كيف حالك؟"})
    assert_integrity(original, translated)
    assert translated[0].text == "مرحبًا\nبالعالم"


def test_integrity_rejects_timestamp_changes():
    original = parse_srt(SAMPLE)
    changed = [SubtitleBlock(1, "00:00:01,501", original[0].end, "x"), original[1]]
    with pytest.raises(ValueError, match="timestamp"):
        assert_integrity(original, changed)


def test_large_srt_keeps_block_count_and_timestamps():
    blocks = [
        SubtitleBlock(i, f"00:00:{(i % 50):02},000", f"00:00:{(i % 50):02},900", f"line {i}")
        for i in range(1, 151)
    ]
    parsed = parse_srt(build_srt(blocks))
    assert len(parsed) == 150
    assert_integrity(blocks, parsed)


def test_translation_payload_requires_exact_ids_and_count():
    payload = [{"id": 4, "translation": "أربعة"}, {"id": 5, "translation": "خمسة"}]
    assert validate_translation_payload(payload, [4, 5]) == {4: "أربعة", 5: "خمسة"}
    with pytest.raises(ValueError):
        validate_translation_payload([{"id": 4, "translation": "أربعة"}], [4, 5])
    with pytest.raises(ValueError):
        validate_translation_payload([{"id": 4, "translation": "أ"}, {"id": 4, "translation": "ب"}], [4, 5])


def test_translation_payload_rejects_empty_translation():
    with pytest.raises(ValueError, match="empty"):
        validate_translation_payload([{"id": 1, "translation": "   "}], [1])


def test_timestamp_rounding_rolls_over_cleanly():
    assert format_timestamp(59.9996) == "00:01:00,000"
    assert format_timestamp(3600.001) == "01:00:00,001"


def test_rate_limit_is_retryable():
    class RateLimitError(Exception):
        status_code = 429

    assert _should_retry(RateLimitError("rate limited")) is True


def test_gateway_translation_keeps_original_srt_metadata(tmp_path: Path):
    source = tmp_path / "in.srt"
    output = tmp_path / "out.srt"
    source.write_text(SAMPLE, encoding="utf-8")

    ok, message = translate_srt(str(source), str(output), gateway_client=FakeGateway())
    assert ok, message

    original = parse_srt(source.read_text(encoding="utf-8"))
    translated = parse_srt(output.read_text(encoding="utf-8"))
    assert_integrity(original, translated)
    assert translated[0].text.startswith("AR:")
