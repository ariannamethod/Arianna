import os
import re
import asyncio
import logging
import random

import httpx
from fastapi import FastAPI, Request

from utils.arianna_engine import AriannaEngine
from utils.split_message import split_message
from utils.vector_store import semantic_search, vectorize_all_files
from utils.text_helpers import extract_text_from_url
from utils.deepseek_search import DEEPSEEK_ENABLED

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN environment variable is not set")
    raise SystemExit("Missing TELEGRAM_BOT_TOKEN")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY environment variable is not set")
    raise SystemExit("Missing OPENAI_API_KEY")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY environment variable is not set")
    raise SystemExit("Missing DEEPSEEK_API_KEY")

app = FastAPI()
engine = AriannaEngine()

DEEPSEEK_CMD = "/ds"
SEARCH_CMD = "/search"
INDEX_CMD = "/index"

SKIP_SHORT_PROB = float(os.getenv("SKIP_SHORT_PROB", 0.5))
URL_REGEX = re.compile(r"https://\S+")
URL_FETCH_TIMEOUT = int(os.getenv("URL_FETCH_TIMEOUT", 10))

BOT_USERNAME = ""
BOT_ID = 0

async def append_link_snippets(text: str) -> str:
    urls = URL_REGEX.findall(text)
    if not urls:
        return text
    tasks = [asyncio.wait_for(extract_text_from_url(url), URL_FETCH_TIMEOUT) for url in urls]
    snippets = await asyncio.gather(*tasks, return_exceptions=True)
    parts = [text]
    for url, snippet in zip(urls, snippets):
        if isinstance(snippet, Exception):
            snippet_text = f"[Error loading page: {snippet}]"
        else:
            snippet_text = snippet
        parts.append(f"\n[Snippet from {url}]\n{snippet_text[:500]}")
    return "\n".join(parts)

async def send_message(chat_id: int, text: str) -> None:
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text},
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
    await engine.setup_assistant()
    logger.info("🚀 Webhook server started")

@app.get("/")
async def root() -> dict:
    return {"status": "ok"}

@app.post("/webhook")
async def telegram_webhook(request: Request) -> dict:
    update = await request.json()
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}

    chat = message["chat"]
    chat_id = chat["id"]
    is_group = chat.get("type") in {"group", "supergroup"}

    text = message.get("text", "")
    if not text:
        return {"ok": True}

    if text.strip().lower().startswith(SEARCH_CMD):
        query = text.strip()[len(SEARCH_CMD):].lstrip()
        if query:
            chunks = await semantic_search(query, engine.openai_key)
            if not chunks:
                await send_message(chat_id, "No relevant documents found.")
            else:
                for ch in chunks:
                    for part in split_message(ch):
                        await send_message(chat_id, part)
        return {"ok": True}

    if text.strip().lower().startswith(INDEX_CMD):
        await send_message(chat_id, "Indexing documents, please wait...")
        async def sender(msg: str) -> None:
            await send_message(chat_id, msg)
        await vectorize_all_files(engine.openai_key, force=True, on_message=sender)
        await send_message(chat_id, "Indexing complete.")
        return {"ok": True}

    if text.strip().lower().startswith(DEEPSEEK_CMD):
        if not DEEPSEEK_ENABLED:
            await send_message(chat_id, "DeepSeek integration is not configured")
            return {"ok": True}
        query = text.strip()[len(DEEPSEEK_CMD):].lstrip()
        if query:
            resp = await engine.deepseek_reply(query)
            for part in split_message(resp):
                await send_message(chat_id, part)
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

    for chunk in split_message(resp):
        await send_message(chat_id, chunk)

    return {"ok": True}
