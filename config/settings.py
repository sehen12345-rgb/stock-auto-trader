import os
from dotenv import load_dotenv

load_dotenv()

# KIS API (KOSPI)
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")
KIS_MOCK = os.getenv("KIS_MOCK", "true").lower() == "true"

# 토스증권 Open API (KOSPI)
TOSS_APP_KEY = os.getenv("TOSS_APP_KEY", "")
TOSS_APP_SECRET = os.getenv("TOSS_APP_SECRET", "")
TOSS_ACCOUNT_NO = os.getenv("TOSS_ACCOUNT_NO", "")
TOSS_MOCK = os.getenv("TOSS_MOCK", "true").lower() == "true"

# Alpaca API (NASDAQ)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

# LLM
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Demo Mode (API 키 없이 데모 실행)
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# 자금 설정
SEED_AMOUNT = int(os.getenv("SEED_AMOUNT", "1000000"))

# App
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
DB_PATH = os.getenv("DB_PATH", "data/trading.db")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
