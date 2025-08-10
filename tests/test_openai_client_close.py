import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import telethon


class DummyTelegramClient:
    def on(self, *args, **kwargs):
        def decorator(func):
            return func
        return decorator

    async def start(self, *args, **kwargs):
        pass

    async def get_me(self):
        return SimpleNamespace(username="bot", id=1)

    async def run_until_disconnected(self):
        pass


class DummyStringSession:
    def __init__(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_openai_client_closed(monkeypatch):
    envs = {
        "OPENAI_API_KEY": "key",
        "TELEGRAM_API_ID": "1",
        "TELEGRAM_API_HASH": "hash",
        "TELEGRAM_PHONE": "123",
        "TELEGRAM_SESSION_STRING": "sess",
    }
    for k, v in envs.items():
        monkeypatch.setenv(k, v)

    monkeypatch.setattr(telethon.sessions, "StringSession", DummyStringSession)
    monkeypatch.setattr(
        telethon, "TelegramClient", lambda *a, **kw: DummyTelegramClient()
    )

    server_arianna = importlib.import_module("server_arianna")
    server_arianna = importlib.reload(server_arianna)

    monkeypatch.setattr(server_arianna.engine, "setup_assistant", AsyncMock())
    monkeypatch.setattr(server_arianna.engine, "aclose", AsyncMock())

    close_mock = AsyncMock()
    monkeypatch.setattr(
        server_arianna, "openai_client", SimpleNamespace(close=close_mock)
    )

    await server_arianna.main()

    close_mock.assert_awaited_once()
