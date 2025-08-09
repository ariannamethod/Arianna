import json
import logging

from utils import journal


def test_log_event_appends_event(tmp_path, monkeypatch):
    log_path = tmp_path / "journal.json"
    monkeypatch.setattr(journal, "LOG_PATH", str(log_path))

    journal.log_event({"action": "test"})

    with open(log_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert data[0]["action"] == "test"
    assert "ts" in data[0]


def test_log_event_logs_exception_on_failure(monkeypatch, caplog, tmp_path):
    log_path = tmp_path / "journal.json"
    monkeypatch.setattr(journal, "LOG_PATH", str(log_path))

    def fail_open(*args, **kwargs):
        raise OSError("fail")

    monkeypatch.setattr(journal, "open", fail_open, raising=False)

    caplog.set_level(logging.ERROR, logger="journal")
    journal.log_event({"action": "fail"})

    assert any(
        "Error writing log event" in record.message and record.levelno == logging.ERROR
        for record in caplog.records
    )

