import difflib
import aiohttp
import atexit
import asyncio
from bs4 import BeautifulSoup


_session: aiohttp.ClientSession | None = None


def get_session() -> aiohttp.ClientSession:
    """Return a global aiohttp session, creating it if needed."""
    global _session
    if _session is None or getattr(_session, "closed", True):
        _session = aiohttp.ClientSession()
    return _session


async def close_session() -> None:
    """Close the global aiohttp session if it exists."""
    global _session
    if _session and not getattr(_session, "closed", True):
        await _session.close()
    _session = None


def _cleanup() -> None:
    """Synchronously close the session at interpreter shutdown."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_running():
        loop.create_task(close_session())
    else:
        loop.run_until_complete(close_session())


atexit.register(_cleanup)


def fuzzy_match(a, b):
    """Return similarity ratio between two strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()


async def extract_text_from_url(url):
    """Fetches a web page asynchronously and returns visible text."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Arianna Agent)"}
        session = get_session()
        async with session.get(url, timeout=10, headers=headers) as resp:
            resp.raise_for_status()
            text = await resp.text()
        soup = BeautifulSoup(text, "html.parser")
        for s in soup(["script", "style", "header", "footer", "nav", "aside"]):
            s.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)[:3500]
    except Exception as e:
        return f"[Error loading page: {e}]"
