APP_NAME = "주식 자동매매 시스템"
APP_VERSION = "0.1.0"

# 장 운영 시간 (KST)
KOSPI_OPEN = "09:00"
KOSPI_CLOSE = "15:30"

# 장 운영 시간 (EST)
NASDAQ_OPEN = "09:30"
NASDAQ_CLOSE = "16:00"

# ── 자금 관리 ──────────────────────────────────────────
SEED_AMOUNT = 1_000_000          # 시드: 100만원 (테스트)
MAX_SLOTS = 2                    # 최대 동시 보유 종목 수 (100만원 → 2종목)
AMOUNT_PER_SLOT = 250_000        # 종목당 최대 25만원
MAX_DAILY_LOSS = 30_000          # 일 최대 손실 한도 3만원 (시드의 3%)

# ── 매매 기준 ──────────────────────────────────────────
DEFAULT_STOP_LOSS = 0.035        # 손절: -3.5%
DEFAULT_TAKE_PROFIT = 0.06       # 익절: +6%
MIN_VOLUME_RATIO = 1.5           # 최소 거래량 배율 (20일 평균 대비)
