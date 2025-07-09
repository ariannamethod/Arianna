import os
import re
import asyncio
import random
import logging

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

from aiogram import Bot, Dispatcher, types
from aiogram.utils.chat_action import ChatActionSender
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from utils.arianna_engine import AriannaEngine
from utils.split_message import split_message
from utils.genesis_tool import genesis_tool_schema, handle_genesis_call  # функция как инструмент

BOT_TOKEN     = os.getenv("TELEGRAM_TOKEN")
BOT_USERNAME  = ""  # will be set at startup
BOT_ID        = 0   # will be set at startup

bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(bot=bot)
engine = AriannaEngine()

# --- health check routes ---
async def healthz(request):
    return web.Response(text="ok")


async def status(request):
    return web.Response(text="running")

@dp.message(lambda m: True)
async def all_messages(m: types.Message):
    user_id = str(m.from_user.id)
    text    = m.text or ""

    # Простая проверка упоминания бота в группах
    is_group = getattr(m.chat, "type", "") in ("group", "supergroup")
    is_reply = (
        m.reply_to_message
        and m.reply_to_message.from_user
        and m.reply_to_message.from_user.id == BOT_ID
    )

    mentioned = False
    if not is_group:
        mentioned = True
    else:
        if re.search(r"\b(arianna|арианна)\b", text, re.I):
            mentioned = True
        elif BOT_USERNAME and f"@{BOT_USERNAME}".lower() in text.lower():
            mentioned = True
        elif m.entities:
            for ent in m.entities:
                if ent.type == "mention":
                    ent_text = text[ent.offset: ent.offset + ent.length]
                    if ent_text[1:].lower() == BOT_USERNAME:
                        mentioned = True
                        break

    if is_reply:
        mentioned = True

    if not (mentioned or is_reply):
        return

    async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
        # Генерируем ответ через Assistants API
        resp = await engine.ask(user_id, text, is_group=is_group)
        # Разбиваем длинные ответы
        for chunk in split_message(resp):
            await m.answer(chunk)

async def main():
    global BOT_USERNAME, BOT_ID
    # получаем имя бота и создаём ассистента и любые ресурс‑ассеты
    me = await bot.get_me()
    BOT_USERNAME = (me.username or "").lower()
    BOT_ID = me.id

    init_failed = False
    try:
        await engine.setup_assistant()
    except Exception:
        logger.exception("Assistant initialization failed")
        init_failed = True

    app = web.Application()
    path = f"/webhook/{BOT_TOKEN}"
    if init_failed:
        async def failed(request):
            return web.Response(status=500, text="Initialization failed")
        app.router.add_route("*", path, failed)
        app.router.add_route("*", "/webhook", failed)
    else:
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        handler.register(app, path=path)
        handler.register(app, path="/webhook")
        setup_application(app, dp)

    # Register health check routes
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/status", status)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🚀 Arianna webhook started on port {port}")
    await asyncio.Event().wait()

if __name__ == "__main__":    asyncio.run(main())

