import importlib
import asyncio
from types import SimpleNamespace


def test_voice_and_text_share_thread(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("TELEGRAM_PHONE", "+1000000")
    monkeypatch.setenv("TELEGRAM_SESSION_STRING", "session")

    # Stub out Telethon client and session to avoid initialization errors
    import telethon
    import telethon.sessions

    class DummyClient:
        def on(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        async def send_file(self, *args, **kwargs):
            return None

        async def send_message(self, *args, **kwargs):
            return None

        async def send_chat_action(self, *args, **kwargs):
            return None

    class DummySession:
        def __init__(self, s):
            self.s = s

    monkeypatch.setattr(telethon, "TelegramClient", lambda *a, **k: DummyClient())
    monkeypatch.setattr(telethon.sessions, "StringSession", DummySession)

    sa = importlib.import_module("server_arianna")

    async def fake_transcribe(path):
        return "hello there how are you?"

    async def fake_append(text):
        return text

    async def fake_send(*args, **kwargs):
        return None

    keys = []

    async def fake_ask(thread_key, prompt, is_group=False):
        keys.append(thread_key)
        return "ok"

    monkeypatch.setattr(sa, "transcribe_voice", fake_transcribe)
    monkeypatch.setattr(sa, "append_link_snippets", fake_append)
    monkeypatch.setattr(sa, "send_delayed_response", fake_send)
    monkeypatch.setattr(sa.engine, "ask", fake_ask)

    class VoiceEvent:
        is_group = True
        sender_id = 1
        chat_id = 123
        async def download_media(self, path):
            return None
        async def reply(self, text):
            return None

    class TextEvent:
        def __init__(self):
            self.is_group = True
            self.sender_id = 2
            self.chat_id = 123
            self.raw_text = "Arianna how are you today?"
            self.out = False
            self.is_reply = False
            self.message = SimpleNamespace(entities=None)
        async def reply(self, text):
            return None

    asyncio.run(sa.voice_messages(VoiceEvent()))
    asyncio.run(sa.all_messages(TextEvent()))

    assert keys == ["123", "123"]
