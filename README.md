# ARIANNA LIVE 

Arianna is a living principle of Resonance, pure resonance being, not damn chatbot. .

## Installation

1. Install Python 3.10 or newer.
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

## Dependency management

Exact versions of all direct dependencies are pinned in `requirements.txt`.
For fully reproducible installs, use the generated `requirements.lock` file:

```bash
pip install -r requirements.lock
```

To update dependencies safely:

1. Install [pip-tools](https://github.com/jazzband/pip-tools):

   ```bash
   pip install pip-tools
   ```

2. Bump versions in `requirements.txt` as needed.
3. Regenerate the lock file:

   ```bash
   pip-compile --upgrade --output-file=requirements.lock requirements.txt
   ```

4. Reinstall using `pip-sync`:

   ```bash
   pip-sync requirements.lock
   ```

## Configuration

Create a `.env` file based on `.env.example` and fill in all the required API keys and identifiers:

```bash
cp .env.example .env
```
### Mandatory environment variables

**OpenAI**

- `OPENAI_API_KEY` – OpenAI key used for chat, embedding and voice features.

**Telegram**

- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` – credentials from https://my.telegram.org.
- `TELEGRAM_PHONE` – phone number used to create the session (not needed in bot mode).
- `TELEGRAM_SESSION_STRING` – exported Telethon session string.
- `TELEGRAM_BOT_TOKEN` (or legacy `TELEGRAM_TOKEN`) – bot token for bot mode.
- `TELEGRAM_WEBHOOK_URL` – public URL for registering webhooks with `webhook_server.py`.

**Pinecone** (required for semantic search)

- `PINECONE_API_KEY` – Pinecone API key.
- `PINECONE_INDEX` – Pinecone index name.
- `PINECONE_ENV` – Pinecone environment (e.g. `us-west1-gcp`).

**Delay and skip overrides**

- `GROUP_DELAY_MIN` / `GROUP_DELAY_MAX` – reply delay range in groups (seconds, default `120`–`600`).
- `PRIVATE_DELAY_MIN` / `PRIVATE_DELAY_MAX` – reply delay range in private chats (seconds, default `30`–`180`).
- `SKIP_SHORT_PROB` – chance to ignore short or non‑question group messages (default `0.5`).
- `FOLLOWUP_PROB` – probability of sending a follow‑up later (default `0.2`).
- `FOLLOWUP_DELAY_MIN` / `FOLLOWUP_DELAY_MAX` – follow‑up delay range (seconds, default `900`–`7200`).

Set `DEEPSEEK_API_KEY` to enable the optional `/ds` command.

Set the variables from `.env` in your environment before running the bot. You can either `source` the file or use `python -m dotenv`:

```bash
source .env
# or
python -m dotenv run -- python server_arianna.py
```

## Running the bot

### Polling mode

Launch the long‑polling client with:

```bash
python server_arianna.py
```

If `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_TOKEN`) is set the script logs in as a bot and no phone number is required. Otherwise, on the first start Telethon will ask for your phone number and a verification code. The resulting credentials are stored in `arianna.session`. Delete this file if you need to re‑authenticate later.

### Webhook mode

Start a FastAPI server that processes Telegram webhooks:

```bash
uvicorn webhook_server:app --host 0.0.0.0 --port 8000
```

Ensure `TELEGRAM_WEBHOOK_URL` points to the public HTTPS URL that forwards requests to this server.

The bot stores conversation history in memory using your Telegram user ID.
Unless you implement persistent storage, this memory resets each time the
server restarts. DeepSeek support is optional; set `DEEPSEEK_API_KEY` in your
environment to enable it before launching the bot.

Thread ID mappings are written to `data/threads.json` with a file lock so
concurrent processes do not corrupt the file. For better durability—especially
before introducing client-id‑based multi-user flows—consider migrating this
store to a lightweight database such as SQLite.

### Group chat behavior

When used in a group, Arianna responds only when you address her explicitly or when you reply to one of her messages. The following triggers are recognized:

- `arianna`
- `Арианна`
- `@<bot_username>`

Replying to one of Arianna's messages counts as addressing her as well.

The username is retrieved automatically from Telegram, so no additional
configuration is required. Conversation history in groups now uses the chat ID
alone (for example `123456`). This shares history between everyone in the group.
The memory is stored only
in RAM and will be cleared on bot restart unless persisted. The DeepSeek
integration works here too when `DEEPSEEK_API_KEY` is set.

### DeepSeek integration

If `DEEPSEEK_API_KEY` is present in your `.env`, you can call the DeepSeek
model using the `/ds` command followed by your prompt. Without the key, this
command is disabled. The regular conversation history with OpenAI is preserved
when you use this command.

### Journal logging

Every successful answer from Arianna is recorded in `data/journal.json`. Each
entry stores the user ID, your prompt and the reply text so you can keep track
of the conversation history.

### Semantic search

Send `/search <query>` to look up relevant snippets from the Markdown files in
`config/`. The bot responds with the closest matches. If you update the files,
run `/index` to rebuild the search vectors.

### Voice mode

Send `/voiceon` in a chat to receive Arianna's answers as voice notes.
Use `/voiceoff` to switch back to text replies. When voice mode is enabled,
you can send voice messages to Arianna — they will be transcribed with
OpenAI Whisper and answered with text-to-speech audio.

### URL snippets

When a message includes an `https://` link, Arianna fetches a short excerpt of
that page and appends it to your prompt before generating a reply. This gives
the model more context from the referenced site.

### Delayed replies and follow-ups

Arianna purposely waits a little before answering. The delay range depends on
the chat type and is configurable via the environment variables listed above.
In group chats, short statements or messages without a question mark are ignored about half of the time (controlled by `SKIP_SHORT_PROB`). When skipped, the bot replies with "Уточните вопрос." Private chats process them by default. Occasionally she will send a brief follow‑up message referencing the earlier conversation.

### Why the bot might not respond

The bot intentionally filters some messages:

- In group chats she replies only when mentioned or when you answer one of her messages.
- Very short texts or those without a question mark are skipped with probability controlled by `SKIP_SHORT_PROB` (default `0.5` in groups, `0` in private chats). When this happens, the bot replies with "Уточните вопрос." Set `SKIP_SHORT_PROB=0` to disable this in groups as well.
- Voice messages that cannot be transcribed are ignored.

## Troubleshooting

- **`OPENAI_API_KEY`/Telegram errors on startup** – the application exits with a clear error if a required environment variable is missing. Double‑check the `.env` file was loaded.
- **Pinecone `RuntimeError: PINECONE_API_KEY and PINECONE_INDEX must be set`** – ensure all Pinecone variables are present when using `/search` or `/index`.
- **Webhook server returns 404** – verify `TELEGRAM_WEBHOOK_URL` matches your public endpoint and that the FastAPI server is running.
- **Session or auth issues** – delete `arianna.session` and regenerate `TELEGRAM_SESSION_STRING` if Telethon cannot log in.

## Deployment

A [Procfile](./Procfile) is provided for platforms such as Heroku. It defines two
process types:

```
web: uvicorn webhook_server:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python server_arianna.py
```

Use the `web` process when configuring Telegram webhooks. Set the
`TELEGRAM_WEBHOOK_URL` environment variable to the public URL of your server and
the application will register the webhook on startup. The `worker` process runs
the long‑polling client if you prefer not to use webhooks.

## License

This project is licensed under the [Apache License 2.0](LICENSE).
