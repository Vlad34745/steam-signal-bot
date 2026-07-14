# 🚀 Steam Signal Telegram Bot

An automated Telegram bot that monitors and analyzes the Steam game market, selects the best deals using a custom scoring algorithm, and publishes smart posts with AI-generated descriptions.

## 🛠 Tech Stack
* **Programming Language:** Python
* **Database:** SQLite, used to track scan history, deduplicate games, and store per-game state (new / posted / expired)
* **Integrations:** Steam API, Google Gemini API (`gemini-2.5-flash` model), Telegram Bot API
* **Libraries & Packages:** `requests`, `python-dotenv`, `google-genai`

## 📊 Key Analytical & Technical Features

1. **Dynamic Scoring Algorithm:** A custom weight-based scoring system evaluates the overall value of each deal, combining brand recognition, Steam rating, price sanity checks, and discount size. Smart multipliers reduce the priority of genres like strategy or simulation when they'd flood the queue, and boost fast-paced genres like action or RPG — keeping the content mix balanced for subscribers.
2. **Data Validation & Cleaning:** An automated pipeline fetches data from the Steam API, deduplicates entries via SQLite, tracks historical prices, and safely handles API failures and malformed responses without crashing the scan.
3. **Live Price Verification:** Before publishing, the bot re-checks the game's current price and discount directly against the Steam API rather than relying on potentially stale database values, so subscribers never see an expired deal.
4. **Smart Posting Schedule:** Flexible timer logic randomizes posting times within a daily window to mimic organic behavior, while respecting Telegram API limits when sending media-heavy content (photos/videos).

## 🚀 How to Run Locally

1. Clone the repository:
   ```bash
   git clone https://github.com/Vlad34745/steam-signal-bot.git
   cd steam-signal-bot
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file based on `.env.example` and fill in your credentials:
   ```
   TOKEN=your_telegram_bot_token
   CHAT_ID=your_channel_or_chat_id
   GEMINI_API_KEY=your_gemini_api_key
   ```

4. Run the bot:
   ```bash
   python main.py
   ```

Configuration values such as scoring weights, blocked keywords, and posting schedule can be tuned in `config.py` without touching the core logic.