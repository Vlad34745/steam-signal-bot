"""
All Steam Store API access: collecting discounted appids, fetching
appdetails, review ratings, and normalizing raw payloads into the app's
internal game dict shape.
"""
import logging
import re
import time

import requests

from bot import config


def get_steam_rating(appid, session: requests.Session = requests):
    """Returns an integer 0-100 positive-review percentage, or None if unavailable."""
    try:
        url = f"https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all"
        r = session.get(url, timeout=10).json()
        summary = r.get("query_summary", {})
        total = summary.get("total_reviews", 0)
        positive = summary.get("total_positive", 0)
        if total > 0:
            return int((positive / total) * 100)
    except Exception as e:
        logging.warning(f"Rating error {appid}: {e}")
    return None


def collect_discounted_appids(session: requests.Session = requests, max_pages: int = 20, sleep_fn=time.sleep):
    """Paginates the Steam specials search until a page comes back empty."""
    all_ids = []
    logging.info("Collecting discounted game IDs from Steam...")
    for page in range(1, max_pages + 1):
        try:
            url = (f"https://store.steampowered.com/search/results/?query&start={(page - 1) * 50}"
                   f"&count=50&specials=1&cc=UA&infinite=1")
            r = session.get(url, timeout=15).json()
            found_ids = re.findall(r'data-ds-appid="(\d+)"', r.get('results_html', ''))
            if not found_ids:
                break
            all_ids.extend(found_ids)
            sleep_fn(0.5)
        except Exception as e:
            logging.warning(f"Failed to collect IDs on page {page}: {e}")
            break
    return all_ids


def fetch_appdetails(appid, session: requests.Session = requests):
    """Fetches raw Steam appdetails JSON for one appid, or None on failure/no data."""
    try:
        res = session.get(
            f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=UA&l=ukrainian",
            timeout=10,
        ).json()
        if res and res.get(str(appid), {}).get('success'):
            return res[str(appid)]['data']
    except Exception:
        pass
    return None


def is_blocked(data: dict) -> bool:
    check_str = (data.get('name', '') + data.get('short_description', '')).lower()
    return any(word in check_str for word in config.BLOCK_LIST)


def fetch_steam(session: requests.Session = requests, sleep_fn=time.sleep):
    """Collects discounted appids, then fetches+filters appdetails for each. Returns raw payloads."""
    all_ids = collect_discounted_appids(session=session, sleep_fn=sleep_fn)
    final_data = []
    process_limit = min(len(all_ids), 500)
    logging.info(f"Found {len(all_ids)} discounted game IDs, checking details for {process_limit} of them...")
    for i, gid in enumerate(all_ids[:process_limit]):
        data = fetch_appdetails(gid, session=session)
        if data and not is_blocked(data) and data.get('type') == 'game' and data.get('header_image'):
            final_data.append(data)
        sleep_fn(0.7)
        if (i + 1) % 50 == 0:
            # Without this, a scan of 300-500 games prints nothing for several minutes
            # straight and looks hung even though it's just rate-limiting itself.
            logging.info(f"Processed {i + 1}/{process_limit} games... ({len(final_data)} qualified so far)")
            sleep_fn(15)
    logging.info(f"Fetch complete: {len(final_data)} games qualified out of {process_limit} checked.")
    return final_data


def norm(g: dict, session: requests.Session = requests):
    """Normalizes a raw Steam appdetails payload into the app's internal game format.

    Returns None if the game doesn't meet the minimum-discount bar or the
    payload is malformed. Called exactly once per game by the caller - the
    previous version called norm() twice per game inside a list
    comprehension (``[norm(g) for g in games if norm(g)]``), which doubled
    every get_steam_rating() network call.
    """
    try:
        price_data = g.get("price_overview", {})
        if not price_data or price_data.get("discount_percent", 0) < config.MIN_DISCOUNT_PERCENT:
            return None

        gid = str(g.get("steam_appid"))
        rating = get_steam_rating(gid, session=session)

        video_url = None
        movies = g.get("movies")
        if movies:
            video_url = movies[0].get("mp4", {}).get("max")

        genres_list = g.get("genres", [])
        genres_str = ", ".join(genre.get("description", "") for genre in genres_list)

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


def normalize_all(raw_games, session: requests.Session = requests):
    """Normalizes a list of raw appdetails payloads, dropping the ones that don't qualify."""
    return [normalized for normalized in (norm(g, session=session) for g in raw_games) if normalized is not None]


def check_live_price(game_id: str, session: requests.Session = requests):
    """Re-fetches a game's current price/discount from Steam. Returns (discount, price) or None if stale/unavailable."""
    data = fetch_appdetails(game_id, session=session)
    if not data:
        return None
    price_info = data.get("price_overview", {})
    if not price_info or price_info.get("discount_percent", 0) < config.MIN_DISCOUNT_PERCENT:
        return None
    return int(price_info.get("discount_percent", 0)), price_info.get("final", 0) / 100
