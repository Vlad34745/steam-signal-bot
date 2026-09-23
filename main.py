"""
Entry point. Kept intentionally thin: env/logging setup, then hands off to
bot.runner.main(). All the testable logic lives inside the bot/ package.
"""
import logging
import os

from dotenv import load_dotenv
from google import genai

from bot.runner import main as run_bot

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
    ai_client = genai.Client(api_key=GEMINI_KEY)
    logging.info("Gemini API connected")
else:
    ai_client = None
    logging.error("GEMINI_API_KEY not found!")

if __name__ == "__main__":
    if not TOKEN or not CHAT_ID:
        raise SystemExit("TOKEN and CHAT_ID must be set in the environment (.env)")
    run_bot(TOKEN, CHAT_ID, ai_client=ai_client)
