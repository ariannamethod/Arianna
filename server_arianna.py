import os
import re
import asyncio
import random
from aiogram import Bot, Dispatcher, types
from aiogram.utils.chat_action import ChatActionSender
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from utils.arianna_engine import AriannaEngine
from utils.genesis_tool import genesis_tool_schema, handle_genesis_call
from pydub import AudioSegment
from openai import AsyncOpenAI

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
IS_GROUP = os.getenv("IS_GROUP", "False").lower() == "true"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot=bot)
engine = AriannaEngine()
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

@dp.message(lambda m: m.voice)
async def handle_voice(m: types.Message):
    chat_id = m.chat.id
    try:
        file = await m.bot.download(m.voice.file_id)
        fname = "voice.ogg"
        with open(fname, "wb") as f:
            f.write(file.read())
        audio = AudioSegment.from_file(fname)
        if len(audio) < 500:
            await m.answer("Audio too short for recognition.")
            return
        if audio.max < 500:
            await m.answer("Audio too quiet for recognition.")
            return
        with open(fname, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        text = transcript.text.strip()
        if not text:
            await m.answer("Could not understand the audio.")
            return
        resp = await engine.ask(str(m.from_user.id), text, is_group=getattr(m.chat, "type", "") in ("group", "supergroup"))
        for chunk in engine.split_message(resp):
            await m.answer(chunk)
    except Exception as e:
        await m.answer(f"Voice/audio error: {str(e)}")

@dp.message(lambda m: m.document)
async def handle_document(m: types.Message):
    chat_id = m.chat.id
    try:
        file = await m.bot.get_file(m.document.file_id)
        fname = f"uploaded_{m.document.file_name}"
        await m.bot.download_file(file.file_path, fname)
        from utils.file_handling import extract_text_from_file_async
        extracted_text = await extract_text_from_file_async(fname)
        if not extracted_text or extracted_text.strip().startswith("[Error") or extracted_text.strip().startswith("[Unsupported"):
            await m.answer(f"Could not read this file: {m.document.file_name}\n{extracted_text}")
            return
        prompt = f"Analyze or summarize this document:\n\n{extracted_text[:4000]}"
        resp = await engine.ask(str(m.from_user.id), prompt, is_group=getattr(m.chat, "type", "") in ("group", "supergroup"))
        for chunk in engine.split_message(resp):
            await m.answer(chunk)
    except Exception as e:
        await m.answer(f"Document error: {str(e)}")

@dp.message(lambda m: True)
async def all_messages(m: types.Message):
    user_id = str(m.from_user.id)
    text = m.text or ""
    is_group = getattr(m.chat, "type", "") in ("group", "supergroup")
    mentioned = not is_group or bool(re.search(r"\barianna\b", text, re.I))
    if not mentioned:
        return
    async with ChatActionSender(bot=bot, chat_id=m.chat.id, action="typing"):
        resp = await engine.ask(user_id, text, is_group=is_group)
        for chunk in engine.split_message(resp):
            await m.answer(chunk)

async def main():
    await engine.setup_assistant()
    app = web.Application()
    path = f"/webhook/{BOT_TOKEN}"
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=path)
    setup_application(app, dp)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🚀 Arianna webhook started on port {port}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
