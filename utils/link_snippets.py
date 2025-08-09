"""Utility for appending web page snippets to messages containing links."""

import os
import re
import asyncio

from utils.text_helpers import extract_text_from_url


URL_REGEX = re.compile(r"https://\S+")
URL_FETCH_TIMEOUT = int(os.getenv("URL_FETCH_TIMEOUT", 10))


async def append_link_snippets(text: str) -> str:
    """Append snippet from any https:// link in the given text.

    For each URL found in *text*, fetch the page content and append a short
    snippet to the original message. Errors while fetching are reported inline.
    """

    urls = URL_REGEX.findall(text)
    if not urls:
        return text

    tasks = [asyncio.wait_for(extract_text_from_url(url), URL_FETCH_TIMEOUT) for url in urls]
    snippets = await asyncio.gather(*tasks, return_exceptions=True)

    parts = [text]
    for url, snippet in zip(urls, snippets):
        snippet_text = (
            f"[Error loading page: {snippet}]" if isinstance(snippet, Exception) else snippet
        )
        parts.append(f"\n[Snippet from {url}]\n{snippet_text[:500]}")

    return "\n".join(parts)


__all__ = ["append_link_snippets"]

