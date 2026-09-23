"""
Configuration constants for the Steam Signal bot.
Keeping these separate from main.py makes it easy to tune scoring
and content rules without touching the core logic.
"""

MODEL_NAME = "gemini-2.5-flash"

# Minimum discount percentage required for a game to be tracked / reposted
MIN_DISCOUNT_PERCENT = 35

# AI writing personas used to vary the tone of generated post text
AI_STYLES = [
    {"role": "gamer-analyst", "mood": "clear and concise, focused on genre and mechanics"},
    {"role": "game guide", "mood": "friendly, gives a concrete recommendation on who would enjoy it"},
    {"role": "your gamer buddy", "mood": "casual language explaining the game's core appeal"},
]

# Content that should never be posted to the channel
BLOCK_LIST = ["hentai", "nudity", "sexual", "puzzle for adults", "artbook", "soundtrack"]

# Well-known franchises that get a scoring boost (higher engagement potential)
HOT_BRANDS = {
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
    "persona 5", "yakuza", "like a dragon", "it takes two", "cuphead", "nba",
}

# Genres that get deprioritized / boosted in the scoring algorithm
SLOW_GENRES = ["strategy", "simulation", "management", "city builder", "casual", "стратегия", "симулятор"]
FAST_GENRES = ["action", "horror", "shooter", "rpg", "adventure", "екшн", "рольова"]

# --- Scoring weights ---
BRAND_BOOST = 150
DEFAULT_RATING_IF_UNKNOWN = 75      # used if the rating value can't be parsed
RATING_WEIGHT = 1.2                 # multiplier applied to the cleaned 0-100 rating

HIGH_DISCOUNT_THRESHOLD = 85
HIGH_DISCOUNT_MIN_PRICE = 80        # super-discount bonus only applies above this price
HIGH_DISCOUNT_BOOST = 40

FAIR_PRICE_RANGE = (80, 250)        # (min, max) UAH range considered "reasonable" for full-price games
FAIR_PRICE_BOOST = 30

LOW_PRICE_JUNK_THRESHOLD = 45       # below this price, non-brand games are treated as junk
LOW_PRICE_JUNK_PENALTY = -120

BASE_DISCOUNT_WEIGHT = 1.0
RANDOM_JITTER_MAX = 15              # small randomness so identical scores don't always tie the same way

SLOW_GENRE_MULTIPLIER = 0.4
FAST_GENRE_MULTIPLIER = 1.2

# --- Posting behaviour ---
POST_CANDIDATE_POOL_SIZE = 50       # how many top-scoring "new" games to pick a candidate from
DAILY_POST_WINDOW_START_HOUR = 9
DAILY_POST_WINDOW_END_HOUR = 23
POST_INTERVAL_MIN_MINUTES = 180
POST_INTERVAL_MAX_MINUTES = 240
FULL_SCAN_DAILY_RESET_HOUR = 20

# Star rating tiers: (minimum_rating_percent, stars)
STAR_RATING_TIERS = [
    (88, "⭐⭐⭐⭐⭐"),
    (70, "⭐⭐⭐⭐"),
    (50, "⭐⭐⭐"),
    (30, "⭐⭐"),
    (0, "⭐"),
]