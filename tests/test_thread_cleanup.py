import time

from utils.arianna_engine import AriannaEngine


def test_cleanup_threads(monkeypatch):
    """Older threads should be removed and saved."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    # Avoid touching real storage
    monkeypatch.setattr("utils.arianna_engine.load_threads", lambda: {})
    saved = {}

    def fake_save(data):
        saved.update(data)

    monkeypatch.setattr("utils.arianna_engine.save_threads", fake_save)

    engine = AriannaEngine()
    now = int(time.time())
    engine.threads = {
        "recent": {"thread_id": "t1", "last_access": now},
        "old": {"thread_id": "t2", "last_access": now - 40 * 86400},
    }

    engine.cleanup_threads(max_age_days=30)

    assert "old" not in engine.threads
    assert "recent" in engine.threads
    assert saved == engine.threads
