import os
from typing import Callable, Awaitable, Optional

from utils.split_message import split_message

DEEPSEEK_CMD = "/ds"
SEARCH_CMD = "/search"
INDEX_CMD = "/index"

SKIP_SHORT_PROB = float(os.getenv("SKIP_SHORT_PROB", 0.5))

SendFunc = Callable[[str], Awaitable[None]]

def parse_command(text: str) -> tuple[Optional[str], str]:
    """Return (command, argument) if text starts with a known command."""
    stripped = text.strip()
    lowered = stripped.lower()
    for cmd in (SEARCH_CMD, INDEX_CMD, DEEPSEEK_CMD):
        if lowered.startswith(cmd):
            arg = stripped[len(cmd):].lstrip()
            return cmd, arg
    return None, stripped


async def dispatch_response(send: SendFunc, text: str) -> None:
    """Split long responses and dispatch each part via send."""
    for chunk in split_message(text):
        await send(chunk)
