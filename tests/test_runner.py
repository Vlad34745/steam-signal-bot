from datetime import datetime

import pytest

from bot import config, db
from bot.runner import (
    check_and_alert_if_silent,
    main,
    post_game,
    run_forever,
    run_scan,
    should_attempt_post,
    should_do_full_scan,
)

# ---------- should_do_full_scan ----------

def test_scan_due_when_never_scanned():
    assert should_do_full_scan(datetime(2026, 1, 1, 10, 0), None) is True


def test_scan_not_due_within_24h_before_reset_window():
    now = datetime(2026, 1, 1, 10, 0)
    last_scan = datetime(2026, 1, 1, 8, 0).isoformat()
    assert should_do_full_scan(now, last_scan) is False


def test_scan_due_after_reset_hour_if_not_scanned_since():
    now = datetime(2026, 1, 1, config.FULL_SCAN_DAILY_RESET_HOUR, 30)
    last_scan = datetime(2026, 1, 1, 8, 0).isoformat()  # before today's reset
    assert should_do_full_scan(now, last_scan) is True


def test_scan_not_due_after_reset_hour_if_already_scanned_since():
    now = datetime(2026, 1, 1, config.FULL_SCAN_DAILY_RESET_HOUR, 30)
    last_scan = datetime(2026, 1, 1, config.FULL_SCAN_DAILY_RESET_HOUR, 10).isoformat()
    assert should_do_full_scan(now, last_scan) is False


def test_scan_due_after_24h_fallback():
    now = datetime(2026, 1, 2, 5, 0)
    last_scan = datetime(2026, 1, 1, 4, 0).isoformat()  # >24h ago, before reset hour today
    assert should_do_full_scan(now, last_scan) is True


# ---------- should_attempt_post ----------

def test_post_not_due_before_interval_elapsed():
    now = datetime(2026, 1, 1, 12, 0)
    last_post = datetime(2026, 1, 1, 11, 50).isoformat()
    assert should_attempt_post(now, last_post, interval_seconds=3600,
                                window_start_hour=9, window_start_minute=0, window_end_hour=23) is False


def test_post_due_after_interval_and_inside_window():
    now = datetime(2026, 1, 1, 12, 0)
    last_post = datetime(2026, 1, 1, 10, 0).isoformat()
    assert should_attempt_post(now, last_post, interval_seconds=3600,
                                window_start_hour=9, window_start_minute=0, window_end_hour=23) is True


def test_post_not_due_outside_window():
    now = datetime(2026, 1, 1, 7, 0)  # before window start
    assert should_attempt_post(now, None, interval_seconds=3600,
                                window_start_hour=9, window_start_minute=0, window_end_hour=23) is False


def test_post_due_with_no_prior_post_inside_window():
    now = datetime(2026, 1, 1, 12, 0)
    assert should_attempt_post(now, None, interval_seconds=3600,
                                window_start_hour=9, window_start_minute=0, window_end_hour=23) is True


# ---------- post_game ----------

@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "test.db")
    db.init_db(p)
    return p


def _seed_game(db_path, gid="1", name="Test Game"):
    db.save_games([{
        "id": gid, "name": name, "discount": 50, "price": 100.0,
        "image": "img", "video": None, "link": "http://link",
        "rating": 80, "genres": "RPG",
    }], db_path=db_path)


def test_post_game_returns_false_when_no_candidates(db_path):
    assert post_game("tok", "chat", db_path=db_path) is False


def test_post_game_marks_expired_when_discount_gone(db_path, monkeypatch):
    _seed_game(db_path)
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: None)
    result = post_game("tok", "chat", db_path=db_path)
    assert result is False
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates == []  # no longer 'new'


def test_post_game_success_path_marks_posted(db_path, monkeypatch):
    _seed_game(db_path)
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: (60, 150.0))
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))

    class FakeResp:
        status_code = 200

    monkeypatch.setattr("bot.runner.send_post", lambda *a, **kw: FakeResp())

    result = post_game("tok", "chat", db_path=db_path)
    assert result is True
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT status, discount, price FROM games WHERE game_id='1'").fetchone()
    assert row["status"] == "posted"
    assert row["discount"] == 60
    assert row["price"] == 150.0


def test_post_game_marks_failed_on_non_200_and_tries_next_candidate(db_path, monkeypatch):
    _seed_game(db_path, gid="1", name="First")
    _seed_game(db_path, gid="2", name="Second")
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: (60, 150.0))
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))
    monkeypatch.setattr("bot.runner.time.sleep", lambda s: None)

    class FailResp:
        status_code = 400
        text = "bad request"

    calls = {"n": 0}

    def fake_send_post(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return FailResp()

        class OkResp:
            status_code = 200
        return OkResp()

    monkeypatch.setattr("bot.runner.send_post", fake_send_post)
    result = post_game("tok", "chat", db_path=db_path)
    assert result is True
    assert calls["n"] == 2


# ---------- run_scan ----------

def test_run_scan_saves_games_and_updates_stat(db_path, monkeypatch):
    monkeypatch.setattr("bot.runner.fetch_steam", lambda: ["raw1"])
    monkeypatch.setattr("bot.runner.normalize_all", lambda raw: [{
        "id": "1", "name": "G", "discount": 50, "price": 100.0,
        "image": "img", "video": None, "link": "http://link", "rating": 80, "genres": "",
    }])
    added = run_scan(db_path=db_path)
    assert added == 1
    assert db.get_stat("last_full_scan", db_path=db_path) is not None


# ---------- post_game: rating lookup + failure paths ----------

def test_post_game_fetches_rating_when_missing(db_path, monkeypatch):
    db.save_games([{
        "id": "1", "name": "Test Game", "discount": 50, "price": 100.0,
        "image": "img", "video": None, "link": "http://link",
        "rating": None, "genres": "RPG",
    }], db_path=db_path)
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: (60, 150.0))
    monkeypatch.setattr("bot.runner.get_steam_rating", lambda gid, **kw: 91)
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))

    class FakeResp:
        status_code = 200

    monkeypatch.setattr("bot.runner.send_post", lambda *a, **kw: FakeResp())
    assert post_game("tok", "chat", db_path=db_path) is True
    # posted, so no longer a 'new' candidate - check the row directly instead
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT rating_percent FROM games WHERE game_id='1'").fetchone()
    assert row["rating_percent"] == 91


def test_post_game_returns_false_when_telegram_never_succeeds(db_path, monkeypatch):
    _seed_game(db_path)
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: (60, 150.0))
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))
    monkeypatch.setattr("bot.runner.time.sleep", lambda s: None)

    monkeypatch.setattr("bot.runner.send_post", lambda *a, **kw: None)  # network error -> None
    assert post_game("tok", "chat", db_path=db_path) is False


def test_post_game_handles_exception_and_continues(db_path, monkeypatch):
    _seed_game(db_path, gid="1", name="First")
    _seed_game(db_path, gid="2", name="Second")

    def boom(gid, **kw):
        if gid == "1":
            raise RuntimeError("unexpected")
        return (60, 150.0)

    monkeypatch.setattr("bot.runner.check_live_price", boom)
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))
    monkeypatch.setattr("bot.runner.time.sleep", lambda s: None)

    class OkResp:
        status_code = 200

    monkeypatch.setattr("bot.runner.send_post", lambda *a, **kw: OkResp())
    assert post_game("tok", "chat", db_path=db_path) is True


# ---------- main loop ----------

def test_main_runs_one_iteration_then_stops(db_path, monkeypatch):
    """Drives main()'s while-loop exactly once by raising from the sleep_fn."""
    monkeypatch.setattr("bot.runner.should_do_full_scan", lambda *a, **kw: False)
    monkeypatch.setattr("bot.runner.should_attempt_post", lambda *a, **kw: False)

    class StopLoop(Exception):
        pass

    def fake_sleep(_seconds):
        raise StopLoop()

    with pytest.raises(StopLoop):
        main("tok", "chat", db_path=db_path, sleep_fn=fake_sleep)


def test_main_runs_scan_and_post_when_due(db_path, monkeypatch):
    monkeypatch.setattr("bot.runner.should_do_full_scan", lambda *a, **kw: True)
    monkeypatch.setattr("bot.runner.should_attempt_post", lambda *a, **kw: True)
    monkeypatch.setattr("bot.runner.run_scan", lambda **kw: 0)
    monkeypatch.setattr("bot.runner.post_game", lambda *a, **kw: True)

    class StopLoop(Exception):
        pass

    def fake_sleep(_seconds):
        raise StopLoop()

    with pytest.raises(StopLoop):
        main("tok", "chat", db_path=db_path, sleep_fn=fake_sleep)
    assert db.get_stat("last", db_path=db_path) is not None


def test_main_handles_scan_exception(db_path, monkeypatch):
    monkeypatch.setattr("bot.runner.should_do_full_scan", lambda *a, **kw: True)
    monkeypatch.setattr("bot.runner.should_attempt_post", lambda *a, **kw: False)

    def boom_scan(**kw):
        raise RuntimeError("scan failed")

    monkeypatch.setattr("bot.runner.run_scan", boom_scan)

    class StopLoop(Exception):
        pass

    def fake_sleep(_seconds):
        raise StopLoop()

    with pytest.raises(StopLoop):
        main("tok", "chat", db_path=db_path, sleep_fn=fake_sleep)


# ---------- post_game: historic-low claim ----------

def test_post_game_flags_historic_low_when_live_price_at_or_below_min(db_path, monkeypatch):
    db.save_games([{
        "id": "1", "name": "Test Game", "discount": 50, "price": 100.0,
        "image": "img", "video": None, "link": "http://link",
        "rating": 80, "genres": "RPG",
    }], db_path=db_path)  # min_price becomes 100.0
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: (60, 90.0))  # new low
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))

    captured = {}

    class OkResp:
        status_code = 200

    def fake_send_post(token, chat_id, caption, image, video, link, **kw):
        captured["caption"] = caption
        return OkResp()

    monkeypatch.setattr("bot.runner.send_post", fake_send_post)
    assert post_game("tok", "chat", db_path=db_path) is True
    assert "найнижча ціна" in captured["caption"]


def test_post_game_does_not_flag_historic_low_when_price_above_min(db_path, monkeypatch):
    db.save_games([{
        "id": "1", "name": "Test Game", "discount": 50, "price": 50.0,
        "image": "img", "video": None, "link": "http://link",
        "rating": 80, "genres": "RPG",
    }], db_path=db_path)  # min_price becomes 50.0
    monkeypatch.setattr("bot.runner.check_live_price", lambda gid, **kw: (30, 80.0))  # higher than min
    monkeypatch.setattr("bot.runner.get_ai_content", lambda *a, **kw: ("Header", "Body"))

    captured = {}

    class OkResp:
        status_code = 200

    def fake_send_post(token, chat_id, caption, image, video, link, **kw):
        captured["caption"] = caption
        return OkResp()

    monkeypatch.setattr("bot.runner.send_post", fake_send_post)
    assert post_game("tok", "chat", db_path=db_path) is True
    assert "найнижча ціна" not in captured["caption"]


# ---------- run_forever ----------

def test_run_forever_restarts_after_crash_then_gives_up(db_path, monkeypatch):
    calls = {"n": 0}

    def flaky_main(token, chat_id, ai_client=None, db_path=None, sleep_fn=None):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("bot.runner.main", flaky_main)
    sleeps = []

    with pytest.raises(RuntimeError):
        run_forever("tok", "chat", db_path=db_path, sleep_fn=sleeps.append,
                     restart_delay_seconds=7, max_restarts=2)

    assert calls["n"] == 2
    assert sleeps == [7]  # slept once between attempt 1 and attempt 2, then gave up


def test_run_forever_propagates_keyboard_interrupt_without_restarting(db_path, monkeypatch):
    def interrupted_main(*a, **kw):
        raise KeyboardInterrupt()

    monkeypatch.setattr("bot.runner.main", interrupted_main)
    sleeps = []

    with pytest.raises(KeyboardInterrupt):
        run_forever("tok", "chat", db_path=db_path, sleep_fn=sleeps.append)

    assert sleeps == []  # no restart attempted


# ---------- check_and_alert_if_silent ----------

def test_no_alert_when_no_reference_timestamp_yet(db_path):
    db.init_db(db_path)
    assert check_and_alert_if_silent("tok", "chat", datetime(2026, 1, 1), db_path=db_path) is False


def test_no_alert_when_within_threshold(db_path):
    db.init_db(db_path)
    db.set_stat("last", datetime(2026, 1, 1).isoformat(), db_path=db_path)
    now = datetime(2026, 1, 2)  # only 1 day silent, threshold is 3
    assert check_and_alert_if_silent("tok", "chat", now, db_path=db_path,
                                      silence_alert_days=3) is False


def test_alert_sent_once_threshold_crossed(db_path, monkeypatch):
    db.init_db(db_path)
    db.set_stat("last", datetime(2026, 1, 1).isoformat(), db_path=db_path)
    now = datetime(2026, 1, 5)  # 4 days silent, threshold 3

    sent = {}

    class OkResp:
        status_code = 200

    def fake_send_text(token, chat_id, text, **kw):
        sent["text"] = text
        return OkResp()

    monkeypatch.setattr("bot.runner.send_text", fake_send_text)
    result = check_and_alert_if_silent("tok", "chat", now, db_path=db_path, silence_alert_days=3)
    assert result is True
    assert "4" in sent["text"]
    assert db.get_stat("last_silence_alert", db_path=db_path) is not None


def test_alert_not_repeated_within_recheck_window(db_path, monkeypatch):
    db.init_db(db_path)
    db.set_stat("last", datetime(2026, 1, 1).isoformat(), db_path=db_path)
    db.set_stat("last_silence_alert", datetime(2026, 1, 5).isoformat(), db_path=db_path)
    now = datetime(2026, 1, 5, 2, 0)  # 2h after last alert, recheck window is 24h

    monkeypatch.setattr("bot.runner.send_text", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not send")))
    result = check_and_alert_if_silent("tok", "chat", now, db_path=db_path,
                                        silence_alert_days=3, recheck_hours=24)
    assert result is False


def test_alert_falls_back_to_bot_started_at_when_never_posted(db_path, monkeypatch):
    db.init_db(db_path)
    db.set_stat("bot_started_at", datetime(2026, 1, 1).isoformat(), db_path=db_path)
    now = datetime(2026, 1, 10)

    class OkResp:
        status_code = 200

    monkeypatch.setattr("bot.runner.send_text", lambda *a, **kw: OkResp())
    result = check_and_alert_if_silent("tok", "chat", now, db_path=db_path, silence_alert_days=3)
    assert result is True


# ---------- main() sets bot_started_at and checks silence ----------

def test_main_sets_bot_started_at_once(db_path, monkeypatch):
    monkeypatch.setattr("bot.runner.should_do_full_scan", lambda *a, **kw: False)
    monkeypatch.setattr("bot.runner.should_attempt_post", lambda *a, **kw: False)
    monkeypatch.setattr("bot.runner.check_and_alert_if_silent", lambda *a, **kw: False)

    class StopLoop(Exception):
        pass

    def fake_sleep(_seconds):
        raise StopLoop()

    with pytest.raises(StopLoop):
        main("tok", "chat", db_path=db_path, sleep_fn=fake_sleep)
    assert db.get_stat("bot_started_at", db_path=db_path) is not None
