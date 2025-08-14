import os
import re
import asyncio
from typing import Callable, Awaitable, Optional

from utils.split_message import split_message
from utils.text_helpers import extract_text_from_url

DEEPSEEK_CMD = "/ds"
SEARCH_CMD = "/search"
INDEX_CMD = "/index"
VOICE_ON_CMD = "/voiceon"
VOICE_OFF_CMD = "/voiceoff"
HELP_CMD = "/help"
MENU_CMD = "/menu"

COMMAND_ALIASES = {
    SEARCH_CMD: ("/search", "/s"),
    INDEX_CMD: ("/index", "/i"),
    DEEPSEEK_CMD: ("/ds",),
    VOICE_ON_CMD: ("/voiceon", "/vo"),
    VOICE_OFF_CMD: ("/voiceoff", "/vf"),
    HELP_CMD: ("/help", "/h"),
    MENU_CMD: ("/menu", "/m"),
}

SHORT_COMMANDS = {key: aliases[-1] for key, aliases in COMMAND_ALIASES.items()}

URL_REGEX = re.compile(r"https://\S+")
URL_FETCH_TIMEOUT = int(os.getenv("URL_FETCH_TIMEOUT", 10))

# Chance to ignore very short or non-question messages.
# Set to 0 to disable random skipping.
SKIP_SHORT_PROB = max(0.0, min(1.0, float(os.getenv("SKIP_SHORT_PROB", 0.5))))

SendFunc = Callable[[str], Awaitable[None]]


async def append_link_snippets(text: str) -> str:
    """Append snippet from any https:// link in the text."""
    urls = URL_REGEX.findall(text)
    if not urls:
        return text
    tasks = [
        asyncio.wait_for(extract_text_from_url(url), URL_FETCH_TIMEOUT)
        for url in urls
    ]
    snippets = await asyncio.gather(*tasks, return_exceptions=True)
    parts = [text]
    for url, snippet in zip(urls, snippets):
        snippet_text = (
            f"[Error loading page: {snippet}]"
            if isinstance(snippet, Exception)
            else snippet
        )
        parts.append(f"\n[Snippet from {url}]\n{snippet_text[:500]}")
    return "\n".join(parts)


def parse_command(
    text: str, bot_username: Optional[str] = None
) -> tuple[Optional[str], str]:
    """Return (command, argument) if text starts with a known command.

    If ``bot_username`` is provided, an ``@<bot_username>`` suffix in the
    command is removed before matching.
    """
    stripped = text.strip()
    if not stripped:
        return None, ""

    first, *rest = stripped.split(maxsplit=1)
    lowered_first = first.lower()
    if bot_username:
        suffix = f"@{bot_username.lower()}"
        if lowered_first.endswith(suffix):
            first = first[:-len(suffix)]
            lowered_first = lowered_first[:-len(suffix)]

    stripped = first + (" " + rest[0] if rest else "")
    lowered = stripped.lower()

    for canonical, aliases in COMMAND_ALIASES.items():
        for cmd in aliases:
            if lowered.startswith(cmd):
                arg = stripped[len(cmd):].lstrip()
                return canonical, arg
    return None, stripped


async def dispatch_response(send: SendFunc, text: str) -> None:
    """Split long responses and dispatch each part via send."""
    for chunk in split_message(text):
        await send(chunk)
