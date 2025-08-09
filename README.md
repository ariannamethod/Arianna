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

Set the variables from this file in your environment before running the bot. You can either `source` the file or use `python -m dotenv`:

```bash
source .env
# or
python -m dotenv run -- python server_arianna.py
```

Important variables include `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`, `TELEGRAM_SESSION_STRING`, `OPENAI_API_KEY`, and `DEEPSEEK_API_KEY`. These must all be provided in the environment; the application will exit if any are missing. Set `TELEGRAM_BOT_TOKEN` (or legacy `TELEGRAM_TOKEN`) to run the client in bot mode. Pinecone settings (`PINECONE_API_KEY`, `PINECONE_INDEX`, `PINECONE_ENV`) are also required if you use semantic search.
Several optional variables fine‑tune the bot's behavior:

- `GROUP_DELAY_MIN`/`GROUP_DELAY_MAX` – range in seconds to wait before replying in groups (default 120–600).
- `PRIVATE_DELAY_MIN`/`PRIVATE_DELAY_MAX` – range for private chats (default 30–180).
- `SKIP_SHORT_PROB` – chance to ignore very short or non‑question messages (default 0.5; set to 0 to disable).
- `FOLLOWUP_PROB` – probability of sending a follow‑up later (default 0.2).
- `FOLLOWUP_DELAY_MIN`/`FOLLOWUP_DELAY_MAX` – delay range for follow‑ups in seconds (default 900–7200).

## Running the bot

Run the Telegram client with:

```bash
python server_arianna.py
```

If `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_TOKEN`) is set the script logs in as a bot and no phone number is required. Otherwise, on the first start Telethon will ask for your phone number and a verification code. The resulting credentials are stored in `arianna.session`. Delete this file if you need to re-authenticate later.

The bot stores conversation history in memory using your Telegram user ID.
Unless you implement persistent storage, this memory resets each time the
server restarts. Set `DEEPSEEK_API_KEY` in your environment to activate the
DeepSeek integration before launching the bot.

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
integration works here too if `DEEPSEEK_API_KEY` is set.

### DeepSeek integration

Set `DEEPSEEK_API_KEY` in your `.env` to enable calls to the DeepSeek model.
Use the `/ds` command followed by your prompt to send a message through
DeepSeek. If no key is configured, this command is disabled. The regular
conversation history with OpenAI is preserved when you use this command.

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
Short statements or messages without a question mark are ignored about half of
the time. Occasionally she will send a brief follow‑up message referencing the
earlier conversation.

### Why the bot might not respond

The bot intentionally filters some messages:

- In group chats she replies only when mentioned or when you answer one of her messages.
- Very short texts or those without a question mark are skipped with probability controlled by `SKIP_SHORT_PROB` (default `0.5`).
  Set `SKIP_SHORT_PROB=0` to disable this random skipping.
- Voice messages that cannot be transcribed are ignored.

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
