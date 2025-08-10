import asyncio
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
    loop = asyncio.get_event_loop()

    async def fake_getaddrinfo(host, port):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
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
    loop = asyncio.get_event_loop()

    async def fake_getaddrinfo(host, port):
        return [(None, None, None, None, ("93.184.216.34", 0))]

    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    text = await extract_text_from_url("http://example.com")
    assert text.startswith("[Error loading page:")


class DummySession:
    async def __aenter__(self):
        raise AssertionError("should not be called")

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def get(self, url, timeout, headers):
        raise AssertionError("should not be called")


@pytest.mark.asyncio
async def test_extract_text_from_url_invalid_scheme(monkeypatch):
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: DummySession())
    text = await extract_text_from_url("ftp://example.com")
    assert text.startswith("[Error loading page:")


@pytest.mark.asyncio
async def test_extract_text_from_url_domain_not_allowed(monkeypatch):
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: DummySession())
    text = await extract_text_from_url(
        "http://example.com", allowed_domains={"allowed.com"}
    )
    assert text.startswith("[Error loading page:")


@pytest.mark.asyncio
async def test_extract_text_from_url_blacklisted_domain(monkeypatch):
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: DummySession())
    text = await extract_text_from_url(
        "http://bad.com", blocked_domains={"bad.com"}
    )
    assert text.startswith("[Error loading page:")


@pytest.mark.asyncio
async def test_extract_text_from_url_blocked_ip(monkeypatch):
    monkeypatch.setattr(aiohttp, "ClientSession", lambda: DummySession())
    text = await extract_text_from_url("http://127.0.0.1")
    assert text.startswith("[Error loading page:")
