from __future__ import annotations

from fastapi.testclient import TestClient

import server.app as gateway_app


class FakeProvider:
    name = "fake"

    def transcribe(self, filename: str, content: bytes):
        return [{"start": 0.0, "end": 1.25, "text": "hello"}]

    def translate(self, items: list[dict]):
        return [{"id": item["id"], "translation": f"AR:{item['text']}"} for item in items]


def setup_module():
    gateway_app._provider = FakeProvider()


def test_health():
    client = TestClient(gateway_app.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_translate_validates_and_returns_items():
    client = TestClient(gateway_app.app)
    response = client.post(
        "/v1/translate",
        headers={"X-Dubora-Client": "test-translate"},
        json={"items": [{"id": 1, "text": "Hello"}, {"id": 2, "text": "World"}]},
    )
    assert response.status_code == 200
    assert response.json()["items"][0] == {"id": 1, "translation": "AR:Hello"}


def test_transcribe_rejects_unsupported_extension():
    client = TestClient(gateway_app.app)
    response = client.post(
        "/v1/transcribe",
        headers={"X-Dubora-Client": "test-audio-bad"},
        files={"file": ("audio.exe", b"abc", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_transcribe_returns_segments():
    client = TestClient(gateway_app.app)
    response = client.post(
        "/v1/transcribe",
        headers={"X-Dubora-Client": "test-audio-good"},
        files={"file": ("audio.wav", b"RIFFfake", "audio/wav")},
    )
    assert response.status_code == 200
    assert response.json()["segments"][0]["text"] == "hello"
