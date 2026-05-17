# 🚀 Steam Signal Telegram Bot

An automated Telegram bot that monitors and analyzes the Steam game market, selects the best deals using a custom scoring algorithm, and publishes smart posts with AI-generated descriptions.

## 🛠 Tech Stack
* **Programming Language:** Python
* **Database:** SQLite (efficient architecture optimized for tracking genre limits and scan history)
* **Integrations:** Steam API, Google Gemini API (`gemini-2.5-flash` model)
* **Libraries & Packages:** `requests`, `python-dotenv`, `google-genai`

## 📊 Key Analytical & Technical Features
1. **Dynamic Scoring Algorithm:** Implemented a custom weight-based scoring system to evaluate the overall value of game discounts. To enhance content diversity and prevent channel fatigue, smart multipliers are applied to specific tags (e.g., automatically lowering the priority of strategy or simulation games if they flood the queue), maintaining an optimal content mix for subscribers.
2. **Data Validation & Cleaning:** Automated pipeline to fetch data from Steam, filtering out duplicates via the SQLite backend, tracking historical low prices, and safely handling API exceptions.
3. **Smart Posting Schedule:** A flexible timer logic featuring built-in post time randomization to mimic organic human behavior (anti-bot protection) alongside reliable handling of Telegram API limits when deploying media heavy content.

## 🚀 How to Run Locally

1. Clone the repository:
   ```bash
   git clone [https://github.com/Vlad34745/steam-signal-bot.git](https://github.com/Vlad34745/steam-signal-bot.git)