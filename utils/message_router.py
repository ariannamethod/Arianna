import random
import re
from typing import Awaitable, Callable, Optional, Sequence

import httpx

from utils.bot_handlers import (
    append_link_snippets,
    parse_command,
    dispatch_response,
    SEARCH_CMD,
    INDEX_CMD,
    DEEPSEEK_CMD,
    SKIP_SHORT_PROB,
)
from utils.deepseek_search import DEEPSEEK_ENABLED
from utils.vector_store import semantic_search, vectorize_all_files
from utils.arianna_engine import AriannaEngine

SendFunc = Callable[[str], Awaitable[None]]
AnswerFunc = Callable[[str, str, bool], Awaitable[None]]

HELP_CMD = "/help"
HELP_TEXT = (
    f"{SEARCH_CMD} <query> - semantic search documents\n"
    f"{INDEX_CMD} - index documents\n"
    f"{DEEPSEEK_CMD} <query> - ask DeepSeek\n"
    f"{HELP_CMD} - show this help message"
)


def _is_mentioned(
    text: str,
    *,
    is_group: bool,
    bot_username: str,
    entities: Optional[Sequence] = None,
    is_reply: bool = False,
) -> bool:
    """Determine if the bot was mentioned in the message."""
    if not is_group:
        return True
    lowered = text.lower()
    if re.search(r"\b(arianna|арианна)\b", lowered, re.I):
        return True
    if bot_username and f"@{bot_username}".lower() in lowered:
        return True
    if entities:
        for ent in entities:
            if hasattr(ent, "offset") and hasattr(ent, "length"):
                ent_text = text[ent.offset : ent.offset + ent.length]
                if ent_text[1:].lower() == bot_username:
                    return True
            elif isinstance(ent, dict) and ent.get("type") == "mention":
                ent_text = text[ent["offset"] : ent["offset"] + ent["length"]]
                if ent_text[1:].lower() == bot_username:
                    return True
    if is_reply:
        return True
    return False


async def route_message(
    text: str,
    chat_id: int,
    sender_id: int,
    *,
    is_group: bool,
    bot_username: str,
    send_reply: SendFunc,
    respond: AnswerFunc,
    engine: AriannaEngine,
    entities: Optional[Sequence] = None,
    is_reply: bool = False,
) -> None:
    """Handle an incoming text message with shared routing logic."""
    cmd, arg = parse_command(text)

    if cmd == SEARCH_CMD:
        if arg:
            chunks = await semantic_search(arg, engine.openai_key)
            if not chunks:
                await send_reply("No relevant documents found.")
            else:
                for ch in chunks:
                    await dispatch_response(send_reply, ch)
        return

    if cmd == INDEX_CMD:
        await send_reply("Indexing documents, please wait...")
        async def sender(msg: str) -> None:
            await send_reply(msg)
        await vectorize_all_files(engine.openai_key, force=True, on_message=sender)
        await send_reply("Indexing complete.")
        return

    if cmd == DEEPSEEK_CMD:
        if not DEEPSEEK_ENABLED:
            await send_reply("DeepSeek integration is not configured")
            return
        if arg:
            resp = await engine.deepseek_reply(arg)
            await dispatch_response(send_reply, resp)
        return

    if text.strip().lower() == HELP_CMD:
        await send_reply(HELP_TEXT)
        return

    if not _is_mentioned(
        text,
        is_group=is_group,
        bot_username=bot_username,
        entities=entities,
        is_reply=is_reply,
    ):
        return

    if len(text.split()) < 4 or "?" not in text:
        if random.random() < SKIP_SHORT_PROB:
            return

    thread_key = str(chat_id) if is_group else str(sender_id)
    prompt = await append_link_snippets(text)

    try:
        resp = await engine.ask(thread_key, prompt, is_group=is_group)
    except httpx.TimeoutException:
        await send_reply("Request timed out. Please try again later.")
        return

    await respond(resp, thread_key, is_group)
