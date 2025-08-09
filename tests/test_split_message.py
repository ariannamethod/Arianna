from utils.split_message import split_message


def test_split_message_splits_on_newline():
    text = "line1\nline2\nline3"
    result = split_message(text, max_length=10)
    assert result == ["line1", "line2", "line3"]


def test_split_message_handles_long_lines():
    text = "a" * 25
    result = split_message(text, max_length=10)
    assert result == ["a" * 10, "a" * 10, "a" * 5]


def test_split_message_empty_returns_placeholder():
    expected = ["Even emptiness can be divided."]
    assert split_message("", max_length=10) == expected
