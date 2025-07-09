import difflib
import requests
import aiohttp
from bs4 import BeautifulSoup

def fuzzy_match(a, b):
    """Return similarity ratio between two strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()

def extract_text_from_url(url):
    """
    Extract visible text from a web page at the given URL.
    Returns the first 3500 characters of joined lines.
    """
async def extract_text_from_url(url):
    """Fetches a web page asynchronously and returns visible text."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Arianna Agent)"}
        resp = requests.get(url, timeout=10, headers=headers)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove non-content elements
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10, headers=headers) as resp:
                resp.raise_for_status()
                text = await resp.text()
        soup = BeautifulSoup(text, "html.parser")
        for s in soup(["script", "style", "header", "footer", "nav", "aside"]):
            s.decompose()
        text = soup.get_text(separator="\n")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        result = "\n".join(lines)[:3500]
        return result
        visible = soup.get_text(separator="\n")
        lines = [line.strip() for line in visible.splitlines() if line.strip()]
        return "\n".join(lines)[:3500]
    except Exception as e:
        return f"[Error loading page: {e}]"
