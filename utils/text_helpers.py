import difflib
import asyncio
import ipaddress
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup


def fuzzy_match(a, b):
    """Return similarity ratio between two strings."""
    return difflib.SequenceMatcher(None, a, b).ratio()


BLOCKED_DOMAINS_DEFAULT = {"localhost"}
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


async def extract_text_from_url(
    url, allowed_domains=None, blocked_domains=None
):
    """Fetches a web page asynchronously and returns visible text."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return "[Error loading page: Invalid URL scheme]"

        host = parsed.hostname
        if not host:
            return "[Error loading page: Invalid hostname]"

        allowed = set(allowed_domains or [])
        blocked = set(blocked_domains or []) | BLOCKED_DOMAINS_DEFAULT

        if allowed and host not in allowed:
            return f"[Error loading page: Domain '{host}' not allowed]"
        if host in blocked:
            return f"[Error loading page: Domain '{host}' is blocked]"

        try:
            ip = ipaddress.ip_address(host)
            ip_addresses = [ip]
        except ValueError:
            loop = asyncio.get_running_loop()
            addrinfos = await loop.getaddrinfo(host, None)
            ip_addresses = [ipaddress.ip_address(a[4][0]) for a in addrinfos]

        for ip in ip_addresses:
            for net in BLOCKED_IP_RANGES:
                if ip in net:
                    return "[Error loading page: IP address not allowed]"

        headers = {"User-Agent": "Mozilla/5.0 (Arianna Agent)"}
        async with aiohttp.ClientSession() as session:
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
