import os
import asyncio
import httpx
from glob import glob
from openai import AsyncOpenAI

class AriannaEngine:
    def __init__(self):
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }
        self.assistant_id = None
        self.threads = {}
        self.client = AsyncOpenAI(api_key=self.openai_key)

    async def setup_assistant(self):
        system_prompt = self._load_system_prompt()
        schema = genesis_tool_schema()
        payload = {
            "name": "Arianna-Core-Assistant",
            "instructions": system_prompt,
            "model": "gpt-4.1",
            "tools": [schema],
            "tool_resources": {}
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(
                "https://api.openai.com/v1/assistants",
                headers=self.headers,
                json=payload
            )
            r.raise_for_status()
            self.assistant_id = r.json()["id"]
            print(f"✅ Arianna Assistant created: {self.assistant_id}")

    def _load_system_prompt(self) -> str:
        from utils.prompt import build_system_prompt
        return build_system_prompt(
            AGENT_NAME="ARIANNA-ANCHOR",
            is_group=True
        )

    async def _get_thread(self, user_id: str) -> str:
        if user_id not in self.threads:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.openai.com/v1/threads",
                    headers=self.headers,
                    json={"metadata": {"user_id": user_id}}
                )
                r.raise_for_status()
                self.threads[user_id] = r.json()["id"]
        return self.threads[user_id]

    async def ask(self, user_id: str, prompt: str, is_group: bool=False) -> str:
        tid = await self._get_thread(user_id)
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.openai.com/v1/threads/{tid}/messages",
                headers=self.headers,
                json={"role": "user", "content": prompt, "metadata": {"is_group": is_group}}
            )
            run = await client.post(
                f"https://api.openai.com/v1/threads/{tid}/runs",
                headers=self.headers,
                json={"assistant_id": self.assistant_id}
            )
            run.raise_for_status()
            run_id = run.json()["id"]
            while True:
                await asyncio.sleep(0.5)
                st = await client.get(
                    f"https://api.openai.com/v1/threads/{tid}/runs/{run_id}",
                    headers=self.headers
                )
                status = st.json()["status"]
                if status == "completed":
                    break
            final = await client.get(
                f"https://api.openai.com/v1/threads/{tid}/messages",
                headers=self.headers
            )
            msg = final.json()["data"][0]
            if msg.get("tool_calls"):
                return await handle_genesis_call(msg["tool_calls"])
            return msg["content"][0]["text"]["value"]

    async def text_to_speech(self, text: str, lang: str = "ru") -> str:
        try:
            voice = "nova" if lang == "en" else "fable"
            resp = await self.client.audio.speech.create(
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

    @staticmethod
    def split_message(text: str, max_len: int = 4000):
        parts = []
        while len(text) > max_len:
            idx = text.rfind("\n", 0, max_len)
            if idx < 0: idx = max_len
            parts.append(text[:idx])
            text = text[idx:].lstrip("\n")
        parts.append(text)
        return parts
