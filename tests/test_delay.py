import importlib
import sys


def _set_base_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "abc")
    monkeypatch.setenv("TELEGRAM_PHONE", "123")
    monkeypatch.setenv("TELEGRAM_SESSION_STRING", "dummy")


def _import_server(monkeypatch, args=None):
    if args is None:
        args = []
    monkeypatch.setattr(sys, "argv", ["server_arianna.py", *args])
    import telethon
    import telethon.sessions

    class DummyStringSession:  # avoids base64 parsing of real StringSession
        def __init__(self, *args, **kwargs):
            pass

    class DummyTelegramClient:  # minimal stand-in for TelegramClient
        def __init__(self, *args, **kwargs):
            pass

        def on(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

    monkeypatch.setattr(telethon.sessions, "StringSession", DummyStringSession)
    monkeypatch.setattr(telethon, "TelegramClient", DummyTelegramClient)
    sys.modules.pop("server_arianna", None)
    return importlib.import_module("server_arianna")


def test_no_delay_env(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("DISABLE_DELAY", "1")
    srv = _import_server(monkeypatch)
    assert srv._delay(True) == 0
    assert srv._delay(False) == 0


def test_no_delay_arg(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.delenv("DISABLE_DELAY", raising=False)
    srv = _import_server(monkeypatch, ["--no-delay"])
    assert srv._delay(True) == 0
    assert srv._delay(False) == 0
