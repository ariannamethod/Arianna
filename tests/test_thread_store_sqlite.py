import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from utils.thread_store_sqlite import save_threads, load_threads  # noqa: E402


def test_save_threads_preserves_existing(tmp_path):
    db_path = tmp_path / "threads.sqlite"
    save_threads({"u1": "t1"}, str(db_path))
    save_threads({"u2": "t2"}, str(db_path))
    threads = load_threads(str(db_path))
    assert threads == {"u1": "t1", "u2": "t2"}

    save_threads({"u1": "t1_new"}, str(db_path))
    threads = load_threads(str(db_path))
    assert threads == {"u1": "t1_new", "u2": "t2"}
