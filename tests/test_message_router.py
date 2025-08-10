import pytest

from utils.message_router import route_message


class DummyEngine:
    def __init__(self):
        self.calls = []
        self.openai_key = "test-key"

    async def ask(self, thread_key: str, prompt: str, is_group: bool = False) -> str:
        self.calls.append((thread_key, prompt, is_group))
        return "engine response"

    async def deepseek_reply(self, query: str) -> str:
        return f"deepseek: {query}"


@pytest.mark.asyncio
async def test_search_command(monkeypatch):
    sent = []

    async def send(msg: str) -> None:
        sent.append(msg)

    async def answer(resp: str, thread_key: str, is_group: bool) -> None:
        sent.append(resp)

    engine = DummyEngine()

    async def fake_search(query, key):
        return ["result1", "result2"]

    monkeypatch.setattr("utils.message_router.semantic_search", fake_search)

    await route_message(
        "/search test",
        chat_id=1,
        sender_id=2,
        is_group=False,
        bot_username="arianna",
        send_reply=send,
        respond=answer,
        engine=engine,
        entities=None,
    )

    assert sent == ["result1", "result2"]
    assert engine.calls == []


@pytest.mark.asyncio
async def test_group_message_without_mention(monkeypatch):
    engine = DummyEngine()
    called = False

    async def send(msg: str) -> None:
        nonlocal called
        called = True

    async def answer(resp: str, thread_key: str, is_group: bool) -> None:
        nonlocal called
        called = True

    await route_message(
        "hello there?",
        chat_id=1,
        sender_id=2,
        is_group=True,
        bot_username="arianna",
        send_reply=send,
        respond=answer,
        engine=engine,
        entities=None,
    )

    assert called is False
    assert engine.calls == []


@pytest.mark.asyncio
async def test_mention_creates_thread_key(monkeypatch):
    engine = DummyEngine()
    responses = []

    async def send(msg: str) -> None:
        pass

    async def answer(resp: str, thread_key: str, is_group: bool) -> None:
        responses.append((resp, thread_key, is_group))

    await route_message(
        "arianna how are you?",
        chat_id=10,
        sender_id=5,
        is_group=True,
        bot_username="arianna",
        send_reply=send,
        respond=answer,
        engine=engine,
        entities=None,
    )

    assert responses == [("engine response", "10", True)]


@pytest.mark.asyncio
async def test_private_thread_key(monkeypatch):
    engine = DummyEngine()
    responses = []

    async def send(msg: str) -> None:
        pass

    async def answer(resp: str, thread_key: str, is_group: bool) -> None:
        responses.append(thread_key)

    await route_message(
        "hello?",
        chat_id=10,
        sender_id=5,
        is_group=False,
        bot_username="arianna",
        send_reply=send,
        respond=answer,
        engine=engine,
        entities=None,
    )

    assert responses == ["5"]
