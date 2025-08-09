import aiohttp
import pytest

from utils.text_helpers import extract_text_from_url


class MockResponse:
    def __init__(self, text):
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def text(self):
        return self._text

    def raise_for_status(self):
        pass


class MockSession:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def get(self, url, timeout, headers):
        return self._response


@pytest.mark.asyncio
async def test_extract_text_from_url_success(monkeypatch):
    html = (
        "<html><body><script>ignore()</script><p>Hello</p>"
        "<style>.a{}</style></body></html>"
    )
    response = MockResponse(html)
    monkeypatch.setattr(
        aiohttp, "ClientSession", lambda: MockSession(response)
    )
    text = await extract_text_from_url("http://example.com")
    assert text == "Hello"


@pytest.mark.asyncio
async def test_extract_text_from_url_error(monkeypatch):
    class FailingSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        def get(self, url, timeout, headers):
            raise Exception("boom")

    monkeypatch.setattr(aiohttp, "ClientSession", lambda: FailingSession())
    text = await extract_text_from_url("http://example.com")
    assert text.startswith("[Error loading page:")
