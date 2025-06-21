import os
import aiohttp

# You can add multiple keys for rotation if needed
DEEPSEEK_KEYS = [os.getenv("DEEPSEEK_API_KEY")]
current_key_idx = 0

def rotate_deepseek_key():
    """Rotate to the next DeepSeek API key (for use if multiple keys are provided)."""
    global current_key_idx
    current_key_idx = (current_key_idx + 1) % len(DEEPSEEK_KEYS)
    return DEEPSEEK_KEYS[current_key_idx]

async def call_deepseek(messages):
    """
    Send chat messages to DeepSeek API and return the response content.
    Automatically rotates key on 401 Unauthorized.
    """
    global current_key_idx
    key = DEEPSEEK_KEYS[current_key_idx]
    url = "https://api.deepseek.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": 0.45,
        "max_tokens": 700
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
            try:
                data = await resp.json()
            except Exception:
                data = {}
            if resp.status == 401:
                rotate_deepseek_key()
                return None
            if resp.status != 200:
                return None
            if "choices" in data and data["choices"]:
                reply = data["choices"][0]["message"]["content"].strip()
                if not reply:
                    return None
                return reply
            return None
