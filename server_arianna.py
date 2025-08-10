import os
import asyncio
import logging
import random
import tempfile
import inspect
from typing import Optional

import openai
import httpx
from pydub import AudioSegment
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from utils.arianna_engine import AriannaEngine
from utils.bot_handlers import append_link_snippets, dispatch_response, SKIP_SHORT_PROB
from utils.message_router import route_message

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

api_id_str = os.getenv("TELEGRAM_API_ID")
if not api_id_str:
    logger.error("TELEGRAM_API_ID environment variable is not set")
    raise SystemExit("Missing TELEGRAM_API_ID. Set the environment variable and restart the application.")
API_ID = int(api_id_str)

API_HASH = os.getenv("TELEGRAM_API_HASH")
if not API_HASH:
    logger.error("TELEGRAM_API_HASH environment variable is not set")
    raise SystemExit("Missing TELEGRAM_API_HASH. Set the environment variable and restart the application.")

PHONE = os.getenv("TELEGRAM_PHONE")
if not PHONE:
    logger.error("TELEGRAM_PHONE environment variable is not set")
    raise SystemExit("Missing TELEGRAM_PHONE. Set the environment variable and restart the application.")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")

SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")
if not SESSION_STRING:
    logger.error("TELEGRAM_SESSION_STRING environment variable is not set")
    raise SystemExit("Missing TELEGRAM_SESSION_STRING. Set the environment variable and restart the application.")


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
VOICE_ON_CMD = "/voiceon"
VOICE_OFF_CMD = "/voiceoff"
VOICE_ENABLED = {}

# --- optional behavior tuning ---
GROUP_DELAY_MIN   = int(os.getenv("GROUP_DELAY_MIN", 120))   # 2 minutes
GROUP_DELAY_MAX   = int(os.getenv("GROUP_DELAY_MAX", 600))   # 10 minutes
PRIVATE_DELAY_MIN = int(os.getenv("PRIVATE_DELAY_MIN", 30))  # 30 seconds
PRIVATE_DELAY_MAX = int(os.getenv("PRIVATE_DELAY_MAX", 180)) # 3 minutes
FOLLOWUP_PROB     = float(os.getenv("FOLLOWUP_PROB", 0.2))
FOLLOWUP_DELAY_MIN = int(os.getenv("FOLLOWUP_DELAY_MIN", 900))   # 15 minutes
FOLLOWUP_DELAY_MAX = int(os.getenv("FOLLOWUP_DELAY_MAX", 7200))  # 2 hours

BOT_USERNAME = ""
BOT_ID = 0

DISABLE_FORMATTING = os.getenv("TELEGRAM_DISABLE_FORMATTING")
PARSE_MODE = None if DISABLE_FORMATTING else os.getenv("TELEGRAM_PARSE_MODE", "MarkdownV2").lower()

async def transcribe_voice(file_path: str) -> str:
    """Transcribe an audio file using OpenAI Whisper."""
    resp = None
    try:
        with open(file_path, "rb") as f:
            resp = await openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
            )
        return resp.text
    except Exception:
        logger.error("Failed to transcribe voice message", exc_info=True)
        return "Sorry, I couldn't transcribe that audio."
    finally:
        if resp and hasattr(resp, "close"):
            close = resp.close
            try:
                if inspect.iscoroutinefunction(close):
                    await close()
                else:
                    close()
            except Exception:
                logger.warning("Failed to close transcription response", exc_info=True)
        try:
            os.remove(file_path)
        except OSError:
            logger.warning("Could not remove temporary file %s", file_path, exc_info=True)

async def synthesize_voice(text: str) -> str:
    """Synthesize speech from text using OpenAI TTS and return OGG path."""
    mp3_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    ogg_fd = tempfile.NamedTemporaryFile(delete=False, suffix=".ogg")
    mp3_path, ogg_path = mp3_fd.name, ogg_fd.name
    mp3_fd.close()
    ogg_fd.close()
    success = False
    resp = None
    try:
        resp = await openai_client.audio.speech.with_streaming_response.create(
            model="tts-1",
            voice="alloy",
            input=text,
        )
        await resp.stream_to_file(mp3_path)
        AudioSegment.from_file(mp3_path).export(ogg_path, format="ogg", codec="libopus")
        success = True
        return ogg_path
    except Exception:
        logger.error("Failed to synthesize voice", exc_info=True)
        return "Sorry, I couldn't synthesize that speech."
    finally:
        if resp is not None:
            try:
                await resp.close()
            except Exception:
                logger.warning("Failed to close speech response", exc_info=True)
        try:
            os.remove(mp3_path)
        except OSError:
            logger.warning("Could not remove temporary file %s", mp3_path, exc_info=True)
        if not success:
            try:
                os.remove(ogg_path)
            except OSError:
                logger.warning("Could not remove temporary file %s", ogg_path, exc_info=True)

def _delay(is_group: bool) -> float:
    return random.uniform(GROUP_DELAY_MIN, GROUP_DELAY_MAX) if is_group else random.uniform(PRIVATE_DELAY_MIN, PRIVATE_DELAY_MAX)

async def send_delayed_response(event, resp: str, is_group: bool, thread_key: str):
    """Send the reply after a randomized delay and schedule optional follow-up."""
    await client.send_chat_action(event.chat_id, 'typing')
    await asyncio.sleep(_delay(is_group))
    if VOICE_ENABLED.get(event.chat_id):
        voice_path = await synthesize_voice(resp)
        if os.path.exists(voice_path):
            await client.send_file(event.chat_id, voice_path, caption=resp[:1024], parse_mode=PARSE_MODE)
            os.remove(voice_path)
        else:
            await client.send_message(event.chat_id, voice_path, parse_mode=PARSE_MODE)
    else:
        async def send(chunk: str) -> None:
            await client.send_message(event.chat_id, chunk, parse_mode=PARSE_MODE)
        await dispatch_response(send, resp)
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
        await client.send_message(chat_id, "Request timed out. Please try again later.", parse_mode=PARSE_MODE)
        return
    if VOICE_ENABLED.get(chat_id):
        voice_path = await synthesize_voice(resp)
        if os.path.exists(voice_path):
            await client.send_file(chat_id, voice_path, caption=resp[:1024], parse_mode=PARSE_MODE)
            os.remove(voice_path)
        else:
            await client.send_message(chat_id, voice_path, parse_mode=PARSE_MODE)
    else:
        async def send(chunk: str) -> None:
            await client.send_message(chat_id, chunk, parse_mode=PARSE_MODE)
        await dispatch_response(send, resp)

@client.on(events.NewMessage(func=lambda e: bool(e.message.voice)))
async def voice_messages(event):
    is_group = event.is_group
    user_id = str(event.sender_id)
    thread_key = f"{event.chat_id}:{event.sender_id}" if is_group else user_id
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await event.download_media(tmp.name)
    text = await transcribe_voice(tmp.name)
    if text.startswith("Sorry, I couldn't transcribe"):
        await event.reply(text)
        logger.info("Skipping voice message: transcription failed")
        return
    text = await append_link_snippets(text)
    if len(text.split()) < 4 or '?' not in text:
        if random.random() < SKIP_SHORT_PROB:
            logger.info("Skipping voice message: too short or no question")
            return
    logger.info("Voice message text: %s", text)
    try:
        resp = await engine.ask(thread_key, text, is_group=is_group)
    except httpx.TimeoutException:
        logger.error("Voice message processing timed out: %s", text, exc_info=True)
        await event.reply("Request timed out. Please try again later.")
        return
    except TimeoutError:
        logger.error("Voice message processing timeout error: %s", text, exc_info=True)
        await event.reply("Request timed out. Please try again later.")
        return
    except Exception:
        logger.exception("Voice message processing failed: %s", text)
        await event.reply("Internal error occurred. Please try again later.")
        return
    asyncio.create_task(send_delayed_response(event, resp, is_group, thread_key))

@client.on(events.NewMessage(incoming=True))
async def all_messages(event):
    if event.out:
        logger.info("Ignoring outgoing message")
        return
    user_id = event.sender_id
    text = event.raw_text or ""

    if text.strip().lower() == VOICE_ON_CMD:
        VOICE_ENABLED[event.chat_id] = True
        await event.reply("Voice responses enabled")
        return
    if text.strip().lower() == VOICE_OFF_CMD:
        VOICE_ENABLED[event.chat_id] = False
        await event.reply("Voice responses disabled")
        return

    is_reply = False
    if event.is_reply:
        replied = await event.get_reply_message()
        if replied and replied.sender_id == BOT_ID:
            is_reply = True

    async def send_msg(part: str) -> None:
        await event.reply(part, parse_mode=PARSE_MODE)

    async def answer(resp: str, thread_key: str, is_group: bool) -> None:
        asyncio.create_task(send_delayed_response(event, resp, is_group, thread_key))

    await route_message(
        text,
        event.chat_id,
        user_id,
        is_group=event.is_group,
        bot_username=BOT_USERNAME,
        send_reply=send_msg,
        respond=answer,
        engine=engine,
        entities=event.message.entities,
        is_reply=is_reply,
    )

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
    except RuntimeError:
        logger.exception("Assistant initialization failed")
        await engine.aclose()
        raise SystemExit(1)
    logger.info("🚀 Arianna client started")
    try:
        await client.run_until_disconnected()
    finally:
        await engine.aclose()

if __name__ == "__main__":
    asyncio.run(main())
