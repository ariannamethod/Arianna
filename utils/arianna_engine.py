import os
import asyncio
import httpx
import logging
from utils.genesis_tool import genesis_tool_schema, handle_genesis_call
from utils.thread_store import load_threads, save_threads

class AriannaEngine:
    """
    Обёртка Assistants API для Арианны:
    — хранит память в threads,
    — запускает ассистента с её системным промптом и Genesis-функцией.
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.openai_key = os.getenv("OPENAI_API_KEY")
        self.headers    = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2"
        }
        self.assistant_id = None
        self.threads      = load_threads()  # user_id → thread_id

    async def setup_assistant(self):
        """
        Создаёт ассистента Арианны и подключает функцию GENESIS.
        """
        system_prompt = self._load_system_prompt()
        schema = genesis_tool_schema()  # схема функции GENESIS

        payload = {
            "name":        "Arianna-Core-Assistant",
            "instructions": system_prompt,
            "model":       "gpt-4.1",      # мощное ядро по твоему желанию
            "tools":       [schema],
            "tool_resources": {}
        }

        async with httpx.AsyncClient() as client:
            try:
                r = await client.post(
                    "https://api.openai.com/v1/assistants",
                    headers=self.headers,
                    json=payload
                )
                r.raise_for_status()
            except Exception as e:
                self.logger.error("Failed to create Arianna Assistant", exc_info=e)
                return f"Failed to create Arianna Assistant: {e}"

            self.assistant_id = r.json()["id"]
            self.logger.info(f"✅ Arianna Assistant created: {self.assistant_id}")
        return self.assistant_id

    def _load_system_prompt(self) -> str:
        # Берём тот же протокол из utils/prompt.py
        from utils.prompt import build_system_prompt
        is_group = os.getenv("IS_GROUP", "False").lower() == "true"
        return build_system_prompt(
            AGENT_NAME="ARIANNA-ANCHOR",
            is_group=is_group
        )

    async def _get_thread(self, user_id: str, force_new: bool = False) -> str:
        if force_new or user_id not in self.threads:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    "https://api.openai.com/v1/threads",
                    headers=self.headers,
                    json={"metadata": {"user_id": user_id}}
                )
                r.raise_for_status()
                self.threads[user_id] = r.json()["id"]
                save_threads(self.threads)
        return self.threads[user_id]

    async def ask(self, user_id: str, prompt: str, is_group: bool=False) -> str:
        """
        Кладёт prompt в thread, запускает run, ждёт и возвращает ответ.
        Если ассистент запрашивает GENESIS-функцию — обрабатываем через handle_genesis_call().
        """
        tid = await self._get_thread(user_id)

        # Добавляем пользовательский запрос
        async with httpx.AsyncClient() as client:
            try:
                msg = await client.post(
                    f"https://api.openai.com/v1/threads/{tid}/messages",
                    headers=self.headers,
                    json={"role": "user", "content": prompt, "metadata": {"is_group": str(is_group)}}
                )
                msg.raise_for_status()
            except httpx.HTTPStatusError as e:
                # Возможно thread устарел – создаём новый и пробуем снова
                self.logger.warning("POST /messages failed, retrying with new thread", exc_info=e)
                self.threads.pop(user_id, None)
                tid = await self._get_thread(user_id, force_new=True)
                msg = await client.post(
                    f"https://api.openai.com/v1/threads/{tid}/messages",
                    headers=self.headers,
                    json={"role": "user", "content": prompt, "metadata": {"is_group": str(is_group)}}
                )
                msg.raise_for_status()
            except Exception as e:
                self.logger.error("Failed to post user message", exc_info=e)
                raise

            # Запускаем ассистента
            run = await client.post(
                f"https://api.openai.com/v1/threads/{tid}/runs",
                headers=self.headers,
                json={"assistant_id": self.assistant_id}
            )
            run.raise_for_status()
            run_id = run.json()["id"]

            # Polling
            while True:
                await asyncio.sleep(0.5)
                st = await client.get(
                    f"https://api.openai.com/v1/threads/{tid}/runs/{run_id}",
                    headers=self.headers
                )
                run_json = st.json()
                status = run_json["status"]
                if status == "requires_action":
                    tool_calls = run_json.get("required_action", {}) \
                        .get("submit_tool_outputs", {}) \
                        .get("tool_calls", [])
                    if tool_calls:
                        output = await handle_genesis_call(tool_calls)
                        await client.post(
                            f"https://api.openai.com/v1/threads/{tid}/runs/{run_id}/submit_tool_outputs",
                            headers=self.headers,
                            json={"tool_outputs": [{
                                "tool_call_id": tool_calls[0]["id"],
                                "output": output
                            }]}
                        )
                    continue
                if status == "completed":
                    break

            # Получаем все tool_calls (если есть) и обычный контент
            final = await client.get(
                f"https://api.openai.com/v1/threads/{tid}/messages",
                headers=self.headers
            )
            msg = final.json()["data"][0]
            # Если ассистент вызвал функцию GENESIS:
            if msg.get("tool_calls"):
                return await handle_genesis_call(msg["tool_calls"])
            return msg["content"][0]["text"]["value"]

