from bot.telegram_client import build_caption, send_post


class FakeResponse:
    def __init__(self, status_code, json_body=None, text=""):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.text = text

    def json(self):
        return self._json_body


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, data, timeout):
        self.calls.append((url, data))
        return self._responses.pop(0)


def test_build_caption_contains_key_fields():
    caption = build_caption("Header", "Game", 60, 199.0, "rating\n", "AI text")
    assert "Header" in caption
    assert "Game" in caption
    assert "-60%" in caption
    assert "199 грн" in caption


def test_build_caption_omits_historic_low_line_by_default():
    caption = build_caption("Header", "Game", 60, 199.0, "rating\n", "AI text")
    assert "найнижча ціна" not in caption


def test_build_caption_includes_historic_low_line_when_flagged():
    caption = build_caption("Header", "Game", 60, 199.0, "rating\n", "AI text", is_historic_low=True)
    assert "найнижча ціна" in caption


def test_send_post_uses_photo_when_no_video():
    session = FakeSession([FakeResponse(200)])
    send_post("tok", "chat", "caption", image="img.png", video=None, link="http://x", session=session)
    url, data = session.calls[0]
    assert "sendPhoto" in url
    assert data["photo"] == "img.png"


def test_send_post_uses_video_when_present():
    session = FakeSession([FakeResponse(200)])
    send_post("tok", "chat", "caption", image="img.png", video="vid.mp4", link="http://x", session=session)
    url, data = session.calls[0]
    assert "sendVideo" in url
    assert data["video"] == "vid.mp4"


def test_send_post_retries_on_429_then_succeeds():
    session = FakeSession([
        FakeResponse(429, json_body={"parameters": {"retry_after": 1}}),
        FakeResponse(200),
    ])
    sleeps = []
    res = send_post("tok", "chat", "cap", "img", None, "link", session=session, sleep_fn=sleeps.append)
    assert res.status_code == 200
    assert sleeps == [1]
    assert len(session.calls) == 2


def test_send_post_gives_up_after_max_429_retries():
    session = FakeSession([
        FakeResponse(429, json_body={"parameters": {"retry_after": 1}}),
        FakeResponse(429, json_body={"parameters": {"retry_after": 1}}),
        FakeResponse(429, json_body={"parameters": {"retry_after": 1}}),
    ])
    res = send_post("tok", "chat", "cap", "img", None, "link", session=session,
                     sleep_fn=lambda s: None, max_429_retries=2)
    assert res.status_code == 429
    assert len(session.calls) == 3


def test_send_post_returns_none_on_network_error():
    class BoomSession:
        def post(self, *a, **kw):
            raise ConnectionError("no network")

    res = send_post("tok", "chat", "cap", "img", None, "link", session=BoomSession())
    assert res is None


def test_send_text_uses_sendmessage_endpoint():
    session = FakeSession([FakeResponse(200)])
    from bot.telegram_client import send_text
    send_text("tok", "chat", "Hello there", session=session)
    url, data = session.calls[0]
    assert "sendMessage" in url
    assert data["text"] == "Hello there"
    assert data["chat_id"] == "chat"


def test_send_text_truncates_long_text():
    session = FakeSession([FakeResponse(200)])
    from bot.telegram_client import send_text
    long_text = "x" * 5000
    send_text("tok", "chat", long_text, session=session)
    _, data = session.calls[0]
    assert len(data["text"]) == 4096


def test_send_text_retries_on_429():
    session = FakeSession([
        FakeResponse(429, json_body={"parameters": {"retry_after": 2}}),
        FakeResponse(200),
    ])
    from bot.telegram_client import send_text
    sleeps = []
    res = send_text("tok", "chat", "hi", session=session, sleep_fn=sleeps.append)
    assert res.status_code == 200
    assert sleeps == [2]
