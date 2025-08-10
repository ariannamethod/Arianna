import json
import logging

from utils import journal


def test_log_event_appends_event(tmp_path, monkeypatch):
    log_path = tmp_path / "journal.json"
    monkeypatch.setattr(journal, "LOG_PATH", str(log_path))

    journal.log_event({"action": "test"})

    with open(log_path, "r", encoding="utf-8") as f:
        data = [json.loads(line) for line in f if line.strip()]

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


def test_log_event_rotates_on_size(tmp_path, monkeypatch):
    log_path = tmp_path / "journal.json"
    monkeypatch.setattr(journal, "LOG_PATH", str(log_path))
    monkeypatch.setattr(journal, "MAX_LOG_SIZE", 10)

    journal.log_event({"n": 1})
    journal.log_event({"n": 2})

    files = list(tmp_path.glob("journal.json*"))
    assert len(files) == 2

    rotated = [f for f in files if f.name != "journal.json"][0]
    with open(rotated, "r", encoding="utf-8") as f:
        first = [json.loads(line) for line in f if line.strip()][0]
    with open(log_path, "r", encoding="utf-8") as f:
        second = [json.loads(line) for line in f if line.strip()][0]

    assert first["n"] == 1
    assert second["n"] == 2

