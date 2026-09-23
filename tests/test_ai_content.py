from bot.ai_content import get_ai_content, NO_KEY_HEADER, FALLBACK_HEADER


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeClient:
    def __init__(self, texts_or_exceptions):
        self._queue = list(texts_or_exceptions)
        self.models = self
        self.calls = 0

    def generate_content(self, model, contents):
        self.calls += 1
        item = self._queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeResponse(item)


def test_no_client_returns_static_fallback_immediately():
    header, body = get_ai_content("My Game", 50, client=None)
    assert header == NO_KEY_HEADER
    assert "My Game" in body


def test_successful_response_is_parsed_into_header_and_body():
    client = FakeClient(["Заголовок|Опис: Чудова гра для всіх."])
    header, body = get_ai_content("My Game", 50, client=client, sleep_fn=lambda s: None)
    assert header == "Заголовок"
    assert body == "Чудова гра для всіх."
    assert client.calls == 1


def test_response_without_separator_uses_default_header():
    client = FakeClient(["просто суцільний текст без роздільника"])
    header, body = get_ai_content("My Game", 50, client=client, sleep_fn=lambda s: None)
    assert header == "Варто глянути"
    assert body[0].isupper()


def test_retries_on_exception_then_succeeds():
    client = FakeClient([RuntimeError("boom"), "Заголовок|Хороший опис."])
    header, body = get_ai_content("My Game", 50, client=client, sleep_fn=lambda s: None)
    assert header == "Заголовок"
    assert client.calls == 2


def test_falls_back_to_static_after_exhausting_retries():
    client = FakeClient([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    header, body = get_ai_content("My Game", 50, client=client, sleep_fn=lambda s: None, max_retries=2)
    assert header == FALLBACK_HEADER
    assert "My Game" in body
    assert client.calls == 3  # initial attempt + 2 retries
