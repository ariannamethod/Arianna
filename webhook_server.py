import os
import logging

import httpx
from fastapi import FastAPI, Request

from utils.arianna_engine import AriannaEngine
from utils.bot_handlers import dispatch_response
from utils.message_router import route_message

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
    payload = {"chat_id": chat_id, "text": text}
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
    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"ok": True}

    chat = message["chat"]
    chat_id = chat["id"]
    is_group = chat.get("type") in {"group", "supergroup"}

    text = message.get("text", "")
    if not text:
        return {"ok": True}

    is_reply = False
    if message.get("reply_to_message"):
        if message["reply_to_message"].get("from", {}).get("id") == BOT_ID:
            is_reply = True

    async def send_msg(part: str) -> None:
        await send_message(chat_id, part)

    async def answer(resp: str, thread_key: str, is_group_flag: bool) -> None:
        async def send(part: str) -> None:
            await send_message(chat_id, part)
        await dispatch_response(send, resp)

    await route_message(
        text,
        chat_id,
        message["from"]["id"],
        is_group=is_group,
        bot_username=BOT_USERNAME,
        send_reply=send_msg,
        respond=answer,
        engine=engine,
        entities=message.get("entities"),
        is_reply=is_reply,
    )

    return {"ok": True}
