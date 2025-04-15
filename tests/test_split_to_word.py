import pytest
from app.search_engine import split_to_words


@pytest.mark.parametrize(
    "input_text, expected_output",
    [
        ("Hello world!", ["hello", "world"]),  # обычный текст
        ("Python is great.", ["python", "is", "great"]),  # текст с пробелами и точкой
        ("Hello, world? How's it going?", ["hello", "world", "how", "s", "it", "going"]),  # текст с вопросительными и апострофами
        ("Test123 test_456 test-789", ["test123", "test_456", "test_789"]),  # текст с цифрами и символами
        ("  Multiple    spaces    here   ", ["multiple", "spaces", "here"]),  # текст с несколькими пробелами
        ("", []),  # пустая строка
    ]
)
async def test_split_to_words(input_text, expected_output):
    assert await split_to_words(input_text) == expected_output