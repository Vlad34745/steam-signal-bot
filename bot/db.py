"""
All SQLite access lives here, behind small, testable functions.

Every function opens its own short-lived connection via ``contextlib.closing``
so the connection is always closed, even if something raises partway
through. Note: ``with sqlite3.connect(...) as conn:`` on its own only
commits/rolls back the transaction - it does NOT close the connection - so
we wrap it in ``closing()`` on top of that. The previous version opened and
closed connections manually in several places in main.py, which could leak
a connection on exceptions.
"""
import sqlite3
from contextlib import closing
from datetime import datetime

from bot.scoring import calc_score

DB_PATH = "steam.db"


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    with closing(get_connection(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                name TEXT,
                discount INTEGER,
                price REAL,
                min_price REAL,
                image TEXT,
                video TEXT,
                link TEXT,
                score REAL,
                rating_percent INTEGER,
                genres TEXT,
                ai_text TEXT,
                last_seen TEXT,
                last_posted TEXT,
                status TEXT DEFAULT 'new'
            )""")
        conn.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()


def save_games(games, db_path: str = DB_PATH) -> int:
    """Upserts a list of normalized game dicts. Returns the number of newly inserted rows."""
    added = 0
    now = datetime.now().isoformat()
    with closing(get_connection(db_path)) as conn:
        c = conn.cursor()
        for g in games:
            if not g:
                continue
            score = calc_score(g["discount"], g["name"], g["price"], g["rating"], g["genres"])
            c.execute("SELECT price FROM games WHERE game_id=?", (g["id"],))
            row = c.fetchone()
            if row:
                c.execute("""
                    UPDATE games
                    SET discount=?, price=?, last_seen=?, rating_percent=?, genres=?, score=?,
                        min_price = CASE WHEN min_price IS NULL OR ? < min_price THEN ? ELSE min_price END
                    WHERE game_id=?
                """, (g["discount"], g["price"], now, g["rating"], g["genres"], score,
                      g["price"], g["price"], g["id"]))
            else:
                c.execute("""
                    INSERT INTO games
                    (game_id, name, discount, price, min_price, image, video, link, rating_percent, genres, score, last_seen)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (g["id"], g["name"], g["discount"], g["price"], g["price"], g["image"], g["video"],
                      g["link"], g["rating"], g["genres"], score, now))
                added += 1
        conn.commit()
    return added


def get_post_candidates(limit: int, db_path: str = DB_PATH):
    with closing(get_connection(db_path)) as conn:
        rows = conn.execute("""
            SELECT * FROM games
            WHERE status='new'
            ORDER BY score DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def mark_status(game_id: str, status: str, db_path: str = DB_PATH) -> None:
    with closing(get_connection(db_path)) as conn:
        conn.execute("UPDATE games SET status=? WHERE game_id=?", (status, game_id))
        conn.commit()


def mark_posted(game_id: str, discount: int, price: float, db_path: str = DB_PATH) -> None:
    """Marks a game as posted with its live discount/price, and folds that
    live price into min_price if it's the lowest we've ever observed
    (min_price only reflects prices this bot has actually seen, not Steam's
    full price history, which Steam does not expose publicly)."""
    with closing(get_connection(db_path)) as conn:
        conn.execute("""
            UPDATE games
            SET status='posted', last_posted=?, discount=?, price=?,
                min_price = CASE WHEN min_price IS NULL OR ? < min_price THEN ? ELSE min_price END
            WHERE game_id=?
        """, (datetime.now().isoformat(), discount, price, price, price, game_id))
        conn.commit()


def update_rating(game_id: str, rating: int, db_path: str = DB_PATH) -> None:
    with closing(get_connection(db_path)) as conn:
        conn.execute("UPDATE games SET rating_percent=? WHERE game_id=?", (rating, game_id))
        conn.commit()


def get_stat(key: str, db_path: str = DB_PATH):
    with closing(get_connection(db_path)) as conn:
        row = conn.execute("SELECT value FROM stats WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def set_stat(key: str, value: str, db_path: str = DB_PATH) -> None:
    with closing(get_connection(db_path)) as conn:
        conn.execute("INSERT OR REPLACE INTO stats (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
