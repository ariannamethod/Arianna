import sys
import asyncio
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from utils import bot_handlers as bh  # noqa: E402


def test_append_link_snippets(monkeypatch):
    async def fake_extract(url: str) -> str:
        assert url == "https://example.com"
        return "Example content"

    async def run_test():
        monkeypatch.setattr(bh, "extract_text_from_url", fake_extract)
        text = "Check https://example.com"
        result = await bh.append_link_snippets(text)
        assert "Example content" in result
        assert text in result

    asyncio.run(run_test())


def test_parse_command():
    cmd, arg = bh.parse_command("/search kittens")
    assert cmd == bh.SEARCH_CMD
    assert arg == "kittens"

    cmd, arg = bh.parse_command("/DS data")
    assert cmd == bh.DEEPSEEK_CMD
    assert arg == "data"

    cmd, arg = bh.parse_command("no command here")
    assert cmd is None
    assert arg == "no command here"


def test_parse_command_with_bot_username():
    cmd, arg = bh.parse_command("/voiceon@mybot", bot_username="mybot")
    assert cmd == bh.VOICE_ON_CMD
    assert arg == ""


def test_dispatch_response_splits():
    parts = []

    async def run_test():
        async def sender(part: str) -> None:
            parts.append(part)

        text = "a" * 5000
        await bh.dispatch_response(sender, text)

    asyncio.run(run_test())
    assert len(parts) == 2
    assert parts[0] == "a" * 4000
    assert parts[1] == "a" * 1000
