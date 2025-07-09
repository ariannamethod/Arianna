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

### Group chat behavior

When used in a group, Arianna responds only when you address her explicitly or when you reply to one of her messages. The following triggers are recognized:

- `arianna`
- `Арианна`
- `@<bot_username>`

The username is retrieved automatically from Telegram, so no additional
configuration is required.

## Deployment

A simple [Procfile](./Procfile) is provided for platforms such as Heroku:

```
web: python server_arianna.py
```

Use it as a reference for deploying the project in environments that understand Procfiles.
