import time
import random
import requests
import sqlite3
import logging
import re
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from google import genai

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
    logging.info("✅ Gemini API підключено")
else:
    logging.error("❌ GEMINI_API_KEY не знайдено!")

MODEL_NAME = "gemini-2.5-flash" 

AI_STYLES = [
    {"role": "геймер-аналітик", "mood": "чітко, з акцентом на жанр та механіки"},
    {"role": "ігровий гід", "mood": "дружньо, дає конкретну пораду, кому гра сподобається"},
    {"role": "твій бро-геймер", "mood": "простою мовою пояснює суть гри та її фішки"}
]

BLOCK_LIST = ["hentai", "nudity", "sexual", "puzzle for adults", "artbook", "soundtrack"]

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("steam.db")
    c = conn.cursor()

    # Повністю оновлена таблиця з колонкою genres
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

# ================= SCORING (З МНОЖНИКАМИ ЖАНРІВ) =================
def calc_score(discount, name, price, rating, genres_str):
    boost = 0
    name_lower = name.lower()
    genres_lower = genres_str.lower() if genres_str else ""
    
    hot_brands = {
        "witcher", "cyberpunk", "stalker", "metro", "gta", "red dead", "baldurs gate", 
        "elden ring", "dark souls", "sekiro", "bloodborne", "lies of p", "god of war", 
        "nier:automata", "horizon", "ghost of tsushima", "days gone", "death stranding", 
        "spider-man", "star wars", "final fantasy", "hogwarts", "fallout", "skyrim", 
        "elder scrolls", "starfield", "mass effect", "dragon age", "battlefield", 
        "call of duty", "far cry", "resident evil", "devil may cry", "doom", 
        "halflife", "bioshock", "dying light", "borderlands", "hitman", "mafia", 
        "payday", "helldivers", "rainbow six", "siege", "ready or not", "total war", 
        "civilization", "hearts of iron", "crusader kings", "stellaris", "manor lords", 
        "frostpunk", "bannerlord", "forza", "need for speed", "euro truck", "sims", 
        "hades", "vampire survivors", "hollow knight", "dead cells", "terraria", 
        "stardew valley", "balatro", "slay the spire", "outer wilds", "inscryption", 
        "cult of the lamb", "dave the diver", "project zomboid", "valheim", "rust", 
        "no mans sky", "subnautica", "the forest", "rimworld", "detroit become human", 
        "persona 5", "yakuza", "like a dragon", "it takes two", "cuphead", "nba"
    }
    
    is_hot = any(brand in name_lower for brand in hot_brands)
    if is_hot:
        boost += 150 

    # 2. Обробка рейтингу Steam (КРИТИЧНО: тепер він має величезну вагу)
    # Якщо рейтинг прийшов як рядок "91%", очищуємо його до числа 91
    try:
        clean_rating = int(str(rating).replace('%', '').strip())
    except Exception:
        clean_rating = 75  # Дефолтне значення, якщо сталася помилка
        
    # Додаємо бали за якість гри (від 0 до 120 балів)
    boost += (clean_rating * 1.2)

    # 3. Розумні бонуси за ціну та знижку
    if discount >= 85 and price > 80: 
        boost += 40  # Бонус за супер-знижку даємо тільки якщо це не копійчаний смітник
        
    if 80 <= price < 250: 
        boost += 30  # Бонус за хорошу "адекватну" ціну для нормальних ігор

    # 4. ШТРАФ ЗА ДЕШЕВИЙ ТРЕШ
    # Якщо гра коштує менше 45 грн і це НЕ відомий бренд із hot_brands — жорстко ріжемо її рейтинг
    if price < 45 and not is_hot:
        boost -= 120 

    # Базовий розрахунок балів (знижка дає плавний приріст, а не вирішальний)
    score = (discount * 1.0) + boost + random.randint(0, 15)
    
    # --- 5. КОЕФІЦІЄНТИ ЖАНРІВ (Твоє жорстке гальмування) ---
    slow_genres = ["strategy", "simulation", "management", "city builder", "casual", "стратегия", "симулятор"]
    fast_genres = ["action", "horror", "shooter", "rpg", "adventure", "екшн", "рольова"]

    check_area = f"{name_lower} {genres_lower}"

    if any(m in check_area for m in slow_genres):
        score = score * 0.4  # Стратегії та симулятори летять на дно
        
    if any(m in check_area for m in fast_genres):
        score = score * 1.2  # Екшни та РПГ отримують легкий приємний буст

    return score

# ================= STEAM RATING =================
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

# ================= STEAM LOGIC =================
def fetch_steam():
    all_ids = []
    logging.info("🌍 Збір ID...")
    for page in range(1, 21):
        try:
            url = f"https://store.steampowered.com/search/results/?query&start={(page-1)*50}&count=50&specials=1&cc=UA&infinite=1"
            r = requests.get(url, timeout=15).json()
            found_ids = re.findall(r'data-ds-appid="(\d+)"', r.get('results_html', ''))
            if not found_ids: break
            all_ids.extend(found_ids)
            time.sleep(0.5)
        except: break

    final_data = []
    process_limit = min(len(all_ids), 500)
    for i, gid in enumerate(all_ids[:process_limit]):
        try:
            res = requests.get(f"https://store.steampowered.com/api/appdetails?appids={gid}&cc=UA&l=ukrainian", timeout=10).json()
            if res and res.get(gid, {}).get('success'):
                data = res[gid]['data']
                
                check_str = (data.get('name', '') + data.get('short_description', '')).lower()
                if any(word in check_str for word in BLOCK_LIST):
                    continue

                if data.get('type') == 'game' and data.get('header_image'):
                    final_data.append(data)
            time.sleep(0.7)
            if (i + 1) % 50 == 0: time.sleep(15)
        except: continue
    return final_data

def norm(g):
    try:
        price_data = g.get("price_overview", {})
        if not price_data or price_data.get("discount_percent", 0) < 35:
            return None

        gid = str(g.get("steam_appid"))
        rating = get_steam_rating(gid)

        video_url = None
        movies = g.get("movies")
        if movies:
            video_url = movies[0].get("mp4", {}).get("max")

        # [НОВЕ] Витягуємо текстові назви жанрів
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
            "genres": genres_str, # Зберігаємо рядок жанрів (напр. "Action, RPG")
            "link": f"https://store.steampowered.com/app/{gid}"
        }
    except:
        return None

def save_games(games):
    conn = sqlite3.connect("steam.db")
    c = conn.cursor()

    added = 0
    now = datetime.now().isoformat()

    for g in games:
        if not g: continue

        # Вираховуємо score на льоту за новою логікою
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
    if not GEMINI_KEY: 
        return "Гарна пропозиція", f"🔥 {name} за супер ціною!"
    try:
        time.sleep(2) 
        style = random.choice(AI_STYLES)
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
        
        response = client.models.generate_content(model=MODEL_NAME, contents=prompt)
        
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
        logging.warning(f"⚠️ Gemini error: {e}")
        if retry < 2:
            time.sleep(5)
            return get_ai_content(name, discount, rating, retry + 1)
    
    return "Цікава пропозиція", f"🎮 {name} вже чекає на тебе у Steam!"

# ================= POSTING =================
def post_game():
    conn = sqlite3.connect("steam.db")
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Беремо топ-50 кандидатів, щоб було з чого вибирати в разі застарілих знижок
    c.execute("""
        SELECT * FROM games 
        WHERE status='new' 
        ORDER BY score DESC 
        LIMIT 50
    """)
    candidates = list(c.fetchall())

    if not candidates:
        logging.info("Нічого нового для публікації.")
        conn.close()
        return False

    random.shuffle(candidates)
    success = False

    for g in candidates:
        try:
            game_id = g['game_id']
            
            # --- 1. ПЕРЕВІРКА АКТУАЛЬНОСТІ ЦІНИ (Обов'язково з регіоном та мовою) ---
            check_url = f"https://store.steampowered.com/api/appdetails?appids={game_id}&cc=UA&l=ukrainian"
            try:
                res_steam = requests.get(check_url, timeout=10).json()
            except Exception as e:
                logging.warning(f"⚠️ Помилка мережі при перевірці Steam для {g['name']}: {e}")
                continue

            if res_steam and res_steam.get(game_id, {}).get('success'):
                current_data = res_steam[game_id]['data']
                price_info = current_data.get("price_overview", {})
                
                # КРИТИЧНО: Якщо блоку цін немає або знижка впала нижче 35% — гра застаріла!
                if not price_info or price_info.get("discount_percent", 0) < 35:
                    logging.info(f"⏭️ Знижка на {g['name']} закінчилася (або відсутня). Маркуємо як expired.")
                    c.execute("UPDATE games SET status='expired' WHERE game_id=?", (game_id,))
                    conn.commit()
                    continue 
                
                # БЕРЕМО ДАНІ ТІЛЬКИ З ЖИВОГО API, А НЕ З БАЗИ!
                live_discount = int(price_info.get("discount_percent", 0))
                live_price = price_info.get("final", 0) / 100
            else:
                logging.warning(f"⚠️ Не вдалося отримати свіжі дані з Steam API для {g['name']}, пропускаємо.")
                continue

            # --- 2. ПІДГОТОВКА РЕЙТИНГУ ТА СУВЕНІРНИХ ЗІРОЧОК ---
            game_rating = g['rating_percent']
            if game_rating is None or game_rating == 0:
                game_rating = get_steam_rating(game_id)
                if game_rating is not None:
                    c.execute("UPDATE games SET rating_percent=? WHERE game_id=?", (game_rating, game_id))
                    conn.commit()

            rating_block = ""
            if game_rating:
                # Справедливе округлення зірочок (90%+ — це 5 зірок)
                if game_rating >= 88:
                    stars = "⭐⭐⭐⭐⭐"
                elif game_rating >= 70:
                    stars = "⭐⭐⭐⭐"
                elif game_rating >= 50:
                    stars = "⭐⭐⭐"
                elif game_rating >= 30:
                    stars = "⭐⭐"
                else:
                    stars = "⭐"
                rating_block = f"⭐ Рейтинг Steam: {stars} ({game_rating}%)\n"

            # --- 3. ГЕНЕРАЦІЯ ШІ-ТЕКСТУ ---
            header, ai_text = get_ai_content(g['name'], live_discount, game_rating)
            
            caption = (
                f"✨ <b>{header}</b>\n\n"
                f"🎮 <b>{g['name']}</b>\n"
                f"💸 -{live_discount}% | <b>{live_price:.0f} грн</b>\n"
                f"{rating_block}\n"
                f"📝 {ai_text}\n\n"
                f"📉 <i>Це історичний мінімум вартості</i>"
            )

            # --- 4. ВІДПРАВКА В TELEGRAM ---
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
                    "reply_markup": json.dumps(reply_markup)
                },
                timeout=60
            )

            if res_tg.status_code == 200:
                c.execute("UPDATE games SET status='posted', last_posted=?, discount=?, price=? WHERE game_id=?", 
                          (datetime.now().isoformat(), live_discount, live_price, game_id))
                conn.commit()
                logging.info(f"✅ Опубліковано з актуальною ціною: {g['name']} (-{live_discount}%)")
                success = True
                break 
            else:
                logging.error(f"❌ Telegram error ({res_tg.status_code}): {res_tg.text}")
                c.execute("UPDATE games SET status='failed' WHERE game_id=?", (game_id,))
                conn.commit()
                time.sleep(5)

        except Exception as e:
            logging.error(f"⚠️ Критична помилка при обробці {g['name']}: {e}")
            time.sleep(2)
            continue

    conn.close()
    return success

# ================= MAIN LOOP =================
def main():
    init_db()
    logging.info("🚀 Бот запущений з чистою структурою жанрів")

    today_start_hour = 9
    today_start_minute = random.randint(0, 30)
    logging.info(f"📅 Сьогодні публікації почнуться після {today_start_hour:02d}:{today_start_minute:02d}")

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
            if cur_time >= "20:05":
                today_limit = now.replace(hour=20, minute=0, second=0)
                if last_scan_dt < today_limit:
                    do_scan = True
            elif (now - last_scan_dt).total_seconds() > 24 * 3600:
                do_scan = True

        if do_scan:
            try:
                raw_games = fetch_steam()
                processed_games = [norm(g) for g in raw_games if norm(g)]
                added = save_games(processed_games)
                logging.info(f"📥 База оновлена (Додано: {added})")
                
                conn = sqlite3.connect("steam.db")
                conn.execute("INSERT OR REPLACE INTO stats (key, value) VALUES ('last_full_scan', ?)", (now.isoformat(),))
                conn.commit()
                conn.close()
            except Exception as e:
                logging.error(f"❌ Помилка при скануванні: {e}")

        # --- ЛОГІКА ПОСТУ ---
        conn = sqlite3.connect("steam.db")
        try:
            last_post_row = conn.execute("SELECT value FROM stats WHERE key='last'").fetchone()
        except:
            last_post_row = None
        conn.close()
        
        if not last_post_row or (now - datetime.fromisoformat(last_post_row[0])).total_seconds() > (random.randint(180, 240) * 60):
            start_time = now.replace(hour=today_start_hour, minute=today_start_minute, second=0)
            if start_time <= now < now.replace(hour=23, minute=0, second=0):
                if post_game():
                    conn = sqlite3.connect("steam.db")
                    conn.execute("INSERT OR REPLACE INTO stats (key, value) VALUES ('last', ?)", (datetime.now().isoformat(),))
                    conn.commit()
                    conn.close()
                    
                    today_start_minute = random.randint(0, 30)
                    logging.info(f"✅ Пост зроблено. Наступного ранку почнемо о 09:{today_start_minute:02d}")

        time.sleep(60)

if __name__ == "__main__":
    main()