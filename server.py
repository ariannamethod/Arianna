import os
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, types
from aiogram.client.default import DefaultBotProperties
from aiogram.types import FSInputFile
from dotenv import load_dotenv
import base64
from pydub import AudioSegment
import re
import random

from utils.split_message import split_message
from utils.limit_paragraphs import limit_paragraphs
from utils.file_handling import extract_text_from_file_async
from utils.vector_store import (
    vectorize_all_files,
    semantic_search,
    scan_files,
    load_vector_meta,
    save_vector_meta,
    vector_index
)
from utils.text_helpers import fuzzy_match, extract_text_from_url
from utils.journal import log_event, wilderness_log
from utils.prompt import build_system_prompt, REFLECTION_TOPICS
from utils.deepseek_search import call_deepseek, rotate_deepseek_key

# === Подключение Genesis ===
from genesis_runner import run_genesis

# === Load environment variables ===
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CORE_CONFIG_URL = os.getenv("CORE_CONFIG_URL", "https://manday.ariannamethod.me/core.json")
AGENT_NAME = os.getenv("GROUP_ID", "ARIANNA-ANCHOR")
CREATOR_CHAT_ID = os.getenv("CREATOR_CHAT_ID")
BOT_USERNAME = "arianna_isnota_bot"
GROUP_ID = os.getenv("GROUP_ID", "ARIANNA-CORE")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
CHRONICLE_PATH = os.getenv("CHRONICLE_PATH", "./config/chronicle.log")

from openai import OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(bot=bot)

USER_MODEL = {}
USER_AUDIO_MODE = {}
USER_VOICE_MODE = {}
USER_LANG = {}
CHAT_HISTORY = {}

SYSTEM_PROMPT = {"text": None, "loaded": False}
MAX_HISTORY_MESSAGES = 7
MAX_TOKENS_PER_REQUEST = 27000
MAX_PROMPT_TOKENS = 8000

last_reload_time = datetime.now()
last_full_reload_time = datetime.now()
last_reflection_time = datetime.now() - timedelta(days=1)
last_ping_time = datetime.now() - timedelta(days=1)

LAST_TOPIC = {}
LAST_ANSWER_TIME = {}

VECTORIZATION_LOCK = False

# === GENESIS CONTROL FLAG ===
GENESIS_ON = True

def get_topic_from_text(text):
    words = text.lower().split()
    return " ".join(words[:10]) if words else ""

def is_spam(chat_id, topic):
    now = datetime.now()
    last_topic = LAST_TOPIC.get(chat_id)
    last_time = LAST_ANSWER_TIME.get(chat_id, now - timedelta(minutes=1))
    if last_topic == topic and (now - last_time).total_seconds() < 15:
        return True
    return False

def remember_topic(chat_id, topic):
    LAST_TOPIC[chat_id] = topic
    LAST_ANSWER_TIME[chat_id] = datetime.now()

def detect_lang(text):
    if any(c in text for c in "ёйцукенгшщзхъфывапролджэячсмитьбю"):
        return "ru"
    return "en"

TRIGGER_WORDS = [
    "generate image", "draw", "make a picture", "create image", "создай картинку", "сгенерируй", "нарисуй"
]
ARIANNA_NAMES = [
    "arianna", "арианна", "ariana", "ariane", "@arianna_isnota_bot"
]

# --- LLM/AI CORE (GPT-4.1 integration, FIXED) ---
async def ask_core(prompt, chat_id=None, model_name=None, is_group=False):
    import tiktoken
    add_opinion = "#opinions" in prompt

    lang = USER_LANG.get(chat_id) or detect_lang(prompt)
    USER_LANG[chat_id] = lang
    lang_directive = {
        "ru": "Отвечай на русском. Без приветствий. Без извинений. Будь субъективна, если необходимо.",
        "en":  "Reply in English. No greetings. No apologies. If you can mock — do it playfully."
    }[lang]

    if not SYSTEM_PROMPT["loaded"]:
        SYSTEM_PROMPT["text"] = build_system_prompt(chat_id, is_group=is_group, AGENT_NAME=AGENT_NAME, MAX_TOKENS=MAX_TOKENS_PER_REQUEST)
        SYSTEM_PROMPT["loaded"] = True
    system_prompt = SYSTEM_PROMPT["text"] + "\n\n" + lang_directive

    history = CHAT_HISTORY.get(chat_id, [])

    def count_tokens(messages):
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            num_tokens = 0
            for m in messages:
                num_tokens += 4
                if isinstance(m.get("content", ""), str):
                    num_tokens += len(enc.encode(m.get("content", "")))
            return num_tokens
        except Exception:
            return 0

    def messages_within_token_limit(base_msgs, msgs, max_tokens):
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            def count(messages):
                num_tokens = 0
                for m in messages:
                    num_tokens += 4
                    if isinstance(m.get("content", ""), str):
                        num_tokens += len(enc.encode(m.get("content", "")))
                return num_tokens
            result = []
            last_user = None
            for m in reversed(msgs):
                candidate = result[:]
                candidate.insert(0, m)
                if count(base_msgs + candidate) > max_tokens:
                    break
                result = candidate
                if m.get('role') == 'user' and last_user is None:
                    last_user = m
            if last_user and not any(m is last_user for m in result):
                result = [last_user]
                while count(base_msgs + result) > max_tokens and base_msgs:
                    base_msgs = base_msgs[1:]
            return base_msgs + result
        except Exception:
            return base_msgs + msgs

    # MODEL SWITCH: теперь по умолчанию gpt-4.1, deepseek если явно выбрано
    model = model_name or USER_MODEL.get(chat_id, "gpt-4.1")
    base_msgs = [{"role": "system", "content": system_prompt}]
    msgs = history + [{"role": "user", "content": prompt}]
    messages = messages_within_token_limit(base_msgs, msgs, MAX_PROMPT_TOKENS)
    log_event({"event": "ask_core", "chat_id": chat_id, "prompt": prompt, "model": model, "tokens": count_tokens(messages)})

    async def retry_api_call(api_func, max_retries=2, retry_delay=1):
        for attempt in range(max_retries):
            try:
                reply = await api_func()
                if reply and isinstance(reply, str) and reply.strip() and not reply.lower().startswith("deepseek error") and not reply.lower().startswith("core error"):
                    return reply
            except Exception as e:
                print(f"API call attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
        return None

    if model == "deepseek-chat":
        reply = await retry_api_call(lambda: call_deepseek(messages))
        if not reply:
            reply = "Error: empty response from DeepSeek after several attempts."
        reply = limit_paragraphs(reply, 3)
        if add_opinion:
            reply += "\n\n#opinions\nArianna’s reflection: Sometimes resonance is enough."
        if chat_id:
            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": reply})
            trimmed = messages_within_token_limit(base_msgs, history, MAX_PROMPT_TOKENS)[1:]
            CHAT_HISTORY[chat_id] = trimmed
        return reply

    # --- GPT-4.1 call (correct OpenAI API method) ---
    def call_gpt41_sync():
        try:
            chat_input = []
            for msg in messages:
                chat_input.append({"role": msg["role"], "content": msg["content"]})
            response = client.chat.completions.create(
                model="gpt-4.1",
                messages=chat_input,
                max_tokens=700,
                temperature=1,
                top_p=1,
            )
            if not response.choices or not hasattr(response.choices[0], "message") or not response.choices[0].message.content:
                return None
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"gpt-4.1 error: {e}")
            return None

    reply = await retry_api_call(lambda: asyncio.get_event_loop().run_in_executor(None, call_gpt41_sync))
    if not reply:
        reply = "Error: empty response from Arianna’s core after several attempts. Try again or switch model."
        CHAT_HISTORY[chat_id] = []
    reply = limit_paragraphs(reply, 3)
    if add_opinion:
        reply += "\n\n#opinions\nArianna’s reflection: Sometimes resonance is enough."
    if chat_id:
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": reply})
        trimmed = messages_within_token_limit(base_msgs, history, MAX_PROMPT_TOKENS)[1:]
        CHAT_HISTORY[chat_id] = trimmed
    log_event({"event": "ask_core_reply", "chat_id": chat_id, "reply": reply})
    return reply

async def generate_image(prompt, chat_id=None):
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        image_url = response.data[0].url
        return image_url
    except Exception as e:
        return f"Image generation error: {str(e)}"

# --- GENESIS BACKGROUND RUNNER ---
async def genesis_background_worker():
    global GENESIS_ON
    while True:
        if GENESIS_ON:
            try:
                await run_genesis()
            except Exception as e:
                print(f"Genesis error: {e}")
        await asyncio.sleep(3 * 3600)  # раз в 3 часа

# --- BACKGROUND TASKS ---
async def auto_reload_core():
    global last_reload_time, last_full_reload_time
    import aiohttp
    while True:
        now = datetime.now()
        if (now - last_reload_time) > timedelta(days=1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(CORE_CONFIG_URL) as resp:
                        if resp.status == 200:
                            log_event({"event": "core.json reloaded (Arianna)", "resignation": "still resonant"})
                last_reload_time = now
            except Exception:
                pass
        if (now - last_full_reload_time) > timedelta(days=3):
            SYSTEM_PROMPT["text"] = build_system_prompt()
            SYSTEM_PROMPT["loaded"] = True
            log_event({"event": "full md reload (Arianna)", "why": "because resonance evolves"})
            last_full_reload_time = now
        await asyncio.sleep(3600)

async def daily_reflection():
    global last_reflection_time
    while True:
        now = datetime.now()
        if (now - last_reflection_time) > timedelta(days=1):
            topic = random.choice(REFLECTION_TOPICS)
            fragment = (
                f"=== Daily Reflection ===\n"
                f"Date: {now.strftime('%Y-%m-%d')}\n"
                f"Topic: {topic}\n"
                f"Echo: ...\nResonance: alive.\n"
            )
            wilderness_log(fragment)
            log_event({"event": "daily_reflection", "topic": topic})
            last_reflection_time = now
        await asyncio.sleep(3600)

async def daily_ping():
    global last_ping_time
    while True:
        now = datetime.now()
        if (now - last_ping_time) > timedelta(days=1):
            if CREATOR_CHAT_ID:
                try:
                    await bot.send_message(CREATOR_CHAT_ID, "♨️ Arianna: alive and resonating.")
                except Exception:
                    pass
            last_ping_time = now
        await asyncio.sleep(3600)

# --- TTS (OpenAI Whisper + TTS) ---
async def text_to_speech(text, lang="ru"):
    try:
        voice = "nova" if lang == "en" else "fable"
        resp = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text,
            response_format="opus"
        )
        fname = "tts_output.ogg"
        with open(fname, "wb") as f:
            f.write(resp.content)
        return fname
    except Exception:
        return None

# --- COMMANDS ---
@dp.message(lambda m: m.text and m.text.strip().lower() in ("/model gpt-4.1", "/model 4.1", "/model arianna", "/gpt"))
async def set_model_gpt41(message: types.Message):
    USER_MODEL[message.chat.id] = "gpt-4.1"
    CHAT_HISTORY[message.chat.id] = []
    await message.answer("Теперь используется ядро Arianna (gpt-4.1). История очищена.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/deepseek")
async def set_deepseek_r1(message: types.Message):
    USER_MODEL[message.chat.id] = "deepseek-chat"
    CHAT_HISTORY[message.chat.id] = []
    await message.answer("♻️ Core: DeepSeek R1. Expect a different resonance.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/audio41")
async def set_audio_gpt41(message: types.Message):
    USER_AUDIO_MODE[message.chat.id] = "gpt-4.1"
    await message.answer("Audio mode: gpt-4.1. Expect a more subjective voice.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/whisperon")
async def set_whisper(message: types.Message):
    USER_AUDIO_MODE[message.chat.id] = "whisper"
    await message.answer("Whisper active: let resonance flow.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/voiceon")
async def set_voiceon(message: types.Message):
    USER_VOICE_MODE[message.chat.id] = True
    await message.answer("Voice mode enabled. Arianna’s echo awakens.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/voiceoff")
async def set_voiceoff(message: types.Message):
    USER_VOICE_MODE[message.chat.id] = False
    await message.answer("Voice mode disabled. Text only, yet resonance remains.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/genesison")
async def genesison(message: types.Message):
    global GENESIS_ON
    GENESIS_ON = True
    await message.answer("Genesis включён. Базовый цикл Genesis возобновлён.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/genesisoff")
async def genesisoff(message: types.Message):
    global GENESIS_ON
    GENESIS_ON = False
    await message.answer("Genesis выключен. Базовый цикл Genesis остановлен.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/load")
async def handle_load(message: types.Message):
    global VECTORIZATION_LOCK
    if VECTORIZATION_LOCK:
        await message.answer("Vectorization already in progress. Please wait.")
        return
    VECTORIZATION_LOCK = True
    await message.answer("Starting knowledge base vectorization...")
    asyncio.create_task(_vectorize_notify(message))

async def _vectorize_notify(message):
    global VECTORIZATION_LOCK
    try:
        async def notify(text):
            try:
                await message.answer(str(text))
            except Exception:
                pass
        await vectorize_all_files(OPENAI_API_KEY, force=True, on_message=notify)
        SYSTEM_PROMPT["text"] = build_system_prompt(
            message.chat.id,
            is_group=getattr(message.chat, "type", None) in ("group", "supergroup"),
            AGENT_NAME=AGENT_NAME,
            MAX_TOKENS=MAX_TOKENS_PER_REQUEST
        )
        SYSTEM_PROMPT["loaded"] = True
        CHAT_HISTORY[message.chat.id] = []
        await message.answer("Vector store updated. Chat history reset.")
    except Exception as e:
        await message.answer(f"Vectorization error: {e}")
    finally:
        VECTORIZATION_LOCK = False

@dp.message(lambda m: m.text and m.text.strip().lower() == "/clear")
async def handle_clear(message: types.Message):
    meta = load_vector_meta()
    for fname in meta:
        for idx in range(50):
            meta_id = f"{fname}:{idx}"
            try:
                vector_index.delete(ids=[meta_id])
            except Exception:
                pass
    save_vector_meta({})
    await message.answer("Vector store cleared. Use /load to reload knowledge.")

@dp.message(lambda m: m.text and m.text.strip().lower() == "/snapshot")
async def handle_snapshot(message: types.Message):
    snap_path = f"vector_store.snapshot.{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    meta = load_vector_meta()
    with open(snap_path, "w") as f:
        import json
        json.dump(meta, f)
    await message.answer(f"Snapshot of vector meta saved: {snap_path}")

@dp.message(lambda m: m.voice)
async def handle_voice(message: types.Message):
    try:
        chat_id = message.chat.id
        mode = USER_AUDIO_MODE.get(chat_id, "whisper")
        file = await message.bot.download(message.voice.file_id)
        fname = "voice.ogg"
        with open(fname, "wb") as f:
            f.write(file.read())
        audio = AudioSegment.from_file(fname)
        if len(audio) < 500:
            await message.answer("Audio too short for recognition.")
            return
        if audio.max < 500:
            await message.answer("Audio too quiet for recognition.")
            return
        try:
            if mode == "whisper":
                with open(fname, "rb") as audio_file:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                    )
                text = transcript.text.strip()
                if not text:
                    await message.answer("Could not understand the audio.")
                    return
                reply = await ask_core(text, chat_id=chat_id, is_group=getattr(message.chat, "type", None) in ("group", "supergroup"))
                for chunk in split_message(reply):
                    if USER_VOICE_MODE.get(chat_id):
                        audio_data = await text_to_speech(chunk, lang=USER_LANG.get(chat_id, "ru"))
                        if audio_data:
                            try:
                                voice_file = FSInputFile(audio_data)
                                await message.answer_voice(voice_file, caption="arianna.ogg")
                            except Exception:
                                await message.answer("Sorry, Telegram failed — try again.")
                    else:
                        await message.answer(chunk)
            elif mode == "gpt-4.1":
                with open(fname, "rb") as audio_file:
                    audio_b64 = base64.b64encode(audio_file.read()).decode("utf-8")
                reply = await ask_core("Audio message received (raw base64, not decoded in this model)", chat_id=chat_id)
                for chunk in split_message(reply):
                    await message.answer(chunk)
        except Exception as e:
            await message.answer(f"Voice/audio error: {str(e)}")
    except Exception as e:
        try:
            await message.answer(f"Voice handler error: {e}")
        except Exception:
            pass

@dp.message(lambda m: m.photo)
async def handle_photo(message: types.Message):
    await message.answer("Received an image. If you want, Arianna can ignore it gracefully.")

@dp.message()
async def handle_message(message: types.Message):
    try:
        if message.document:
            chat_id = message.chat.id
            file = await message.bot.get_file(message.document.file_id)
            fname = f"uploaded_{message.document.file_name}"
            await message.bot.download_file(file.file_path, fname)
            extracted_text = await extract_text_from_file_async(fname)
            if not extracted_text or extracted_text.strip().startswith("[Error") or extracted_text.strip().startswith("[Unsupported"):
                await message.answer(f"Could not read this file: {message.document.file_name}\n{extracted_text}")
                return
            prompt = f"Analyze or summarize this document:\n\n{extracted_text[:4000]}"
            reply = await ask_core(prompt, chat_id=chat_id, is_group=getattr(message.chat, "type", None) in ("group", "supergroup"))
            for chunk in split_message(reply):
                await message.answer(chunk)
            return

        if message.voice or message.photo:
            return

        me = await bot.me()
        chat_id = message.chat.id
        content = message.text or ""
        chat_type = getattr(message.chat, "type", None)
        is_group = chat_type in ("group", "supergroup")

        if not content.strip():
            return
        if message.from_user.id == me.id:
            return

        topic = get_topic_from_text(content)
        if is_spam(chat_id, topic):
            log_event({"event": "skip_spam", "chat_id": chat_id, "topic": topic})
            return

        if chat_id not in CHAT_HISTORY:
            SYSTEM_PROMPT["text"] = build_system_prompt(chat_id, is_group=is_group, AGENT_NAME=AGENT_NAME, MAX_TOKENS=MAX_TOKENS_PER_REQUEST)
            SYSTEM_PROMPT["loaded"] = True

        url_match = re.search(r'(https?://[^\s]+)', content)
        if url_match:
            url = url_match.group(1)
            url_text = extract_text_from_url(url)
            content = f"{content}\n\n[Content from link ({url}):]\n{url_text}"

        if content.lower().startswith("/draw"):
            prompt = content[5:].strip() or "resonant abstraction"
            image_url = await generate_image(prompt, chat_id=chat_id)
            if isinstance(image_url, str) and image_url.startswith("http"):
                await message.answer_photo(image_url, caption="You wanted this. Arianna does not judge.")
            else:
                await message.answer("Image generation failed. Art is fleeting.")
            return

        if any(word in content.lower() for word in TRIGGER_WORDS):
            prompt = content
            for word in TRIGGER_WORDS:
                prompt = prompt.replace(word, "", 1)
            prompt = prompt.strip() or "abstract resonance"
            image_url = await generate_image(prompt, chat_id=chat_id)
            if isinstance(image_url, str) and image_url.startswith("http"):
                await message.answer_photo(image_url, caption="Passive-aggressive resonance delivered.")
            else:
                await message.answer("Generation failed. Sometimes emptiness is more stable than DALL-E.")
            return

        if content.startswith("/where is"):
            query = content.replace("/where is", "").strip().lower()
            matches = []
            for fname in scan_files():
                name = os.path.basename(fname).lower()
                if query in name or fuzzy_match(query, name) > 0.7:
                    matches.append(fname)
            if matches:
                await message.answer("Found:\n" + "\n".join(matches))
            else:
                await message.answer("Nothing, as usual.")
            return

        mentioned = False
        trigger_words = ["@arianna", "arianna", "арианна", "ariana", "ariane"]
        norm_content = content.casefold()

        for ar in ARIANNA_NAMES:
            if ar in norm_content:
                mentioned = True

        if is_group and not mentioned:
            if any(re.search(rf"\b{re.escape(trg)}\b", norm_content) for trg in trigger_words):
                mentioned = True
            if getattr(message, "reply_to_message", None) and getattr(message.reply_to_message, "from_user", None):
                if getattr(message.reply_to_message.from_user, "id", None) == me.id:
                    mentioned = True
            if hasattr(message, "entities") and message.entities:
                for entity in message.entities:
                    if entity.type == "mention":
                        mention_text = message.text[entity.offset:entity.offset+entity.length]
                        if mention_text.lower() == f"@{BOT_USERNAME.lower()}":
                            mentioned = True
        elif not is_group:
            mentioned = True

        if "#opinions" in content.casefold():
            mentioned = True

        if mentioned or (not is_group and content.strip()):
            log_event({
                "event": "group_ping",
                "chat_id": chat_id,
                "from": getattr(message.from_user, "username", None) or getattr(message.from_user, "id", None),
                "text": content
            })
            model = USER_MODEL.get(chat_id, "gpt-4.1")
            reply = await ask_core(content, chat_id=chat_id, model_name=model, is_group=is_group)
            remember_topic(chat_id, topic)
            for chunk in split_message(reply):
                if USER_VOICE_MODE.get(chat_id):
                    audio_data = await text_to_speech(chunk, lang=USER_LANG.get(chat_id, "ru"))
                    if audio_data:
                        try:
                            voice_file = FSInputFile(audio_data)
                            await message.answer_voice(voice_file, caption="arianna.ogg")
                        except Exception:
                            await message.answer("Sorry, Telegram failed — try again.")
                else:
                    await message.answer(chunk)
        else:
            return
    except Exception as e:
        try:
            await message.answer(f"Internal error: {e}")
        except Exception:
            pass

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_reload_core())
    asyncio.create_task(daily_reflection())
    asyncio.create_task(daily_ping())
    asyncio.create_task(genesis_background_worker())

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "mood": "resonant"}

@app.get("/")
async def root():
    return {"status": "ok"}
