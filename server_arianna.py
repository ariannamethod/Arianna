import os
import re
import asyncio
import random
import logging
import tempfile
from typing import Optional

import openai
import httpx
from pydub import AudioSegment
from telethon import TelegramClient, events
from telethon.tl.types import MessageEntityMention
from telethon.sessions import StringSession

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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY environment variable is not set")
    raise SystemExit("Missing OPENAI_API_KEY. Set the environment variable and restart the application.")

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    logger.error("DEEPSEEK_API_KEY environment variable is not set")
    raise SystemExit("Missing DEEPSEEK_API_KEY. Set the environment variable and restart the application.")

API_ID = int(os.getenv("TELEGRAM_API_ID", 20973755))
API_HASH = os.getenv("TELEGRAM_API_HASH", "51173cd91874b5f7576b2012f08f40f0")
PHONE = os.getenv("TELEGRAM_PHONE", "+972584038033")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
SESSION_STRING = os.getenv(
    "TELEGRAM_SESSION_STRING",
    (
        "1BJWap1sBuwLNE3K0r3YyH19KqYjpKAgTfUalQz7J_sJbTtN5KiHLMjYVxyA2-qZOivMKx9U_AKQ3H2DGsN1CjCrtgB7PEgWiiwvcxMC7aMx04co"
        "LG6RgnFl0C2jLL6HtDzZS8VrS-L5auPZ7Rw_gm-Oe532NHMZdh1yA2pyyjd2aVJpFJGWULs0P0mGYwXSb5BNTrP2vpyWTCcZa8Ei9KEP6y_nBDtVz"
        "FBKwxBDn5_3wEBjg9SKUS48qZnoIdeD5gsQICjFi0x29oNwIYvOIjnBsg72RfCdaukvGu2yFcDop1Z752a2NUrs0DYXvr990zVwxdlLg1RH6Gk-Ke"
        "MkQDJoN_g8BRrI="
    ),
)


def create_telegram_client(
    phone: Optional[str] = None,
    bot_token: Optional[str] = None,
    session_string: Optional[str] = None,
) -> TelegramClient:
    if session_string:
        return TelegramClient(StringSession(session_string), API_ID, API_HASH)
    session_name = "arianna_bot" if bot_token else "arianna"
    return TelegramClient(session_name, API_ID, API_HASH)


client = create_telegram_client(phone=PHONE, bot_token=BOT_TOKEN, session_string=SESSION_STRING)
engine = AriannaEngine()
openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
DEEPSEEK_CMD = "/ds"
SEARCH_CMD = "/search"
INDEX_CMD = "/index"
VOICE_ON_CMD = "/voiceon"
VOICE_OFF_CMD = "/voiceoff"
VOICE_ENABLED = {}

# --- optional behavior tuning ---
GROUP_DELAY_MIN   = int(os.getenv("GROUP_DELAY_MIN", 120))   # 2 minutes
GROUP_DELAY_MAX   = int(os.getenv("GROUP_DELAY_MAX", 600))   # 10 minutes
PRIVATE_DELAY_MIN = int(os.getenv("PRIVATE_DELAY_MIN", 30))  # 30 seconds
PRIVATE_DELAY_MAX = int(os.getenv("PRIVATE_DELAY_MAX", 180)) # 3 minutes
SKIP_SHORT_PROB   = float(os.getenv("SKIP_SHORT_PROB", 0.5))
FOLLOWUP_PROB     = float(os.getenv("FOLLOWUP_PROB", 0.2))
FOLLOWUP_DELAY_MIN = int(os.getenv("FOLLOWUP_DELAY_MIN", 900))   # 15 minutes
FOLLOWUP_DELAY_MAX = int(os.getenv("FOLLOWUP_DELAY_MAX", 7200))  # 2 hours

# Regex for detecting links
URL_REGEX = re.compile(r"https://\S+")
URL_FETCH_TIMEOUT = int(os.getenv("URL_FETCH_TIMEOUT", 10))

BOT_USERNAME = ""
BOT_ID = 0

async def append_link_snippets(text: str) -> str:
    """Append snippet from any https:// link in the text."""
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
    resp = await openai_client.audio.speech.with_streaming_response.create(
        model="tts-1",
        voice="alloy",
        input=text,
    )
    await resp.stream_to_file(mp3_fd.name)
    AudioSegment.from_file(mp3_fd.name).export(ogg_fd.name, format="ogg", codec="libopus")
    os.remove(mp3_fd.name)
    return ogg_fd.name

def _delay(is_group: bool) -> float:
    return random.uniform(GROUP_DELAY_MIN, GROUP_DELAY_MAX) if is_group else random.uniform(PRIVATE_DELAY_MIN, PRIVATE_DELAY_MAX)

async def send_delayed_response(event, resp: str, is_group: bool, thread_key: str):
    """Send the reply after a randomized delay and schedule optional follow-up."""
    await asyncio.sleep(_delay(is_group))
    if VOICE_ENABLED.get(event.chat_id):
        voice_path = await synthesize_voice(resp)
        await client.send_file(event.chat_id, voice_path, caption=resp[:1024])
        os.remove(voice_path)
    else:
        for chunk in split_message(resp):
            await client.send_message(event.chat_id, chunk)
    if random.random() < FOLLOWUP_PROB:
        asyncio.create_task(schedule_followup(event.chat_id, thread_key, is_group))

async def schedule_followup(chat_id: int, thread_key: str, is_group: bool):
    """Send a short follow-up message referencing the earlier conversation."""
    await asyncio.sleep(random.uniform(FOLLOWUP_DELAY_MIN, FOLLOWUP_DELAY_MAX))
    follow_prompt = "Send a short follow-up message referencing our earlier conversation."
    try:
        resp = await engine.ask(thread_key, follow_prompt, is_group=is_group)
    except httpx.TimeoutException:
        logger.error("Follow-up request timed out", exc_info=True)
        await client.send_message(chat_id, "Request timed out. Please try again later.")
        return
    if VOICE_ENABLED.get(chat_id):
        voice_path = await synthesize_voice(resp)
        await client.send_file(chat_id, voice_path, caption=resp[:1024])
        os.remove(voice_path)
    else:
        for chunk in split_message(resp):
            await client.send_message(chat_id, chunk)

@client.on(events.NewMessage(func=lambda e: bool(e.message.voice)))
async def voice_messages(event):
    is_group = event.is_group
    user_id = str(event.sender_id)
    thread_key = f"{event.chat_id}:{event.sender_id}" if is_group else user_id
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await event.download_media(tmp.name)
    text = await transcribe_voice(tmp.name)
    os.remove(tmp.name)
    text = await append_link_snippets(text)
    if len(text.split()) < 4 or '?' not in text:
        if random.random() < SKIP_SHORT_PROB:
            return
    try:
        resp = await engine.ask(thread_key, text, is_group=is_group)
    except httpx.TimeoutException:
        logger.error("Voice message processing timed out", exc_info=True)
        await event.reply("Request timed out. Please try again later.")
        return
    asyncio.create_task(send_delayed_response(event, resp, is_group, thread_key))

@client.on(events.NewMessage(incoming=True))
async def all_messages(event):
    if event.out:
        return
    user_id = str(event.sender_id)
    text = event.raw_text or ""

    if text.strip().lower().startswith(SEARCH_CMD):
        query = text.strip()[len(SEARCH_CMD):].lstrip()
        if not query:
            return
        chunks = await semantic_search(query, engine.openai_key)
        if not chunks:
            await event.reply("No relevant documents found.")
        else:
            for ch in chunks:
                for part in split_message(ch):
                    await event.reply(part)
        return

    if text.strip().lower().startswith(INDEX_CMD):
        await event.reply("Indexing documents, please wait...")
        async def sender(msg):
            await event.reply(msg)
        await vectorize_all_files(engine.openai_key, force=True, on_message=sender)
        await event.reply("Indexing complete.")
        return

    if text.strip().lower() == VOICE_ON_CMD:
        VOICE_ENABLED[event.chat_id] = True
        await event.reply("Voice responses enabled")
        return
    if text.strip().lower() == VOICE_OFF_CMD:
        VOICE_ENABLED[event.chat_id] = False
        await event.reply("Voice responses disabled")
        return

    if text.strip().lower().startswith(DEEPSEEK_CMD):
        if not DEEPSEEK_ENABLED:
            await event.reply("DeepSeek integration is not configured")
            return
        query = text.strip()[len(DEEPSEEK_CMD):].lstrip()
        if not query:
            return
        resp = await engine.deepseek_reply(query)
        for chunk in split_message(resp):
            await event.reply(chunk)
        return

    is_group = event.is_group
    is_reply = False
    if event.is_reply:
        replied = await event.get_reply_message()
        if replied and replied.sender_id == BOT_ID:
            is_reply = True

    mentioned = False
    if not is_group:
        mentioned = True
    else:
        if re.search(r"\b(arianna|арианна)\b", text, re.I):
            mentioned = True
        elif BOT_USERNAME and f"@{BOT_USERNAME}".lower() in text.lower():
            mentioned = True
        if event.message.entities:
            for ent in event.message.entities:
                if isinstance(ent, MessageEntityMention):
                    ent_text = text[ent.offset: ent.offset + ent.length]
                    if ent_text[1:].lower() == BOT_USERNAME:
                        mentioned = True
                        break

    if is_reply:
        mentioned = True

    if not (mentioned or is_reply):
        return

    if len(text.split()) < 4 or '?' not in text:
        if random.random() < SKIP_SHORT_PROB:
            return

    thread_key = user_id if not is_group else str(event.chat_id)
    prompt = await append_link_snippets(text)
    try:
        resp = await engine.ask(thread_key, prompt, is_group=is_group)
    except httpx.TimeoutException:
        logger.error("OpenAI request timed out", exc_info=True)
        await event.reply("Request timed out. Please try again later.")
        return
    asyncio.create_task(send_delayed_response(event, resp, is_group, thread_key))

async def main():
    global BOT_USERNAME, BOT_ID
    if BOT_TOKEN:
        await client.start(bot_token=BOT_TOKEN)
    elif SESSION_STRING:
        await client.start()
    else:
        await client.start(phone=PHONE)
    me = await client.get_me()
    BOT_USERNAME = (me.username or "").lower()
    BOT_ID = me.id
    try:
        await engine.setup_assistant()
    except Exception:
        logger.exception("Assistant initialization failed")
        await engine.aclose()
        return
    logger.info("🚀 Arianna client started")
    try:
        await client.run_until_disconnected()
    finally:
        await engine.aclose()

if __name__ == "__main__":
    asyncio.run(main())
