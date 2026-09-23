"""
Orchestration layer: the main loop plus the scan/post scheduling rules.

The scheduling rules (should_do_full_scan / should_attempt_post) are pulled
out as pure functions of (now, stored timestamps, config) so they can be
unit-tested without a live clock, a database, or the network.
"""
import logging
import random
import time
from datetime import datetime
from typing import Optional

from bot import config, db
from bot.scoring import stars_for_rating
from bot.steam_api import fetch_steam, get_steam_rating, normalize_all, check_live_price
from bot.telegram_client import build_caption, send_post
from bot.ai_content import get_ai_content


def should_do_full_scan(now: datetime, last_scan_iso: Optional[str]) -> bool:
    """True if a full Steam catalogue scan is due.

    Rule: scan if we've never scanned, or if it's past today's daily reset
    hour and we haven't scanned since that reset, or if more than 24h have
    passed since the last scan (fallback for when the reset check misses,
    e.g. the bot was offline over the reset hour).
    """
    if not last_scan_iso:
        return True

    last_scan_dt = datetime.fromisoformat(last_scan_iso)
    cur_time = now.strftime("%H:%M")
    reset_time_str = f"{config.FULL_SCAN_DAILY_RESET_HOUR:02d}:05"

    if cur_time >= reset_time_str:
        today_limit = now.replace(hour=config.FULL_SCAN_DAILY_RESET_HOUR, minute=0, second=0, microsecond=0)
        return last_scan_dt < today_limit

    return (now - last_scan_dt).total_seconds() > 24 * 3600


def should_attempt_post(now: datetime, last_post_iso, interval_seconds: int,
                         window_start_hour: int, window_start_minute: int, window_end_hour: int) -> bool:
    """True if enough time has passed since the last post AND we're inside today's posting window."""
    if last_post_iso:
        elapsed = (now - datetime.fromisoformat(last_post_iso)).total_seconds()
        if elapsed <= interval_seconds:
            return False

    start_time = now.replace(hour=window_start_hour, minute=window_start_minute, second=0, microsecond=0)
    end_time = now.replace(hour=window_end_hour, minute=0, second=0, microsecond=0)
    return start_time <= now < end_time


# ================= SCAN =================
def run_scan(db_path: str = db.DB_PATH) -> int:
    raw_games = fetch_steam()
    processed_games = normalize_all(raw_games)
    added = db.save_games(processed_games, db_path=db_path)
    logging.info(f"Database updated (added: {added})")

    removed = db.cleanup_old_entries(config.DB_RETENTION_DAYS, db_path=db_path)
    if removed:
        logging.info(f"Cleaned up {removed} old entries (older than {config.DB_RETENTION_DAYS} days).")

    db.set_stat("last_full_scan", datetime.now().isoformat(), db_path=db_path)
    return added


# ================= POSTING =================
def post_game(token: str, chat_id: str, ai_client=None, db_path: str = db.DB_PATH) -> bool:
    candidates = db.get_post_candidates(config.POST_CANDIDATE_POOL_SIZE, db_path=db_path)
    if not candidates:
        logging.info("Nothing new to post.")
        return False

    random.shuffle(candidates)

    for g in candidates:
        game_id = g["game_id"]
        try:
            live = check_live_price(game_id)
            if live is None:
                logging.info(f"Discount for {g['name']} has expired or is missing, marking as expired.")
                db.mark_status(game_id, "expired", db_path=db_path)
                continue
            live_discount, live_price = live

            game_rating = g.get("rating_percent")
            if not game_rating:
                game_rating = get_steam_rating(game_id)
                if game_rating is not None:
                    db.update_rating(game_id, game_rating, db_path=db_path)

            rating_block = ""
            if game_rating:
                stars = stars_for_rating(game_rating)
                rating_block = f"⭐ Рейтинг Steam: {stars} ({game_rating}%)\n"

            header, ai_text = get_ai_content(g["name"], live_discount, game_rating, client=ai_client)
            # min_price reflects the lowest price this bot has observed for this game so far
            # (via scans + past live-price checks) - it's only ever set from data we fetched
            # ourselves, since Steam doesn't expose a public full price-history API.
            stored_min = g.get("min_price")
            is_historic_low = stored_min is None or live_price <= stored_min
            caption = build_caption(header, g["name"], live_discount, live_price, rating_block, ai_text,
                                     is_historic_low=is_historic_low)

            res_tg = send_post(token, chat_id, caption, g["image"], g["video"], g["link"])

            if res_tg is not None and res_tg.status_code == 200:
                db.mark_posted(game_id, live_discount, live_price, db_path=db_path)
                logging.info(f"Posted with live price: {g['name']} (-{live_discount}%)")
                return True
            else:
                status_text = res_tg.text if res_tg is not None else "no response"
                logging.error(f"Telegram error: {status_text}")
                db.mark_status(game_id, "failed", db_path=db_path)
                time.sleep(5)

        except Exception as e:
            logging.error(f"Critical error processing {g['name']}: {e}")
            time.sleep(2)
            continue

    return False


# ================= MAIN LOOP =================
def main(token: str, chat_id: str, ai_client=None, db_path: str = db.DB_PATH, sleep_fn=time.sleep):
    db.init_db(db_path=db_path)
    logging.info("Bot started")

    today_start_hour = config.DAILY_POST_WINDOW_START_HOUR
    today_start_minute = random.randint(0, 30)
    logging.info(f"Today's posting window opens after {today_start_hour:02d}:{today_start_minute:02d}")

    while True:
        now = datetime.now()
        last_scan_iso = db.get_stat("last_full_scan", db_path=db_path)

        if should_do_full_scan(now, last_scan_iso):
            try:
                run_scan(db_path=db_path)
            except Exception as e:
                logging.error(f"Scan failed: {e}")

        last_post_iso = db.get_stat("last", db_path=db_path)
        interval_seconds = random.randint(
            config.POST_INTERVAL_MIN_MINUTES, config.POST_INTERVAL_MAX_MINUTES
        ) * 60

        if should_attempt_post(now, last_post_iso, interval_seconds,
                                today_start_hour, today_start_minute, config.DAILY_POST_WINDOW_END_HOUR):
            if post_game(token, chat_id, ai_client=ai_client, db_path=db_path):
                db.set_stat("last", datetime.now().isoformat(), db_path=db_path)
                today_start_minute = random.randint(0, 30)
                logging.info(f"Post published. Next window opens tomorrow at 09:{today_start_minute:02d}")

        sleep_fn(60)


# ================= CRASH-RESISTANT WRAPPER =================
def run_forever(token: str, chat_id: str, ai_client=None, db_path: str = db.DB_PATH,
                 sleep_fn=time.sleep, restart_delay_seconds: int = config.CRASH_RESTART_DELAY_SECONDS,
                 max_restarts: Optional[int] = None):
    """
    Runs main() and automatically restarts it if it crashes with an
    unhandled exception (main()'s own loop body already catches scan and
    per-candidate posting errors - this is a last-resort safety net for
    anything that slips past those, e.g. a corrupted DB file).

    KeyboardInterrupt (Ctrl+C) is never treated as a crash - it always
    propagates so the process actually stops when asked to.
    """
    restarts = 0
    while True:
        try:
            main(token, chat_id, ai_client=ai_client, db_path=db_path, sleep_fn=sleep_fn)
        except KeyboardInterrupt:
            logging.info("Stopped by user (KeyboardInterrupt).")
            raise
        except Exception as e:
            restarts += 1
            logging.error(f"Bot crashed unexpectedly: {e}. Restarting in {restart_delay_seconds}s "
                           f"(restart #{restarts}).")
            if max_restarts is not None and restarts >= max_restarts:
                logging.error(f"Reached max_restarts={max_restarts}, giving up.")
                raise
            sleep_fn(restart_delay_seconds)
