import datetime
from utils.thread_store_sqlite import (
    save_message,
    get_messages_by_date,
    search_messages_by_embedding,
    save_snapshot,
    get_snapshots_by_date,
)


def epoch(date_str: str) -> int:
    return int(datetime.datetime.strptime(date_str, "%Y-%m-%d").timestamp())


def test_message_store_and_query(tmp_path):
    db = tmp_path / "threads.sqlite"
    save_message("t1", "user", "hello", [1.0, 0.0], created_at=epoch("2024-01-01"), db_path=str(db))
    save_message("t1", "assistant", "world", [0.0, 1.0], created_at=epoch("2024-01-01"), db_path=str(db))
    save_message("t2", "user", "later", [0.5, 0.5], created_at=epoch("2024-01-02"), db_path=str(db))

    day_msgs = get_messages_by_date("2024-01-01", db_path=str(db))
    assert len(day_msgs) == 2
    assert day_msgs[0]["content"] == "hello"

    res = search_messages_by_embedding([1.0, 0.0], top_k=1, db_path=str(db))
    assert res[0]["content"] == "hello"


def test_snapshot_store_and_query(tmp_path):
    db = tmp_path / "threads.sqlite"
    save_snapshot("2024-01-01", "snapshot1", created_at=epoch("2024-01-01"), db_path=str(db))
    save_snapshot("2024-01-02", "snapshot2", created_at=epoch("2024-01-02"), db_path=str(db))

    snaps = get_snapshots_by_date("2024-01-01", db_path=str(db))
    assert len(snaps) == 1
    assert snaps[0]["summary"] == "snapshot1"
