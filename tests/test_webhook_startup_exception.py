import asyncio
import importlib

import pytest


def test_webhook_startup_handles_openai_failure(monkeypatch):
    """Ensure startup exits when assistant creation fails."""

    # Provide required environment variables before importing the module
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ok")

    webhook_server = importlib.import_module("webhook_server")

    class DummyResp:
        def json(self):
            return {"result": {"username": "bot", "id": 1}}

    class DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def get(self, *args, **kwargs):
            return DummyResp()

        async def post(self, *args, **kwargs):
            return DummyResp()

    monkeypatch.setattr(webhook_server.httpx, "AsyncClient", lambda *a, **k: DummyAsyncClient())

    async def fail_setup():
        raise RuntimeError("boom")

    monkeypatch.setattr(webhook_server.engine, "setup_assistant", fail_setup)

    with pytest.raises(SystemExit):
        asyncio.run(webhook_server.startup())
