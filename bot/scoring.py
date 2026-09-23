"""
Deal scoring logic.

Kept free of any network/DB calls on purpose: every function here is a pure
function of its inputs, which is what makes 100% test coverage realistic.
"""
import random

from bot import config


def calc_score(discount: int, name: str, price: float, rating, genres_str: str) -> float:
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
    except (TypeError, ValueError):
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


def stars_for_rating(rating_percent: int) -> str:
    """Maps a 0-100 Steam rating percentage to a star-tier string from config."""
    for threshold, stars in config.STAR_RATING_TIERS:
        if rating_percent >= threshold:
            return stars
    return config.STAR_RATING_TIERS[-1][1]
