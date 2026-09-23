"""
Telegram Bot API client: publishing a game post (photo/video + caption) and
sending plain-text alerts (e.g. the "bot's gone quiet" self-alert).

Handles HTTP 429 ("Too Many Requests") the way the Bot API expects: it
returns a JSON body with parameters.retry_after (seconds to wait), so we
sleep exactly that long and retry, instead of treating it as a hard failure
like the previous version did.
"""
import json
import logging
import time

import requests

TELEGRAM_API_BASE = "https://api.telegram.org"


def build_caption(header: str, name: str, live_discount: int, live_price: float, rating_block: str,
                   ai_text: str, is_historic_low: bool = False) -> str:
    # Only claim a historic low when it's actually true for prices this bot has observed -
    # previously this line was shown unconditionally on every post, which was misleading.
    footer = "\n\n📉 <i>Це найнижча ціна, яку бот бачив на цю гру</i>" if is_historic_low else ""
    return (
        f"✨ <b>{header}</b>\n\n"
        f"🎮 <b>{name}</b>\n"
        f"💸 -{live_discount}% | <b>{live_price:.0f} грн</b>\n"
        f"{rating_block}\n"
        f"📝 {ai_text}"
        f"{footer}"
    )


def _post_with_429_retry(url: str, payload: dict, session: requests.Session, sleep_fn, max_429_retries: int):
    """Shared HTTP-post-with-429-backoff logic used by both send_post and send_text."""
    attempts = 0
    while True:
        try:
            res = session.post(url, data=payload, timeout=60)
        except Exception as e:
            logging.warning(f"Telegram network error: {e}")
            return None

        if res.status_code == 429 and attempts < max_429_retries:
            retry_after = 5
            try:
                retry_after = res.json().get("parameters", {}).get("retry_after", 5)
            except Exception:
                pass
            logging.warning(f"Telegram rate limit hit, waiting {retry_after}s before retry.")
            sleep_fn(retry_after)
            attempts += 1
            continue

        return res


def send_post(token: str, chat_id: str, caption: str, image: str, video: str, link: str,
              session: requests.Session = requests, sleep_fn=time.sleep, max_429_retries: int = 3):
    """
    Sends a photo or video post with an inline "Open in Steam" button.
    Returns the final requests.Response (or None if the request itself
    raised, e.g. a connection error).
    """
    reply_markup = {"inline_keyboard": [[{"text": "🚀 Відкрити в Steam", "url": link}]]}
    method = "sendVideo" if video else "sendPhoto"
    file_key = "video" if video else "photo"
    media_url = video if video else image

    payload = {
        "chat_id": str(chat_id).strip(),
        file_key: media_url,
        "caption": caption[:1024],
        "parse_mode": "HTML",
        "reply_markup": json.dumps(reply_markup),
    }
    return _post_with_429_retry(f"{TELEGRAM_API_BASE}/bot{token}/{method}",
                                 payload, session, sleep_fn, max_429_retries)


def send_text(token: str, chat_id: str, text: str,
              session: requests.Session = requests, sleep_fn=time.sleep, max_429_retries: int = 3):
    """
    Sends a plain text message (used for the "bot's gone quiet" self-alert,
    not for game posts). Returns the final requests.Response, or None if the
    request itself raised.
    """
    payload = {"chat_id": str(chat_id).strip(), "text": text[:4096]}
    return _post_with_429_retry(f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
                                 payload, session, sleep_fn, max_429_retries)
