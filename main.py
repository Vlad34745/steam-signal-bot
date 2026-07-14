import time
import random
import requests
import sqlite3
import logging
import re
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from google import genai

import config

# ================= CONFIGURATION =================
load_dotenv()

TOKEN = os.getenv("TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("bot.log", encoding="utf-8"), logging.StreamHandler()]
)

if GEMINI_KEY:
    client = genai.Client(api_key=GEMINI_KEY)
    logging.info("Gemini API connected")
else:
    client = None
    logging.error("GEMINI_API_KEY not found!")


# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("steam.db")
    c = conn.cursor()

    c.execute("""
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

    c.execute("CREATE TABLE IF NOT EXISTS stats (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


# ================= SCORING =================
def calc_score(discount, name, price, rating, genres_str):
    """
    Scores a deal based on brand recognition, Steam rating, price sanity,
    and genre preference. Higher score = higher priority to post.
    """
    boost = 0
    name_lower = name.lower()
    genres_lower = genres_str.lower() if genres_str else ""

    # 1. Brand recognition boost
    is_hot = any(brand in name_lower for brand in config.HOT_BRANDS)
    if is_hot:
        boost += config.BRAND_BOOST

    # 2. Steam rating weight (dominant factor for perceived quality)
    try:
        clean_rating = int(str(rating).replace('%', '').strip())
    except Exception:
        clean_rating = config.DEFAULT_RATING_IF_UNKNOWN
    boost += clean_rating * config.RATING_WEIGHT

    # 3. Smart price/discount bonuses
    if discount >= config.HIGH_DISCOUNT_THRESHOLD and price > config.HIGH_DISCOUNT_MIN_PRICE:
        boost += config.HIGH_DISCOUNT_BOOST  # only reward huge discounts on non-junk games

    fair_min, fair_max = config.FAIR_PRICE_RANGE
    if fair_min <= price < fair_max:
        boost += config.FAIR_PRICE_BOOST  # reasonable price range for a full game

    # 4. Penalty for cheap junk (unless it's a known brand)
    if price < config.LOW_PRICE_JUNK_THRESHOLD and not is_hot:
        boost += config.LOW_PRICE_JUNK_PENALTY

    # Base score: discount contributes gradually rather than dominating
    score = (discount * config.BASE_DISCOUNT_WEIGHT) + boost + random.randint(0, config.RANDOM_JITTER_MAX)

    # 5. Genre multipliers
    check_area = f"{name_lower} {genres_lower}"

    if any(m in check_area for m in config.SLOW_GENRES):
        score = score * config.SLOW_GENRE_MULTIPLIER  # strategy/sim genres sink to the bottom
    if any(m in check_area for m in config.FAST_GENRES):
        score = score * config.FAST_GENRE_MULTIPLIER  # action/RPG genres get a light boost

    return score


# ================= STEAM API =================
def get_steam_rating(appid):
    try:
        url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all"
        r = requests.get(url, timeout=10).json()

        summary = r.get("query_summary", {})
        total = summary.get("total_reviews", 0)
        positive = summary.get("total_positive", 0)

        if total > 0:
            return int((positive / total) * 100)
    except Exception as e:
        logging.warning(f"Rating error {appid}: {e}")
    return None


def fetch_steam():
    all_ids = []
    logging.info("Collecting discounted game IDs from Steam...")
    for page in range(1, 21):
        try:
            url = f"https://store.steampowered.com/search/results/?query&start={(page-1)*50}&count=50&specials=1&cc=UA&infinite=1"
            r = requests.get(url, timeout=15).json()
            found_ids = re.findall(r'data-ds-appid="(\d+)"', r.get('results_html', ''))
            if not found_ids:
                break
            all_ids.extend(found_ids)
            time.sleep(0.5)
        except Exception as e:
            logging.warning(f"Failed to collect IDs on page {page}: {e}")
            break

    final_data = []
    process_limit = min(len(all_ids), 500)
    for i, gid in enumerate(all_ids[:process_limit]):
        try:
            res = requests.get(
                f"https://store.steampowered.com/api/appdetails?appids={gid}&cc=UA&l=ukrainian",
                timeout=10,
            ).json()
            if res and res.get(gid, {}).get('success'):
                data = res[gid]['data']

                check_str = (data.get('name', '') + data.get('short_description', '')).lower()
                if any(word in check_str for word in config.BLOCK_LIST):
                    continue

                if data.get('type') == 'game' and data.get('header_image'):
                    final_data.append(data)
            time.sleep(0.7)
            if (i + 1) % 50 == 0:
                time.sleep(15)
        except Exception:
            continue
    return final_data


def norm(g):
    """Normalizes a raw Steam appdetails payload into the app's internal game format."""
    try:
        price_data = g.get("price_overview", {})
        if not price_data or price_data.get("discount_percent", 0) < config.MIN_DISCOUNT_PERCENT:
            return None

        gid = str(g.get("steam_appid"))
        rating = get_steam_rating(gid)

        video_url = None
        movies = g.get("movies")
        if movies:
            video_url = movies[0].get("mp4", {}).get("max")

        genres_list = g.get("genres", [])
        genres_str = ", ".join([genre.get("description", "") for genre in genres_list])

        return {
            "id": gid,
            "name": g.get("name", "Unknown"),
            "discount": int(price_data.get("discount_percent")),
            "price": price_data.get("final", 0) / 100,
            "image": g.get("header_image"),
            "video": video_url,
            "rating": rating,
            "genres": genres_str,
            "link": f"https://store.steampowered.com/app/{gid}",
        }
    except Exception:
        return None


def save_games(games):
    conn = sqlite3.connect("steam.db")
    c = conn.cursor()

    added = 0
    now = datetime.now().isoformat()

    for g in games:
        if not g:
            continue

        score = calc_score(g["discount"], g["name"], g["price"], g["rating"], g["genres"])

        c.execute("SELECT price FROM games WHERE game_id=?", (g["id"],))
        row = c.fetchone()

        if row:
            c.execute("""
                UPDATE games
                SET discount=?, price=?, last_seen=?, rating_percent=?, genres=?, score=?
                WHERE game_id=?
            """, (
                g["discount"], g["price"], now, g["rating"], g["genres"], score, g["id"]
            ))
        else:
            c.execute("""
                INSERT INTO games
                (game_id, name, discount, price, image, video, link, rating_percent, genres, score, last_seen)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                g["id"], g["name"], g["discount"], g["price"],
                g["image"], g["video"], g["link"], g["rating"], g["genres"], score, now
            ))
            added += 1

    conn.commit()
    conn.close()
    return added


# ================= AI GENERATION =================
def get_ai_content(name, discount, rating=None, retry=0):
    """
    Generates a short Ukrainian-language promo post via Gemini.
    Falls back to a static template if the API key is missing or the call fails.
    """
    if not GEMINI_KEY:
        return "Гарна пропозиція", f"🔥 {name} за супер ціною!"
    try:
        time.sleep(2)
        style = random.choice(config.AI_STYLES)
        rating_info = f"Рейтинг Steam: {rating}%." if rating else "Рейтинг поки невідомий."

        prompt = (f"Гра: '{name}' (-{discount}%). {rating_info} "
                  f"Твоя роль: {style['role']}. {style['mood']}. "
                  f"Напиши пост за таким планом: "
                  f"1. Короткий заголовок (до 3 слів). "
                  f"2. Опис: 1 речення (жанр та головна суть). "
                  f"3. Порада: Кому варто зіграти (1 речення). "
                  f"ВАЖЛИВО: Не пиши слова 'Текст:', 'Жанр:', 'Порада:'. "
                  f"Пиши звичайними літерами (без CAPS LOCK). "
                  f"Розділяй заголовок та основний текст знаком |")

        response = client.models.generate_content(model=config.MODEL_NAME, contents=prompt)

        if response and hasattr(response, 'text') and response.text:
            text = response.text.replace("*", "").replace("`", "").strip()

            if "|" in text:
                h, b = text.split("|", 1)
            else:
                h, b = "Варто глянути", text

            b = re.sub(r'^(текст|опис|порада|text|description|advice):\s*', '', b, flags=re.IGNORECASE).strip()
            h = h.strip().capitalize()
            if b:
                b = b[0].upper() + b[1:]

            return h, b
    except Exception as e:
        logging.warning(f"Gemini error: {e}")
        if retry < 2:
            time.sleep(5)
            return get_ai_content(name, discount, rating, retry + 1)

    return "Цікава пропозиція", f"🎮 {name} вже чекає на тебе у Steam!"


def _stars_for_rating(rating_percent: int) -> str:
    for threshold, stars in config.STAR_RATING_TIERS:
        if rating_percent >= threshold:
            return stars
    return config.STAR_RATING_TIERS[-1][1]


# ================= POSTING =================
def post_game():
    conn = sqlite3.connect("steam.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Pull a larger candidate pool so there's something left if some discounts expired
    c.execute("""
        SELECT * FROM games
        WHERE status='new'
        ORDER BY score DESC
        LIMIT ?
    """, (config.POST_CANDIDATE_POOL_SIZE,))
    candidates = list(c.fetchall())

    if not candidates:
        logging.info("Nothing new to post.")
        conn.close()
        return False

    random.shuffle(candidates)
    success = False

    for g in candidates:
        try:
            game_id = g['game_id']

            # 1. Verify the discount is still active before posting (region + language matter here)
            check_url = f"https://store.steampowered.com/api/appdetails?appids={game_id}&cc=UA&l=ukrainian"
            try:
                res_steam = requests.get(check_url, timeout=10).json()
            except Exception as e:
                logging.warning(f"Network error checking Steam for {g['name']}: {e}")
                continue

            if res_steam and res_steam.get(game_id, {}).get('success'):
                current_data = res_steam[game_id]['data']
                price_info = current_data.get("price_overview", {})

                # If there's no price block or the discount dropped below the threshold, it's stale
                if not price_info or price_info.get("discount_percent", 0) < config.MIN_DISCOUNT_PERCENT:
                    logging.info(f"Discount for {g['name']} has expired or is missing, marking as expired.")
                    c.execute("UPDATE games SET status='expired' WHERE game_id=?", (game_id,))
                    conn.commit()
                    continue

                # Always use live API data for the actual post, never stale DB values
                live_discount = int(price_info.get("discount_percent", 0))
                live_price = price_info.get("final", 0) / 100
            else:
                logging.warning(f"Could not fetch fresh Steam data for {g['name']}, skipping.")
                continue

            # 2. Prepare the rating block and star tier
            game_rating = g['rating_percent']
            if game_rating is None or game_rating == 0:
                game_rating = get_steam_rating(game_id)
                if game_rating is not None:
                    c.execute("UPDATE games SET rating_percent=? WHERE game_id=?", (game_rating, game_id))
                    conn.commit()

            rating_block = ""
            if game_rating:
                stars = _stars_for_rating(game_rating)
                rating_block = f"⭐ Рейтинг Steam: {stars} ({game_rating}%)\n"

            # 3. Generate the AI post text
            header, ai_text = get_ai_content(g['name'], live_discount, game_rating)

            caption = (
                f"✨ <b>{header}</b>\n\n"
                f"🎮 <b>{g['name']}</b>\n"
                f"💸 -{live_discount}% | <b>{live_price:.0f} грн</b>\n"
                f"{rating_block}\n"
                f"📝 {ai_text}\n\n"
                f"📉 <i>Це історичний мінімум вартості</i>"
            )

            # 4. Send to Telegram
            reply_markup = {"inline_keyboard": [[{"text": "🚀 Відкрити в Steam", "url": g['link']}]]}
            method = "sendVideo" if g['video'] else "sendPhoto"
            file_key = "video" if g['video'] else "photo"
            media_url = g['video'] if g['video'] else g['image']

            res_tg = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/{method}",
                data={
                    "chat_id": str(CHAT_ID).strip(),
                    file_key: media_url,
                    "caption": caption[:1024],
                    "parse_mode": "HTML",
                    "reply_markup": json.dumps(reply_markup),
                },
                timeout=60,
            )

            if res_tg.status_code == 200:
                c.execute(
                    "UPDATE games SET status='posted', last_posted=?, discount=?, price=? WHERE game_id=?",
                    (datetime.now().isoformat(), live_discount, live_price, game_id),
                )
                conn.commit()
                logging.info(f"Posted with live price: {g['name']} (-{live_discount}%)")
                success = True
                break
            else:
                logging.error(f"Telegram error ({res_tg.status_code}): {res_tg.text}")
                c.execute("UPDATE games SET status='failed' WHERE game_id=?", (game_id,))
                conn.commit()
                time.sleep(5)

        except Exception as e:
            logging.error(f"Critical error processing {g['name']}: {e}")
            time.sleep(2)
            continue

    conn.close()
    return success


# ================= MAIN LOOP =================
def main():
    init_db()
    logging.info("Bot started")

    today_start_hour = config.DAILY_POST_WINDOW_START_HOUR
    today_start_minute = random.randint(0, 30)
    logging.info(f"Today's posting window opens after {today_start_hour:02d}:{today_start_minute:02d}")

    while True:
        now = datetime.now()
        cur_time = now.strftime("%H:%M")

        conn = sqlite3.connect("steam.db")
        try:
            last_scan_row = conn.execute("SELECT value FROM stats WHERE key='last_full_scan'").fetchone()
        except sqlite3.OperationalError:
            last_scan_row = None
        conn.close()

        do_scan = False
        if not last_scan_row:
            do_scan = True
        else:
            last_scan_dt = datetime.fromisoformat(last_scan_row[0])
            reset_time_str = f"{config.FULL_SCAN_DAILY_RESET_HOUR:02d}:05"
            if cur_time >= reset_time_str:
                today_limit = now.replace(hour=config.FULL_SCAN_DAILY_RESET_HOUR, minute=0, second=0)
                if last_scan_dt < today_limit:
                    do_scan = True
            elif (now - last_scan_dt).total_seconds() > 24 * 3600:
                do_scan = True

        if do_scan:
            try:
                raw_games = fetch_steam()
                processed_games = [norm(g) for g in raw_games if norm(g)]
                added = save_games(processed_games)
                logging.info(f"Database updated (added: {added})")

                conn = sqlite3.connect("steam.db")
                conn.execute("INSERT OR REPLACE INTO stats (key, value) VALUES ('last_full_scan', ?)", (now.isoformat(),))
                conn.commit()
                conn.close()
            except Exception as e:
                logging.error(f"Scan failed: {e}")

        # --- POSTING LOGIC ---
        conn = sqlite3.connect("steam.db")
        try:
            last_post_row = conn.execute("SELECT value FROM stats WHERE key='last'").fetchone()
        except Exception:
            last_post_row = None
        conn.close()

        interval_seconds = random.randint(
            config.POST_INTERVAL_MIN_MINUTES, config.POST_INTERVAL_MAX_MINUTES
        ) * 60

        if not last_post_row or (now - datetime.fromisoformat(last_post_row[0])).total_seconds() > interval_seconds:
            start_time = now.replace(hour=today_start_hour, minute=today_start_minute, second=0)
            end_time = now.replace(hour=config.DAILY_POST_WINDOW_END_HOUR, minute=0, second=0)
            if start_time <= now < end_time:
                if post_game():
                    conn = sqlite3.connect("steam.db")
                    conn.execute("INSERT OR REPLACE INTO stats (key, value) VALUES ('last', ?)", (datetime.now().isoformat(),))
                    conn.commit()
                    conn.close()

                    today_start_minute = random.randint(0, 30)
                    logging.info(f"Post published. Next window opens tomorrow at 09:{today_start_minute:02d}")

        time.sleep(60)


if __name__ == "__main__":
    main()