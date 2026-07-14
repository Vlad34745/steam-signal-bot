@echo off
chcp 65001 > nul
echo 🚀 Starting Steam Signal Bot...
cd /d D:\SteamProject

call .venv\Scripts\activate.bat

python main.py

if errorlevel 1 (
    echo.
    echo ❌ Bot crashed. Check bot_errors.log for details.
)

pause