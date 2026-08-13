# 주식 자동매매 시스템 (KOSPI & NASDAQ)

> Python + PyQt6 데스크톱 앱 기반 AI 자동매매 시스템
> Claude LLM이 올랜도킴 전략 규칙으로 매수/매도/홀드 판단

---

## 🛠 개발환경

| 항목 | 내용 |
|------|------|
| **언어** | Python 3.11+ |
| **GUI** | PyQt6 6.7+ |
| **차트** | PyQtGraph |
| **LLM** | Claude API (anthropic) |
| **브로커 API** | KIS (KOSPI), Alpaca (NASDAQ) |
| **DB** | SQLite3 (내장) |
| **알림** | python-telegram-bot |
| **스케줄러** | asyncio 기반 (QThread로 GUI 분리) |
| **OS** | Windows 10/11 |
| **IDE** | VSCode / PyCharm |

### 로컬 실행

```bash
# 1. 가상환경 생성
python -m venv venv
venv\Scripts\activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 입력

# 4. PyQt6 앱 실행
python gui_main.py

# (선택) 데모 모드 — API 키 없이 테스트
set DEMO_MODE=true
python gui_main.py
```

---

## 🏗 아키텍처

```
┌─────────────────────────────────────────────────────┐
│                   PyQt6 GUI Layer                    │
│  MainWindow                                          │
│  ├── ControlPanel   (시작/중지/모드 선택)             │
│  ├── WatchlistWidget (관심종목 실시간 시세)            │
│  ├── ChartWidget    (캔들차트 + 지표)                 │
│  ├── PortfolioWidget (보유종목 + 손익)                 │
│  ├── DecisionWidget (AI 판단 피드)                    │
│  └── LogWidget      (시스템 로그)                     │
└────────────────┬────────────────────────────────────┘
                 │ Qt Signals (thread-safe)
┌────────────────▼────────────────────────────────────┐
│              EngineWorker (QThread + asyncio)         │
│  TradingEngine  ←→  30초 tick                        │
│  ├── DataFetcher      (시세 수집)                     │
│  ├── LLMJudge         (Claude AI 판단)               │
│  ├── StrategyManager  (기술 지표 신호)                │
│  └── OrderManager     (주문 실행)                     │
└────────────────┬────────────────────────────────────┘
                 │
    ┌────────────┼────────────┐
    ▼            ▼            ▼
[KIS API]   [Alpaca API]  [SQLite DB]
(KOSPI)     (NASDAQ)      (거래내역)
    │
[Telegram Bot]  (알림/명령)
```

### 파일 구조

```
stock-auto-trader/
├── gui_main.py                     # PyQt6 앱 진입점
├── main.py                         # FastAPI (레거시, 참고용)
├── gui/
│   ├── main_window.py              # 메인 윈도우
│   ├── workers.py                  # EngineWorker (QThread)
│   ├── styles/
│   │   └── theme.py               # 다크 테마 QSS 상수
│   ├── widgets/
│   │   ├── control_panel.py       # 시작/중지/모드
│   │   ├── watchlist_widget.py    # 관심종목 테이블
│   │   ├── portfolio_widget.py    # 포트폴리오/포지션
│   │   ├── decision_widget.py     # AI 판단 피드
│   │   └── log_widget.py         # 시스템 로그
│   └── dialogs/
│       └── settings_dialog.py    # API 키 설정 (예정)
├── core/
│   ├── engine.py                  # 메인 트레이딩 엔진
│   ├── llm_judge.py               # Claude LLM 매매 판단
│   ├── data_fetcher.py            # 시세/지표 수집
│   ├── indicators.py              # 기술 지표 계산
│   ├── demo_data.py               # 데모 더미 데이터
│   ├── broker/
│   │   ├── kis.py                 # 한국투자증권 API
│   │   ├── alpaca.py              # Alpaca API
│   │   └── toss.py                # 토스증권 API
│   ├── strategy/
│   │   ├── value_investing.py     # 가치투자 전략
│   │   ├── ma_cross.py            # 이동평균선 전략
│   │   ├── rsi_strategy.py        # RSI 전략
│   │   ├── scalping.py            # 스캘핑 전략
│   │   ├── day_trading.py         # 데이트레이딩 전략
│   │   ├── swing.py               # 스윙 전략
│   │   ├── strategy_manager.py    # 전략 통합 관리
│   │   └── orlando_kim/           # 올랜도킴 전략
│   └── order/
│       └── manager.py             # 주문/손절/익절
├── database/
│   ├── db.py                      # SQLite 연결
│   └── models.py                  # 거래내역/포지션 모델
├── notifications/
│   └── telegram_bot.py            # 텔레그램 봇
├── api/                           # FastAPI (레거시)
├── static/                        # 웹 대시보드 (레거시)
├── config/
│   ├── constants.py               # 앱 상수
│   └── settings.py                # 환경변수 로딩
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 🎨 디자인 가이드

### 다크 테마 색상 팔레트

| 역할 | 색상 코드 | 설명 |
|------|-----------|------|
| 배경 Primary | `#1E1E2E` | 메인 배경 |
| 배경 Secondary | `#2A2A3E` | 패널/카드 배경 |
| 배경 Tertiary | `#333350` | 호버/활성 상태 |
| 테두리 | `#404058` | 구분선/보더 |
| Accent Blue | `#5B9BD5` | 버튼/NASDAQ 강조 |
| 상승 Green | `#26A69A` | 양봉/수익 |
| 하락 Red | `#EF5350` | 음봉/손실 |
| 경고 Yellow | `#FFA726` | 경고/홀드 |
| 텍스트 Primary | `#FFFFFF` | 주요 텍스트 |
| 텍스트 Secondary | `#A0A0B8` | 보조 텍스트 |
| 텍스트 Disabled | `#606078` | 비활성 텍스트 |

### 폰트

| 용도 | 폰트 | 크기 |
|------|------|------|
| 헤더 타이틀 | Noto Sans KR Bold | 14px |
| 섹션 제목 | Noto Sans KR Medium | 12px |
| 본문 | Noto Sans KR Regular | 12px |
| 숫자/시세 | D2Coding / 기본 Monospace | 12px |
| 로그 | D2Coding | 11px |

### 레이아웃 원칙

- 최소 해상도: 1400 × 900
- 좌측 패널: 관심종목 (너비 220px 고정)
- 중앙 패널: 차트 + AI 판단 (가변)
- 우측 패널: 포트폴리오 (너비 280px 고정)
- 하단: 로그 패널 (높이 120px 고정)
- 패딩: 패널 내부 8px, 카드 내부 10px

---

## 🚀 배포환경

| 항목 | 내용 |
|------|------|
| **실행 환경** | Windows PC 데스크톱 앱 |
| **패키징** | PyInstaller (예정) → .exe 단독 실행 파일 |
| **자동 시작** | Windows 작업 스케줄러 등록 (예정) |
| **데이터 저장** | 로컬 SQLite (`data/trading.db`) |
| **로그** | 로컬 파일 (`logs/`) + GUI 로그 패널 |

---

## 📋 TODO 리스트

### ✅ 완료

- [x] 프로젝트 초기화 및 디렉터리 구조 설계
- [x] 전략 엔진 (MA Cross, RSI, 스캘핑, 데이트레이딩, 스윙, 가치투자, 전략 매니저)
- [x] 브로커 API 래퍼 (KIS KOSPI, Alpaca NASDAQ, 토스증권)
- [x] 주문 관리자 (손절/익절/일 손실 한도/트레일링 스탑)
- [x] SQLite DB (거래내역, 포지션, 신호 저장)
- [x] Claude LLM 판단 엔진 (BUY/SELL/HOLD + 확신도 + 한국어 근거)
- [x] 텔레그램 봇 (알림 + /status /stop /portfolio 명령어)
- [x] 데모 모드 (더미 데이터로 API 키 없이 실행)
- [x] 매매 모드 전환 (scalping / day_trading / swing / long_term)
- [x] **PyQt6 메인 윈도우 기본 레이아웃 + 다크 테마** (2026-08-12)
- [x] **EngineWorker (QThread + asyncio 통합)** (2026-08-13)
- [x] **ControlPanel (시작/중지/모드 선택/상태 표시)** (2026-08-13)
- [x] **WatchlistWidget (관심종목 실시간 테이블)** (2026-08-13)
- [x] **PortfolioWidget (보유종목 + 손익 테이블)** (2026-08-13)
- [x] **DecisionWidget (AI 판단 피드)** (2026-08-13)
- [x] **LogWidget (시스템 로그 + loguru 연동)** (2026-08-13)
- [x] **종합 문서화 (README 업데이트)** (2026-08-13)

### 🚧 진행 중

- [ ] 관심종목 추가/제거 UI (WatchlistWidget 우클릭 메뉴)
- [ ] KIS API 실계좌 연동 테스트
- [ ] 올랜도킴 강의 자료 → 전략 코드 반영

### 📌 추가 예정

- [ ] **캔들차트 위젯** (PyQtGraph 기반, MA20/MA60 오버레이)
- [ ] **설정 다이얼로그** (API 키 GUI 입력, .env 저장)
- [ ] **백테스팅 UI** (기간/전략 선택 → 결과 차트)
- [ ] **수익률 차트** (누적 수익률 꺾은선 그래프)
- [ ] **OCO 주문** (진입 즉시 손절/익절 동시 설정)
- [ ] **나스닥 실시간 WebSocket 시세**
- [ ] **관심종목 고점 돌파 알림** (텔레그램)
- [ ] **PyInstaller 패키징** → .exe 단독 배포
- [ ] **Windows 자동 시작** 등록

---

## 🔑 필요한 API 키

| API | 용도 | 발급처 |
|-----|------|--------|
| KIS App Key/Secret | KOSPI 매매 | https://apiportal.koreainvestment.com |
| Alpaca Key/Secret | NASDAQ 매매 | https://alpaca.markets |
| Anthropic API Key | LLM 판단 | https://console.anthropic.com |
| Telegram Bot Token | 알림/명령 | @BotFather |

> **DEMO_MODE=true** 설정 시 API 키 없이 더미 데이터로 실행 가능

---

## ⚠️ 주의사항

- API 키는 절대 git에 커밋하지 않습니다 (`.env` 파일 사용)
- 반드시 모의투자 (`KIS_MOCK=true`, `ALPACA_PAPER=true`) 로 충분히 테스트 후 실전 전환
- 손절 설정 필수 (기본 -3.5%)

---

## 📅 개발 이력

| 날짜 | 내용 |
|------|------|
| 2026-08-12 | 프로젝트 초기화, 디렉터리 구조 설계 |
| 2026-08-12 | 전략 엔진, 브로커 API, 주문 관리, DB, LLM 판단, 텔레그램 봇 구현 |
| 2026-08-12 | FastAPI 백엔드 + 웹 대시보드 구현 (레거시) |
| 2026-08-12 | PyQt6 메인 윈도우 뼈대 + 다크 테마 |
| 2026-08-13 | PyQt6 GUI 본격 구현 (Worker, 위젯 전체) + 문서 정비 |
