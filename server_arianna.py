import os
import re
import asyncio
import random
import logging
import tempfile

import openai
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

from aiogram import Bot, Dispatcher, types
from aiogram.utils.chat_action import ChatActionSender
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from utils.arianna_engine import AriannaEngine
from utils.split_message import split_message
from utils.genesis_tool import genesis_tool_schema, handle_genesis_call  # функция как инструмент
from utils.vector_store import semantic_search, vectorize_all_files

BOT_TOKEN     = os.getenv("TELEGRAM_TOKEN")
BOT_USERNAME  = ""  # will be set at startup
BOT_ID        = 0   # will be set at startup

bot    = Bot(token=BOT_TOKEN)
dp     = Dispatcher(bot=bot)
engine = AriannaEngine()
openai_client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DEEPSEEK_CMD = "/ds"
SEARCH_CMD = "/search"
INDEX_CMD = "/index"
VOICE_ON_CMD = "/voiceon"
VOICE_OFF_CMD = "/voiceoff"
VOICE_ENABLED = {}


async def transcribe_voice(file_path: str) -> str:
    """Transcribe an audio file using OpenAI Whisper."""
    with open(file_path, "rb") as f:
        resp = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
        )
    return resp.text


async def synthesize_voice(text: str) -> str:
    """Synthesize speech from text using OpenAI TTS and return OGG path."""
    mp3_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    ogg_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    mp3_fd.close()
    ogg_fd.close()
    resp = await openai_client.audio.speech.create(
        model="tts-1",
        voice="alloy",
        input=text,
    )
    resp.stream_to_file(mp3_fd.name)
    AudioSegment.from_file(mp3_fd.name).export(ogg_fd.name, format="ogg", codec="libopus")
    os.remove(mp3_fd.name)
    return ogg_fd.name

# --- health check routes ---
async def healthz(request):
    return web.Response(text="ok")


async def status(request):
    return web.Response(text="running")


@dp.message(lambda m: m.voice)
async def voice_messages(m: types.Message):
    is_group = getattr(m.chat, "type", "") in ("group", "supergroup")
    user_id = str(m.from_user.id)
    thread_key = f"{m.chat.id}:{m.from_user.id}" if is_group else user_id
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await bot.download(m.voice.file_id, tmp.name)
    text = await transcribe_voice(tmp.name)
    os.remove(tmp.name)
    async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
        resp = await engine.ask(thread_key, text, is_group=is_group)
        if VOICE_ENABLED.get(m.chat.id):
            voice_path = await synthesize_voice(resp)
            await m.answer_voice(types.FSInputFile(voice_path), caption=resp[:1024])
            os.remove(voice_path)
        else:
            for chunk in split_message(resp):
                await m.answer(chunk)

@dp.message(lambda m: True)
async def all_messages(m: types.Message):
    user_id = str(m.from_user.id)
    text    = m.text or ""

    # Semantic search
    if text.strip().lower().startswith(SEARCH_CMD):
        query = text.strip()[len(SEARCH_CMD):].lstrip()
        if not query:
            return
        async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
            chunks = await semantic_search(query, engine.openai_key)
            if not chunks:
                await m.answer("No relevant documents found.")
            else:
                for ch in chunks:
                    for part in split_message(ch):
                        await m.answer(part)
        return

    if text.strip().lower().startswith(INDEX_CMD):
        async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
            await m.answer("Indexing documents, please wait...")

            async def sender(msg):
                await m.answer(msg)

            await vectorize_all_files(engine.openai_key, force=True, on_message=sender)
            await m.answer("Indexing complete.")
        return

    if text.strip().lower() == VOICE_ON_CMD:
        VOICE_ENABLED[m.chat.id] = True
        await m.answer("Voice responses enabled")
        return
    if text.strip().lower() == VOICE_OFF_CMD:
        VOICE_ENABLED[m.chat.id] = False
        await m.answer("Voice responses disabled")
        return

    # Direct DeepSeek call
    if text.strip().lower().startswith(DEEPSEEK_CMD):
        query = text.strip()[len(DEEPSEEK_CMD):].lstrip()
        if not query:
            return
        async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
            resp = await engine.deepseek_reply(query)
            for chunk in split_message(resp):
                await m.answer(chunk)
        return

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

    thread_key = user_id
    if is_group:
        thread_key = f"{m.chat.id}:{m.from_user.id}"

    async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
        # Генерируем ответ через Assistants API
        resp = await engine.ask(thread_key, text, is_group=is_group)
        if VOICE_ENABLED.get(m.chat.id):
            voice_path = await synthesize_voice(resp)
            await m.answer_voice(types.FSInputFile(voice_path), caption=resp[:1024])
            os.remove(voice_path)
        else:
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

