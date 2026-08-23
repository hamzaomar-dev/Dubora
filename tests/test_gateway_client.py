from __future__ import annotations

import httpx

from modules.gateway_client import GatewayClient


def test_translate_retries_429_then_succeeds(monkeypatch):
    calls = {"count": 0}

    def fake_request(method, url, **kwargs):
        calls["count"] += 1
        request = httpx.Request(method, url)
        if calls["count"] < 3:
            return httpx.Response(429, json={"detail": "slow down"}, request=request)
        return httpx.Response(
            200,
            json={"items": [{"id": 7, "translation": "مرحبا"}]},
            request=request,
        )

    monkeypatch.setattr("modules.gateway_client.httpx.request", fake_request)
    monkeypatch.setattr("modules.gateway_client.DEFAULT_DELAYS", (0, 0, 0))

    client = GatewayClient("http://gateway.test")
    result = client.translate([{"id": 7, "text": "hello"}])
    assert result == [{"id": 7, "translation": "مرحبا"}]
    assert calls["count"] == 3


def test_health_failure_is_safe(monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("modules.gateway_client.httpx.get", fail)
    result = GatewayClient("http://gateway.test").health()
    assert result["ok"] is False
