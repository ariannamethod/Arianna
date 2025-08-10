import os
import re
import argparse
import asyncio
import random
import logging
import socket
import tempfile
import inspect
from typing import Optional

import openai
import httpx
from pydub import AudioSegment
from telethon import TelegramClient, events, Button
from telethon.tl.types import (
    MessageEntityMention,
    BotCommand,
    BotCommandScopeDefault,
)
from telethon.sessions import StringSession

from utils.arianna_engine import AriannaEngine
from utils.thread_store_sqlite import cleanup_old_threads
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


THREAD_TTL_DAYS = int(os.getenv("THREAD_TTL_DAYS", "30"))
cleanup_old_threads(THREAD_TTL_DAYS)
client = create_telegram_client(phone=PHONE, bot_token=BOT_TOKEN, session_string=SESSION_STRING)
engine = AriannaEngine()
openai_client = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
VOICE_ON_CMD = "/voiceon"
VOICE_OFF_CMD = "/voiceoff"
HELP_CMD = "/help"
VOICE_ENABLED = {}
HELP_TEXT = (
    f"{SEARCH_CMD} <query> - semantic search documents\n"
    f"{INDEX_CMD} - index documents\n"
    f"{DEEPSEEK_CMD} <query> - ask DeepSeek\n"
    f"{VOICE_ON_CMD} - enable voice responses\n"
    f"{VOICE_OFF_CMD} - disable voice responses\n"
    f"{HELP_CMD} - show this help message"
)

def default_buttons():
    """Inline buttons for common actions."""
    return [
        [Button.inline("Voice On", b"voice_on"), Button.inline("Voice Off", b"voice_off")],
        [Button.inline("Search docs", b"search_docs")],
    ]

# --- optional behavior tuning ---
arg_parser = argparse.ArgumentParser(add_help=False)
arg_parser.add_argument("--group-delay-min", type=int, help="Min reply delay in group chats")
arg_parser.add_argument("--group-delay-max", type=int, help="Max reply delay in group chats")
arg_parser.add_argument("--private-delay-min", type=int, help="Min reply delay in private chats")
arg_parser.add_argument("--private-delay-max", type=int, help="Max reply delay in private chats")
arg_parser.add_argument("--no-delay", action="store_true", help="Disable reply delays")
cli_args, _ = arg_parser.parse_known_args()

DISABLE_DELAY = cli_args.no_delay or os.getenv("DISABLE_DELAY", "").lower() in ("1", "true", "yes")

GROUP_DELAY_MIN = int(cli_args.group_delay_min if cli_args.group_delay_min is not None else os.getenv("GROUP_DELAY_MIN", 120))   # 2 minutes
GROUP_DELAY_MAX = int(cli_args.group_delay_max if cli_args.group_delay_max is not None else os.getenv("GROUP_DELAY_MAX", 600))   # 10 minutes
PRIVATE_DELAY_MIN = int(cli_args.private_delay_min if cli_args.private_delay_min is not None else os.getenv("PRIVATE_DELAY_MIN", 30))  # 30 seconds
PRIVATE_DELAY_MAX = int(cli_args.private_delay_max if cli_args.private_delay_max is not None else os.getenv("PRIVATE_DELAY_MAX", 180)) # 3 minutes

if DISABLE_DELAY:
    GROUP_DELAY_MIN = GROUP_DELAY_MAX = PRIVATE_DELAY_MIN = PRIVATE_DELAY_MAX = 0

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
    if DISABLE_DELAY:
        return 0.0
    return random.uniform(GROUP_DELAY_MIN, GROUP_DELAY_MAX) if is_group else random.uniform(PRIVATE_DELAY_MIN, PRIVATE_DELAY_MAX)

async def send_delayed_response(event, resp: str, is_group: bool, thread_key: str):
    """Send the reply after a randomized delay and schedule optional follow-up."""
    await client.send_chat_action(event.chat_id, 'typing')
    await asyncio.sleep(_delay(is_group))
    if VOICE_ENABLED.get(event.chat_id):
        voice_path = await synthesize_voice(resp)
        if os.path.exists(voice_path):
            await client.send_file(
                event.chat_id,
                voice_path,
                caption=resp[:1024],
                parse_mode=PARSE_MODE,
                buttons=default_buttons(),
            )
            os.remove(voice_path)
        else:
            await client.send_message(
                event.chat_id,
                voice_path,
                parse_mode=PARSE_MODE,
                buttons=default_buttons(),
            )
    else:
        async def send(chunk: str) -> None:
            await client.send_message(
                event.chat_id,
                chunk,
                parse_mode=PARSE_MODE,
                buttons=default_buttons(),
            )
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
            await client.send_file(
                chat_id,
                voice_path,
                caption=resp[:1024],
                parse_mode=PARSE_MODE,
                buttons=default_buttons(),
            )
            os.remove(voice_path)
        else:
            await client.send_message(
                chat_id,
                voice_path,
                parse_mode=PARSE_MODE,
                buttons=default_buttons(),
            )
    else:
        async def send(chunk: str) -> None:
            await client.send_message(
                chat_id,
                chunk,
                parse_mode=PARSE_MODE,
                buttons=default_buttons(),
            )
        await dispatch_response(send, resp)

@client.on(events.NewMessage(func=lambda e: bool(e.message.voice)))
async def voice_messages(event):
    is_group = event.is_group
    user_id = str(event.sender_id)
    thread_key = str(event.chat_id) if is_group else user_id
    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        await event.download_media(tmp.name)
    text = await transcribe_voice(tmp.name)
    if text.startswith("Sorry, I couldn't transcribe"):
        await event.reply(text)
        logger.info("Skipping voice message: transcription failed")
        return
    text = await append_link_snippets(text)
    if len(text.split()) < 4 or '?' not in text:
        skip_prob = SKIP_SHORT_PROB if is_group else 0.0
        if random.random() < skip_prob:
            logger.info("Skipping voice message: too short or no question")
            await event.reply("Уточните вопрос.")
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
    user_id = str(event.sender_id)
    text = event.raw_text or ""

    cmd, arg = parse_command(text, BOT_USERNAME)
    if cmd == SEARCH_CMD:
        if not arg:
            logger.info("Search command missing argument")
            return
        chunks = await semantic_search(arg, engine.openai_key)
        if not chunks:
            await event.reply("No relevant documents found.")
        else:
            async def send(part: str) -> None:
                await event.reply(part)
            for ch in chunks:
                await dispatch_response(send, ch)
        return

    if cmd == INDEX_CMD:
        await event.reply("Indexing documents, please wait...")
        async def sender(msg):
            await event.reply(msg)
        await vectorize_all_files(engine.openai_key, force=True, on_message=sender)
        await event.reply("Indexing complete.")
        return

    if text.strip().lower() == VOICE_ON_CMD:
        VOICE_ENABLED[event.chat_id] = True
        await event.reply("Voice responses enabled", buttons=default_buttons())
        return
    if text.strip().lower() == VOICE_OFF_CMD:
        VOICE_ENABLED[event.chat_id] = False
        await event.reply("Voice responses disabled", buttons=default_buttons())
        return
    if text.strip().lower() == HELP_CMD:
        await event.reply(HELP_TEXT, buttons=default_buttons())
        return

    if cmd == DEEPSEEK_CMD:
        if not DEEPSEEK_ENABLED:
            await event.reply("DeepSeek integration is not configured")
            return
        if not arg:
            logger.info("DeepSeek command missing argument")
            return
        resp = await engine.deepseek_reply(arg)
        async def send(part: str) -> None:
            await event.reply(part)
        await dispatch_response(send, resp)
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
        logger.info("Message ignored: bot not mentioned and not a reply")
        return

    if len(text.split()) < 4 or '?' not in text:
        skip_prob = SKIP_SHORT_PROB if is_group else 0.0
        if random.random() < skip_prob:
            logger.info("Skipping message: too short or no question")
            await event.reply("Уточните вопрос.")
            return

    thread_key = user_id if not is_group else str(event.chat_id)
    prompt = await append_link_snippets(text)
    logger.info("Message text: %s", text)
    try:
        resp = await engine.ask(thread_key, prompt, is_group=is_group)
    except httpx.TimeoutException:
        logger.error("OpenAI request timed out: %s", text, exc_info=True)
        await event.reply("Request timed out. Please try again later.")
        return
    except TimeoutError:
        logger.error("Timeout error while processing message: %s", text, exc_info=True)
        await event.reply("Request timed out. Please try again later.")
        return
    except Exception:
        logger.exception("Failed to process message: %s", text)
        await event.reply("Internal error occurred. Please try again later.")
        return
    asyncio.create_task(send_delayed_response(event, resp, is_group, thread_key))


@client.on(events.CallbackQuery)
async def callback_query_handler(event):
    """Handle presses of inline buttons."""
    data = event.data.decode("utf-8")
    if data == "voice_on":
        VOICE_ENABLED[event.chat_id] = True
        await event.respond("Voice responses enabled", buttons=default_buttons())
    elif data == "voice_off":
        VOICE_ENABLED[event.chat_id] = False
        await event.respond("Voice responses disabled", buttons=default_buttons())
    elif data == "search_docs":
        await event.respond("Use /search <query> to search documents", buttons=default_buttons())
    await event.answer()

async def main():
    global BOT_USERNAME, BOT_ID
    
    # Диагностика сети перед подключением
    try:
        logger.info(f"Проверка подключения к api.telegram.org...")
        ip_address = socket.gethostbyname("api.telegram.org")
        logger.info(f"IP адрес api.telegram.org: {ip_address}")
        
        # Проверка подключения к конкретному IP и порту
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_socket.settimeout(5)
        result = test_socket.connect_ex(("149.154.167.91", 443))
        test_socket.close()
        
        if result == 0:
            logger.info("Подключение к 149.154.167.91:443 успешно")
        else:
            logger.warning(f"Не удалось подключиться к 149.154.167.91:443, код ошибки: {result}")
    except Exception as e:
        logger.error(f"Ошибка при проверке сети: {e}")
    
    # Пробуем подключиться
    try:
        if BOT_TOKEN:
            logger.info("Подключение через BOT_TOKEN...")
            await client.start(bot_token=BOT_TOKEN)
        elif SESSION_STRING:
            logger.info("Подключение через SESSION_STRING...")
            await client.start()
        else:
            logger.info("Подключение через PHONE...")
            await client.start(phone=PHONE)
        logger.info("Подключение успешно!")
    except Exception as e:
        logger.error(f"Ошибка при подключении: {e}", exc_info=True)
        raise SystemExit(f"Не удалось подключиться: {e}")
    me = await client.get_me()
    if BOT_TOKEN or getattr(me, "bot", False):
        await client.set_bot_commands(
            [
                BotCommand(SEARCH_CMD.lstrip("/"), "Semantic search documents"),
                BotCommand(INDEX_CMD.lstrip("/"), "Index documents"),
                BotCommand(DEEPSEEK_CMD.lstrip("/"), "Ask DeepSeek"),
                BotCommand(VOICE_ON_CMD.lstrip("/"), "Enable voice responses"),
                BotCommand(VOICE_OFF_CMD.lstrip("/"), "Disable voice responses"),
                BotCommand(HELP_CMD.lstrip("/"), "Show help"),
            ],
            scope=BotCommandScopeDefault(),
        )
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
        await openai_client.close()

if __name__ == "__main__":
    asyncio.run(main())
