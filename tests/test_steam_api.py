from bot.steam_api import (
    get_steam_rating, collect_discounted_appids, fetch_appdetails,
    is_blocked, fetch_steam, norm, normalize_all, check_live_price,
)


class FakeResponse:
    def __init__(self, payload=None, raise_exc=None):
        self._payload = payload
        self._raise_exc = raise_exc

    def json(self):
        if self._raise_exc:
            raise self._raise_exc
        return self._payload


class FakeSession:
    """Records calls and returns pre-programmed responses in order (by URL substring match)."""

    def __init__(self, responses):
        # responses: list of (url_substring, FakeResponse)
        self.responses = responses
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        for substr, resp in self.responses:
            if substr in url:
                return resp
        raise AssertionError(f"No fake response configured for {url}")


def test_get_steam_rating_computes_percentage():
    session = FakeSession([
        ("appreviews", FakeResponse({"query_summary": {"total_reviews": 200, "total_positive": 150}}))
    ])
    assert get_steam_rating("123", session=session) == 75


def test_get_steam_rating_returns_none_when_no_reviews():
    session = FakeSession([("appreviews", FakeResponse({"query_summary": {"total_reviews": 0}}))])
    assert get_steam_rating("123", session=session) is None


def test_get_steam_rating_returns_none_on_error():
    session = FakeSession([("appreviews", FakeResponse(raise_exc=ConnectionError("boom")))])
    assert get_steam_rating("123", session=session) is None


def test_collect_discounted_appids_stops_on_empty_page():
    session = FakeSession([
        ("start=0", FakeResponse({"results_html": 'data-ds-appid="1" data-ds-appid="2"'})),
        ("start=50", FakeResponse({"results_html": ""})),
    ])
    ids = collect_discounted_appids(session=session, sleep_fn=lambda s: None)
    assert ids == ["1", "2"]


def test_collect_discounted_appids_stops_on_exception():
    session = FakeSession([("start=0", FakeResponse(raise_exc=TimeoutError("slow")))])
    ids = collect_discounted_appids(session=session, sleep_fn=lambda s: None)
    assert ids == []


def test_fetch_appdetails_success():
    session = FakeSession([
        ("appdetails", FakeResponse({"42": {"success": True, "data": {"name": "Game"}}}))
    ])
    assert fetch_appdetails("42", session=session) == {"name": "Game"}


def test_fetch_appdetails_failure_returns_none():
    session = FakeSession([("appdetails", FakeResponse({"42": {"success": False}}))])
    assert fetch_appdetails("42", session=session) is None


def test_is_blocked_matches_block_list_word():
    assert is_blocked({"name": "Some Hentai Game", "short_description": ""}) is True
    assert is_blocked({"name": "Normal Game", "short_description": "an adventure"}) is False


def test_fetch_steam_filters_blocked_and_non_games():
    session = FakeSession([
        ("start=0", FakeResponse({"results_html": 'data-ds-appid="1" data-ds-appid="2" data-ds-appid="3"'})),
        ("start=50", FakeResponse({"results_html": ""})),
        ("appdetails?appids=1", FakeResponse({"1": {"success": True, "data": {
            "name": "Good Game", "short_description": "", "type": "game", "header_image": "img"}}})),
        ("appdetails?appids=2", FakeResponse({"2": {"success": True, "data": {
            "name": "Hentai Thing", "short_description": "", "type": "game", "header_image": "img"}}})),
        ("appdetails?appids=3", FakeResponse({"3": {"success": True, "data": {
            "name": "A DLC", "short_description": "", "type": "dlc", "header_image": "img"}}})),
    ])
    result = fetch_steam(session=session, sleep_fn=lambda s: None)
    assert [g["name"] for g in result] == ["Good Game"]


def test_norm_returns_none_below_min_discount():
    payload = {"price_overview": {"discount_percent": 5}}
    assert norm(payload, session=FakeSession([])) is None


def test_norm_builds_expected_shape():
    session = FakeSession([("appreviews", FakeResponse({"query_summary": {"total_reviews": 10, "total_positive": 8}}))])
    payload = {
        "steam_appid": 99,
        "name": "Cool Game",
        "price_overview": {"discount_percent": 50, "final": 19999},
        "movies": [{"mp4": {"max": "http://video"}}],
        "genres": [{"description": "RPG"}, {"description": "Action"}],
    }
    result = norm(payload, session=session)
    assert result == {
        "id": "99", "name": "Cool Game", "discount": 50, "price": 199.99,
        "image": None, "video": "http://video", "rating": 80, "genres": "RPG, Action",
        "link": "https://store.steampowered.com/app/99",
    }


def test_norm_calls_rating_exactly_once_per_game():
    """Regression test: norm() used to be called twice per game in the old
    list comprehension, doubling get_steam_rating() network calls."""
    session = FakeSession([("appreviews", FakeResponse({"query_summary": {"total_reviews": 10, "total_positive": 5}}))])
    payload = {
        "steam_appid": 1, "name": "G", "price_overview": {"discount_percent": 50, "final": 1000}, "genres": [],
    }
    normalize_all([payload], session=session)
    rating_calls = [c for c in session.calls if "appreviews" in c]
    assert len(rating_calls) == 1


def test_normalize_all_drops_non_qualifying_games():
    session = FakeSession([("appreviews", FakeResponse({"query_summary": {"total_reviews": 1, "total_positive": 1}}))])
    below_threshold = {"price_overview": {"discount_percent": 5}}
    qualifying = {"steam_appid": 1, "name": "G", "price_overview": {"discount_percent": 50, "final": 1000}, "genres": []}
    result = normalize_all([below_threshold, qualifying], session=session)
    assert len(result) == 1
    assert result[0]["id"] == "1"


def test_check_live_price_returns_none_when_expired():
    session = FakeSession([("appdetails", FakeResponse({"1": {"success": True, "data": {
        "price_overview": {"discount_percent": 5, "final": 100}}}}))])
    assert check_live_price("1", session=session) is None


def test_check_live_price_returns_current_values():
    session = FakeSession([("appdetails", FakeResponse({"1": {"success": True, "data": {
        "price_overview": {"discount_percent": 60, "final": 15000}}}}))])
    assert check_live_price("1", session=session) == (60, 150.0)


def test_check_live_price_returns_none_when_fetch_fails():
    session = FakeSession([("appdetails", FakeResponse({"1": {"success": False}}))])
    assert check_live_price("1", session=session) is None
