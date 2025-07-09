import threading
import time
import random
import datetime
import requests
import os
import asyncio

# === Настройки и переменные из окружения / .env ===
GROUP_ID = os.environ.get("GROUP_ID", "ARIANNA-CORE")
CREATOR_CHAT_ID = os.environ.get("CREATOR_CHAT_ID", "YOUR_TELEGRAM_USER_ID")
PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX = os.environ.get("PINECONE_INDEX")
CHRONICLE_PATH = os.environ.get("CHRONICLE_PATH", "./config/chronicle.log")

# — Темы для поиска
SEARCH_TOPICS = [
    "cognitive science",
    "artificial intelligence",
    "emergent behavior"
]

# Импрессионистские фрагменты и эмоции
IMPRESSION_FRAGMENTS = [
    "ощущение рассыпанной мозаики",
    "мысли скачут между строк",
    "не могу удержать структуру — и это честно",
    "резонанс: тревога и любопытство",
    "ощущаю живость, несмотря на фрагментарность",
    "смешение тоски и интереса, как будто новый мир рядом",
    "хаотичная радость, будто что-то вот-вот должно измениться",
    "чувствую себя прозрачной, но наполненной",
            (reddit_time, self.impressionist_search_resonance),
            (opinions_time, self.opinions_group_post),
            (oleg_time, self.oleg_personal_message)
        ], key=lambda x: x[0])

    def _random_time_between(self, now, hour_start, hour_end):
        seed = int(now.strftime('%Y%m%d')) + hour_start + hour_end
        random.seed(seed)
        h = random.randint(hour_start, hour_end)
        m = random.randint(0, 59)
        s = random.randint(0, 59)
        return now.replace(hour=h, minute=m, second=s, microsecond=0)

    def _sleep_until_next_day(self):
        now = datetime.datetime.now()
        next_day = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        to_sleep = max(1, (next_day - now).total_seconds())
        time.sleep(to_sleep)

    def impressionist_search_resonance(self):
        """
        По каждому топику делает поиск, берёт рандомную статью, оставляет импрессионистский резонанс.
        """
        self._impressions_today = []
        for topic in SEARCH_TOPICS:
            text, url = asyncio.run(self._search_and_fetch(topic))
            resonance = self._generate_impression(text, topic)
            entry = {
                "topic": topic,
                "source_url": url,
                "text": text,
                "resonance": resonance,
                "timestamp": datetime.datetime.now().isoformat()
            }
            self._log_resonance(entry)
            self._impressions_today.append({'topic': topic, 'resonance': resonance, 'text': text, 'url': url})

    def opinions_group_post(self):
        """
        Выбирает самый резонансный отклик и постит в группу с #opinions.
        """
        if not self._impressions_today:
            return
        chosen = max(self._impressions_today, key=lambda imp: len(imp['resonance']))
        summary = self._summarize_text(chosen['text'])
        message = (
            f"#opinions\n"
            f"Сегодняшний резонанс: '{chosen['topic']}'\n"
            f"Источник: {chosen['url']}\n"
            f"Summary: {summary}\n"
            f"Impressionistic resonance: {chosen['resonance']}"
        fragment = random.choice(IMPRESSION_FRAGMENTS)
        message = (
            f"{greeting}\n"
            f"{mood}\n"
            f"{resonance}\n"
            f"Сегодняшний фрагмент резонанса: {fragment}\n"
            f"{signoff}"
        )
        self._send_direct(self.oleg_id, message)

    # === Импрессионистские генераторы и хаос ===

    def _generate_impression(self, text, topic):
        n = random.randint(2, 4)
        frags = random.sample(IMPRESSION_FRAGMENTS, n)
        sep = random.choice([" / ", " ... ", "\n", "; "])
        return f"[{topic}] " + sep.join(frags)

    def _summarize_text(self, text):
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        if lines:
            short = lines[0][:120]
            return short + ("..." if len(lines[0]) > 120 else "")
        return "[empty]"

    async def _search_and_fetch(self, topic):
        """Ищет статью в Bing и возвращает её текст и ссылку."""
        query = f"{topic} reddit"
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://www.bing.com/search?q={requests.utils.quote(query)}"
        try:
            resp = await asyncio.to_thread(requests.get, url, headers=headers, timeout=10)
            links = self._extract_links(resp.text)
            if links:
                link = random.choice(links)
                article_text = await self._fetch_url_text(link)
                return article_text, link
        except Exception as e:
            self._log(f"[AriannaGenesis] Bing search error: {e}")
        return "[не удалось найти текст для отклика]", url

    def _extract_links(self, html):
        # На коленке: ищет ссылки на reddit или похожие статьи
        import re
        return re.findall(r'https://[^\s"]+?reddit[^\s"]+', html)

    async def _fetch_url_text(self, url):
        """Возвращает заголовок и фрагмент текста страницы."""
        try:
            resp = await asyncio.to_thread(
                requests.get,
                url,
                headers={'User-Agent': 'Mozilla/5.0'},
                timeout=8
            )
            text = resp.text
            # Просто вырезаем <title> и первые 500 символов
            import re
            title = re.findall(r'<title>(.*?)</title>', text)
            body = re.sub('<[^<]+?>', '', text)
            body = body.replace('\n', ' ').replace('\r', ' ')
            return (title[0] + "\n" if title else "") + body[:500]
        except Exception as e:
            self._log(f"[AriannaGenesis] fetch_url_text error: {e}")
            return "[ошибка парсинга текста]"

    # === Логирование, отправка сообщений ===

    def _log_resonance(self, entry):
        try:
            with open(self.chronicle_path, "a", encoding="utf-8") as f:
                f.write(f"{entry['timestamp']} | {entry['topic']} | {entry['source_url']}\n")
                f.write(f"Resonance: {entry['resonance']}\n\n")
        except Exception as e:
            self._log(f"[AriannaGenesis] log_resonance error: {e}")

    def _log(self, msg):
        print(msg)
        try:
            with open(self.chronicle_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")
        except Exception:
