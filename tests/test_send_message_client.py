import importlib

import httpx
import pytest


@pytest.mark.asyncio
async def test_send_multiple_messages(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "key")

    webhook_server = importlib.import_module("webhook_server")
    webhook_server = importlib.reload(webhook_server)
    original_client = webhook_server.tg_client

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    webhook_server.tg_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    )
    await original_client.aclose()

    class DummyEngine:
        async def aclose(self):
            pass

    monkeypatch.setattr(webhook_server, "engine", DummyEngine())

    for i in range(3):
        await webhook_server.send_message(1, f"msg {i}")

    assert len(calls) == 3

    await webhook_server.shutdown()
    assert webhook_server.tg_client.is_closed
