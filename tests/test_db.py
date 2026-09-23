import pytest

from datetime import datetime, timedelta

from bot import db


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def make_game(gid="1", name="Test Game", discount=50, price=100.0, rating=80, genres="RPG"):
    return {
        "id": gid, "name": name, "discount": discount, "price": price,
        "image": "http://img", "video": None, "link": "http://link",
        "rating": rating, "genres": genres,
    }


def test_init_db_creates_tables(db_path):
    db.init_db(db_path)
    with db.get_connection(db_path) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "games" in tables
    assert "stats" in tables


def test_save_games_inserts_new_and_counts_added(db_path):
    db.init_db(db_path)
    added = db.save_games([make_game(gid="1"), make_game(gid="2")], db_path=db_path)
    assert added == 2
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert {c["game_id"] for c in candidates} == {"1", "2"}


def test_save_games_sets_min_price_to_price_on_insert(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", price=99.0)], db_path=db_path)
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates[0]["min_price"] == 99.0


def test_save_games_lowers_min_price_when_new_price_is_lower(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", price=100.0)], db_path=db_path)
    db.save_games([make_game(gid="1", price=70.0)], db_path=db_path)
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates[0]["min_price"] == 70.0


def test_save_games_keeps_min_price_when_new_price_is_higher(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", price=70.0)], db_path=db_path)
    db.save_games([make_game(gid="1", price=100.0)], db_path=db_path)
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates[0]["min_price"] == 70.0


def test_save_games_updates_existing_without_counting_as_added(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", discount=30)], db_path=db_path)
    added = db.save_games([make_game(gid="1", discount=70)], db_path=db_path)
    assert added == 0
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates[0]["discount"] == 70


def test_save_games_skips_falsy_entries(db_path):
    db.init_db(db_path)
    added = db.save_games([None, make_game(gid="1")], db_path=db_path)
    assert added == 1


def test_get_post_candidates_only_returns_new_status(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1"), make_game(gid="2")], db_path=db_path)
    db.mark_posted("1", 60, 90.0, db_path=db_path)
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert [c["game_id"] for c in candidates] == ["2"]


def test_mark_status(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1")], db_path=db_path)
    db.mark_status("1", "expired", db_path=db_path)
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates == []


def test_update_rating(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", rating=None)], db_path=db_path)
    db.update_rating("1", 88, db_path=db_path)
    candidates = db.get_post_candidates(10, db_path=db_path)
    assert candidates[0]["rating_percent"] == 88


def test_get_and_set_stat_roundtrip(db_path):
    db.init_db(db_path)
    assert db.get_stat("last_full_scan", db_path=db_path) is None
    db.set_stat("last_full_scan", "2026-01-01T00:00:00", db_path=db_path)
    assert db.get_stat("last_full_scan", db_path=db_path) == "2026-01-01T00:00:00"
    db.set_stat("last_full_scan", "2026-01-02T00:00:00", db_path=db_path)
    assert db.get_stat("last_full_scan", db_path=db_path) == "2026-01-02T00:00:00"


def test_mark_posted_sets_status_and_live_values(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", discount=30, price=50.0)], db_path=db_path)
    db.mark_posted("1", discount=60, price=40.0, db_path=db_path)
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM games WHERE game_id='1'").fetchone()
    assert row["status"] == "posted"
    assert row["discount"] == 60
    assert row["price"] == 40.0
    assert row["last_posted"] is not None


def test_mark_posted_lowers_min_price_when_live_price_is_new_low(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", price=100.0)], db_path=db_path)  # min_price=100
    db.mark_posted("1", discount=70, price=60.0, db_path=db_path)
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT min_price FROM games WHERE game_id='1'").fetchone()
    assert row["min_price"] == 60.0


def test_mark_posted_keeps_min_price_when_live_price_is_higher(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1", price=50.0)], db_path=db_path)  # min_price=50
    db.mark_posted("1", discount=30, price=80.0, db_path=db_path)
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT min_price FROM games WHERE game_id='1'").fetchone()
    assert row["min_price"] == 50.0


# ---------- cleanup_old_entries ----------

def _set_last_seen(db_path, game_id, iso_ts):
    with db.get_connection(db_path) as conn:
        conn.execute("UPDATE games SET last_seen=? WHERE game_id=?", (iso_ts, game_id))
        conn.commit()


def test_cleanup_removes_old_terminal_status_entries(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1")], db_path=db_path)
    db.mark_status("1", "expired", db_path=db_path)
    old_ts = (datetime.now() - timedelta(days=40)).isoformat()
    _set_last_seen(db_path, "1", old_ts)

    removed = db.cleanup_old_entries(retention_days=30, db_path=db_path)
    assert removed == 1
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM games WHERE game_id='1'").fetchone()
    assert row is None


def test_cleanup_keeps_recent_terminal_status_entries(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1")], db_path=db_path)
    db.mark_status("1", "expired", db_path=db_path)
    recent_ts = (datetime.now() - timedelta(days=5)).isoformat()
    _set_last_seen(db_path, "1", recent_ts)

    removed = db.cleanup_old_entries(retention_days=30, db_path=db_path)
    assert removed == 0
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM games WHERE game_id='1'").fetchone()
    assert row is not None


def test_cleanup_keeps_new_status_entries_regardless_of_age(db_path):
    db.init_db(db_path)
    db.save_games([make_game(gid="1")], db_path=db_path)  # status stays 'new'
    old_ts = (datetime.now() - timedelta(days=100)).isoformat()
    _set_last_seen(db_path, "1", old_ts)

    removed = db.cleanup_old_entries(retention_days=30, db_path=db_path)
    assert removed == 0
