from bot import config
from bot.scoring import calc_score, stars_for_rating


def test_brand_boost_applied_for_known_franchise():
    boosted = calc_score(discount=50, name="The Witcher 3", price=200, rating=90, genres_str="RPG")
    plain = calc_score(discount=50, name="Some Random Game", price=200, rating=90, genres_str="RPG")
    assert boosted > plain


def test_unknown_rating_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(config, "RANDOM_JITTER_MAX", 0)
    # price=300 deliberately sits outside FAIR_PRICE_RANGE and above the high-discount
    # price floor but discount=50 is below HIGH_DISCOUNT_THRESHOLD, so no price bonus applies -
    # isolates the "unknown rating -> DEFAULT_RATING_IF_UNKNOWN" behaviour being tested.
    score = calc_score(discount=50, name="No Rating Game", price=300, rating=None, genres_str="")
    expected_boost = config.DEFAULT_RATING_IF_UNKNOWN * config.RATING_WEIGHT
    assert score == 50 * config.BASE_DISCOUNT_WEIGHT + expected_boost


def test_rating_string_with_percent_sign_is_parsed():
    monkey_score = calc_score(discount=10, name="X", price=10, rating="77%", genres_str="")
    numeric_score = calc_score(discount=10, name="X", price=10, rating=77, genres_str="")
    # both should land in the same ballpark (jitter aside); compare the deterministic component
    assert round(monkey_score) - round(numeric_score) in range(-config.RANDOM_JITTER_MAX, config.RANDOM_JITTER_MAX + 1)


def test_high_discount_bonus_requires_price_above_threshold():
    monkey_high_price = calc_score(discount=90, name="Deal", price=100, rating=50, genres_str="")
    monkey_low_price = calc_score(discount=90, name="Deal", price=10, rating=50, genres_str="")
    # low price + non-brand also triggers the junk penalty, so it should score much lower
    assert monkey_low_price < monkey_high_price


def test_cheap_non_brand_game_gets_junk_penalty():
    cheap = calc_score(discount=50, name="Random Asset Flip", price=20, rating=50, genres_str="")
    normal = calc_score(discount=50, name="Random Asset Flip", price=150, rating=50, genres_str="")
    assert cheap < normal


def test_cheap_brand_game_is_exempt_from_junk_penalty():
    cheap_brand = calc_score(discount=50, name="Terraria", price=20, rating=50, genres_str="")
    cheap_other = calc_score(discount=50, name="Random Asset Flip", price=20, rating=50, genres_str="")
    assert cheap_brand > cheap_other


def test_slow_genre_multiplier_reduces_score():
    monkeypatch_score_strategy = calc_score(discount=50, name="Some City Builder", price=150, rating=50, genres_str="Strategy")
    monkeypatch_score_plain = calc_score(discount=50, name="Some Plain Game", price=150, rating=50, genres_str="")
    assert monkeypatch_score_strategy < monkeypatch_score_plain


def test_fast_genre_multiplier_increases_score():
    action_score = calc_score(discount=50, name="Some Shooter", price=150, rating=50, genres_str="Action")
    plain_score = calc_score(discount=50, name="Some Plain Game", price=150, rating=50, genres_str="")
    assert action_score > plain_score


def test_stars_for_rating_tiers():
    assert stars_for_rating(95) == "⭐⭐⭐⭐⭐"
    assert stars_for_rating(88) == "⭐⭐⭐⭐⭐"
    assert stars_for_rating(75) == "⭐⭐⭐⭐"
    assert stars_for_rating(55) == "⭐⭐⭐"
    assert stars_for_rating(35) == "⭐⭐"
    assert stars_for_rating(5) == "⭐"
    assert stars_for_rating(0) == "⭐"
