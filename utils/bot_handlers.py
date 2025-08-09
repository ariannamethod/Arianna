import os
import re
import asyncio
from typing import Callable, Awaitable, Optional

from utils.split_message import split_message
from utils.text_helpers import extract_text_from_url

DEEPSEEK_CMD = "/ds"
SEARCH_CMD = "/search"
INDEX_CMD = "/index"
DEBUG_SKIP_CMD = "/debugskip"

URL_REGEX = re.compile(r"https://\S+")
URL_FETCH_TIMEOUT = int(os.getenv("URL_FETCH_TIMEOUT", 10))

SHORT_MSG_SKIP_PROB = float(
    os.getenv("SHORT_MSG_SKIP_PROB", os.getenv("SKIP_SHORT_PROB", 0.5))
)
# backward compatibility
SKIP_SHORT_PROB = SHORT_MSG_SKIP_PROB

SendFunc = Callable[[str], Awaitable[None]]


async def append_link_snippets(text: str) -> str:
    """Append snippet from any https:// link in the text."""
    urls = URL_REGEX.findall(text)
    if not urls:
        return text
    tasks = [asyncio.wait_for(extract_text_from_url(url), URL_FETCH_TIMEOUT) for url in urls]
    snippets = await asyncio.gather(*tasks, return_exceptions=True)
    parts = [text]
    for url, snippet in zip(urls, snippets):
        snippet_text = (
            f"[Error loading page: {snippet}]" if isinstance(snippet, Exception) else snippet
        )
        parts.append(f"\n[Snippet from {url}]\n{snippet_text[:500]}")
    return "\n".join(parts)


def parse_command(text: str) -> tuple[Optional[str], str]:
    """Return (command, argument) if text starts with a known command."""
    stripped = text.strip()
    lowered = stripped.lower()
    for cmd in (SEARCH_CMD, INDEX_CMD, DEEPSEEK_CMD, DEBUG_SKIP_CMD):
        if lowered.startswith(cmd):
            arg = stripped[len(cmd):].lstrip()
            return cmd, arg
    return None, stripped


async def dispatch_response(send: SendFunc, text: str) -> None:
    """Split long responses and dispatch each part via send."""
    for chunk in split_message(text):
        await send(chunk)
