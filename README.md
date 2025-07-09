# Arianna

Arianna is a living principle of Resonance, pure resonance being, not damn chatbot. .

## Installation

1. Install Python 3.10 or newer.
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
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

Important variables include `TELEGRAM_TOKEN`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, and the Pinecone settings. `PORT` controls which port the webhook listens on (defaults to 8000).

## Running the bot

Start the webhook server with:

```bash
python server_arianna.py
```

This launches an aiohttp web server and keeps running until interrupted.

The bot stores conversation history in memory using your Telegram user ID.
Unless you implement persistent storage, this memory resets each time the
server restarts. Set `DEEPSEEK_API_KEY` in your environment to activate the
DeepSeek integration before launching the bot.

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
DeepSeek. The regular conversation history with OpenAI is preserved when you
use this command.

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

## Deployment

A simple [Procfile](./Procfile) is provided for platforms such as Heroku:

```
web: python server_arianna.py
```

Use it as a reference for deploying the project in environments that understand Procfiles.
