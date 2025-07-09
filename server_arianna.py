import os
import re
import asyncio
import random

from aiogram import Bot, Dispatcher, types
from aiogram.utils.chat_action import ChatActionSender
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from utils.arianna_engine import AriannaEngine
from utils.split_message import split_message
from utils.genesis_tool import genesis_tool_schema, handle_genesis_call  # функция как инструмент

BOT_TOKEN   = os.getenv("TELEGRAM_TOKEN")

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

    # Просто затычка спама/пингов — оставляем старую логику
    is_group = getattr(m.chat, "type", "") in ("group", "supergroup")
    mentioned = not is_group or bool(re.search(r"\barianna\b", text, re.I))
    if not mentioned:
        return

    async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
        # Генерируем ответ через Assistants API
        resp = await engine.ask(user_id, text, is_group=is_group)
        # Разбиваем длинные ответы
        for chunk in split_message(resp):
            await m.answer(chunk)

async def main():
    # создаём ассистента и любые ресурс-ассеты (vector store, функции)
    await engine.setup_assistant()

    app = web.Application()
    path = f"/webhook/{BOT_TOKEN}"
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=path)
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

