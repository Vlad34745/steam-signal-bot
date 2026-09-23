"""
Gemini-powered post text generation, with a static fallback when the API
key is missing or the call fails after retries.
"""
import logging
import random
import re
import time

from bot import config

FALLBACK_HEADER = "Цікава пропозиція"
FALLBACK_BODY_TEMPLATE = "🎮 {name} вже чекає на тебе у Steam!"
NO_KEY_HEADER = "Гарна пропозиція"
NO_KEY_BODY_TEMPLATE = "🔥 {name} за супер ціною!"

_LABEL_PREFIX_RE = re.compile(r'^(текст|опис|порада|text|description|advice):\s*', re.IGNORECASE)


def _build_prompt(name: str, discount: int, rating, style: dict) -> str:
    rating_info = f"Рейтинг Steam: {rating}%." if rating else "Рейтинг поки невідомий."
    return (f"Гра: '{name}' (-{discount}%). {rating_info} "
            f"Твоя роль: {style['role']}. {style['mood']}. "
            f"Напиши пост за таким планом: "
            f"1. Короткий заголовок (до 3 слів). "
            f"2. Опис: 1 речення (жанр та головна суть). "
            f"3. Порада: Кому варто зіграти (1 речення). "
            f"ВАЖЛИВО: Не пиши слова 'Текст:', 'Жанр:', 'Порада:'. "
            f"Пиши звичайними літерами (без CAPS LOCK). "
            f"Розділяй заголовок та основний текст знаком |")


def _parse_response_text(text: str):
    text = text.replace("*", "").replace("`", "").strip()
    if "|" in text:
        h, b = text.split("|", 1)
    else:
        h, b = "Варто глянути", text
    b = _LABEL_PREFIX_RE.sub('', b).strip()
    h = h.strip().capitalize()
    if b:
        b = b[0].upper() + b[1:]
    return h, b


def get_ai_content(name, discount, rating=None, client=None, retry=0, sleep_fn=time.sleep, max_retries=2):
    """
    Generates a short Ukrainian-language promo post via Gemini.
    Falls back to a static template if no client is configured or the call
    keeps failing after ``max_retries`` retries.
    """
    if client is None:
        return NO_KEY_HEADER, NO_KEY_BODY_TEMPLATE.format(name=name)

    try:
        sleep_fn(2)
        style = random.choice(config.AI_STYLES)
        prompt = _build_prompt(name, discount, rating, style)
        response = client.models.generate_content(model=config.MODEL_NAME, contents=prompt)
        if response and getattr(response, 'text', None):
            return _parse_response_text(response.text)
    except Exception as e:
        logging.warning(f"Gemini error: {e}")

    if retry < max_retries:
        sleep_fn(5)
        return get_ai_content(name, discount, rating, client=client, retry=retry + 1,
                               sleep_fn=sleep_fn, max_retries=max_retries)
    return FALLBACK_HEADER, FALLBACK_BODY_TEMPLATE.format(name=name)
