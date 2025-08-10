import os
import re
import logging
import random

import httpx
from fastapi import FastAPI, Request

from utils.arianna_engine import AriannaEngine
from utils.vector_store import semantic_search, vectorize_all_files
from utils.deepseek_search import DEEPSEEK_ENABLED
from utils.bot_handlers import (
    append_link_snippets,
    parse_command,
    dispatch_response,
    DEEPSEEK_CMD,
    SEARCH_CMD,
    INDEX_CMD,
    SKIP_SHORT_PROB,
)

HELP_CMD = "/help"
HELP_TEXT = (
    f"{SEARCH_CMD} <query> - semantic search documents\n"
    f"{INDEX_CMD} - index documents\n"
    f"{DEEPSEEK_CMD} <query> - ask DeepSeek\n"
    f"{HELP_CMD} - show this help message"
)

def default_keyboard() -> dict:
    """Inline keyboard with common actions."""
    return {
        "inline_keyboard": [
            [
                {"text": "Voice On", "callback_data": "voice_on"},
                {"text": "Voice Off", "callback_data": "voice_off"},
            ],
            [{"text": "Search docs", "callback_data": "search_docs"}],
        ]
    }


VOICE_ENABLED = {}

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN/TELEGRAM_TOKEN not set")
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_TOKEN")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY environment variable is not set")
    raise SystemExit("Missing OPENAI_API_KEY")

app = FastAPI()
engine = AriannaEngine()

BOT_USERNAME = ""
BOT_ID = 0

DISABLE_FORMATTING = os.getenv("TELEGRAM_DISABLE_FORMATTING")
PARSE_MODE = None if DISABLE_FORMATTING else os.getenv("TELEGRAM_PARSE_MODE", "MarkdownV2")

async def send_message(chat_id: int, text: str) -> None:
    payload = {"chat_id": chat_id, "text": text, "reply_markup": default_keyboard()}
    if PARSE_MODE:
        payload["parse_mode"] = PARSE_MODE
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=payload,
            timeout=30,
        )

@app.on_event("startup")
async def startup() -> None:
    global BOT_USERNAME, BOT_ID
    async with httpx.AsyncClient() as client:
        me = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe")
        data = me.json()["result"]
        BOT_USERNAME = (data.get("username") or "").lower()
        BOT_ID = data.get("id", 0)
        webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
        if webhook_url:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                json={"url": webhook_url},
            )
    try:
        await engine.setup_assistant()
    except RuntimeError:
        logger.exception("Assistant initialization failed")
        await engine.aclose()
        raise SystemExit(1)
    logger.info("🚀 Webhook server started")

@app.on_event("shutdown")
async def shutdown() -> None:
    await engine.aclose()

@app.get("/")
async def root() -> dict:
    return {"status": "ok"}

@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    update = await request.json()

    callback = update.get("callback_query")
    if callback:
        data = callback.get("data")
        chat_id = callback["message"]["chat"]["id"]
        if data == "voice_on":
            VOICE_ENABLED[chat_id] = True
            await send_message(chat_id, "Voice responses enabled")
        elif data == "voice_off":
            VOICE_ENABLED[chat_id] = False
            await send_message(chat_id, "Voice responses disabled")
        elif data == "search_docs":
            await send_message(chat_id, "Use /search <query> to search documents")
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                json={"callback_query_id": callback.get("id")},
            )
        return {"ok": True}

    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}

    chat = message["chat"]
    chat_id = chat["id"]
    is_group = chat.get("type") in {"group", "supergroup"}

    text = message.get("text", "")
    if not text:
        return {"ok": True}

    cmd, arg = parse_command(text)
    if cmd == SEARCH_CMD:
        if arg:
            chunks = await semantic_search(arg, engine.openai_key)
            if not chunks:
                await send_message(chat_id, "No relevant documents found.")
            else:
                async def send(part: str) -> None:
                    await send_message(chat_id, part)
                for ch in chunks:
                    await dispatch_response(send, ch)
        return {"ok": True}

    if cmd == INDEX_CMD:
        await send_message(chat_id, "Indexing documents, please wait...")
        async def sender(msg: str) -> None:
            await send_message(chat_id, msg)
        await vectorize_all_files(engine.openai_key, force=True, on_message=sender)
        await send_message(chat_id, "Indexing complete.")
        return {"ok": True}

    if cmd == DEEPSEEK_CMD:
        if not DEEPSEEK_ENABLED:
            await send_message(chat_id, "DeepSeek integration is not configured")
            return {"ok": True}
        if arg:
            resp = await engine.deepseek_reply(arg)
            async def send(part: str) -> None:
                await send_message(chat_id, part)
            await dispatch_response(send, resp)
        return {"ok": True}

    if text.strip().lower() == HELP_CMD:
        await send_message(chat_id, HELP_TEXT)
        return {"ok": True}

    mentioned = False
    if not is_group:
        mentioned = True
    else:
        if re.search(r"\b(arianna|арианна)\b", text, re.I):
            mentioned = True
        elif BOT_USERNAME and f"@{BOT_USERNAME}" in text.lower():
            mentioned = True
        if message.get("entities"):
            for ent in message["entities"]:
                if ent.get("type") == "mention":
                    ent_text = text[ent["offset"]: ent["offset"] + ent["length"]]
                    if ent_text[1:].lower() == BOT_USERNAME:
                        mentioned = True
                        break
        if message.get("reply_to_message"):
            if message["reply_to_message"].get("from", {}).get("id") == BOT_ID:
                mentioned = True

    if not mentioned:
        return {"ok": True}

    if len(text.split()) < 4 or '?' not in text:
        if random.random() < SKIP_SHORT_PROB:
            return {"ok": True}

    thread_key = str(chat_id) if is_group else str(message["from"]["id"])
    prompt = await append_link_snippets(text)
    try:
        resp = await engine.ask(thread_key, prompt, is_group=is_group)
    except httpx.TimeoutException:
        await send_message(chat_id, "Request timed out. Please try again later.")
        return {"ok": True}

    async def send(part: str) -> None:
        await send_message(chat_id, part)
    await dispatch_response(send, resp)

    return {"ok": True}
