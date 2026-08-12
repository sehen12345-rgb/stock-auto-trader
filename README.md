# 주식 자동매매 시스템 (KOSPI & NASDAQ)

> FastAPI 백엔드 + 웹 대시보드 + 텔레그램 봇 기반 AI 자동매매 시스템
> Claude LLM이 올랜도킴 전략 규칙으로 매수/매도/홀드 판단

---

## 🚀 실행 방법

```bash
# 1. 가상환경
python -m venv venv
venv\Scripts\activate

# 2. 패키지 설치
pip install -r requirements.txt

# 3. 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 입력

# 4. 실행
python main.py

# 5. 접속
# 데스크탑/모바일 브라우저: http://localhost:8000
# 외부 접속: http://[내PC IP]:8000
```

---

## 📋 TODO 리스트

### ✅ 완료
- [x] 프로젝트 초기화 및 문서화
- [x] 프로젝트 디렉터리 구조 설계
- [x] 전략 엔진 (가치투자, MA Cross, RSI, 전략 매니저)
- [x] 브로커 API 래퍼 (KIS KOSPI, Alpaca NASDAQ)
- [x] 주문 관리자 (손절/익절/일 손실 한도)
- [x] SQLite DB (거래내역, 포지션, 신호 저장)
- [x] **FastAPI 백엔드** (REST API + WebSocket)
- [x] **웹 대시보드** (모바일/데스크탑 동시 접속, 다크테마)
- [x] **텔레그램 봇** (알림 + /status /stop /portfolio 명령어)
- [x] **Claude LLM 판단 엔진** (BUY/SELL/HOLD + 확신도 + 한국어 근거)
- [x] **올랜도킴 전략 폴더** 구조 준비

### 🚧 진행 중
- [ ] 올랜도킴 강의 자료 → 전략 코드 반영 (자료 수신 시 지속 업데이트)
- [ ] KIS API 실계좌 연동 테스트
- [ ] 웹 대시보드 수익률 차트 실데이터 연동

### 📌 추가 예정
- [ ] 나스닥 실시간 WebSocket 시세
- [ ] OCO 주문 자동 등록 (진입 즉시 손절/익절 동시 설정)
- [ ] 모의투자 백테스팅 리포트
- [ ] 관심종목 고점 돌파 알림 (텔레그램)
- [ ] ngrok 연동 (외부 네트워크에서 모바일 접속)

---

## 🏗 아키텍처

```
[KIS API / Alpaca API]  ←→  [DataFetcher]
                                  ↓
                          [TradingEngine]  ←  asyncio 30초 tick
                                  ↓
                          [Claude LLM Judge]  → BUY/SELL/HOLD + 확신도
                                  ↓
                          [OrderManager]  → 실제 주문 실행
                                  ↓
                          [SQLite DB]  ←→  [FastAPI Routes]
                                                ↓
                                     ┌──────────────────┐
                                     │  웹 대시보드       │  ← 모바일/데스크탑
                                     │  (WebSocket 실시간)│
                                     └──────────────────┘
                                     [텔레그램 봇]  ← 알림/명령
```

### 파일 구조

```
stock-auto-trader/
├── main.py                         # FastAPI 앱 진입점
├── api/
│   ├── routes.py                   # REST API 엔드포인트
│   └── websocket.py                # WebSocket 실시간 push
├── core/
│   ├── engine.py                   # 메인 트레이딩 엔진 (asyncio)
│   ├── llm_judge.py                # Claude LLM 매매 판단
│   ├── data_fetcher.py             # 시세/지표 데이터 수집
│   ├── broker/
│   │   ├── kis.py                  # 한국투자증권 API (KOSPI)
│   │   └── alpaca.py               # Alpaca API (NASDAQ)
│   ├── strategy/
│   │   ├── value_investing.py      # 가치투자 전략
│   │   ├── ma_cross.py             # 이동평균선 전략
│   │   ├── rsi_strategy.py         # RSI 전략
│   │   ├── strategy_manager.py     # 전략 통합 관리
│   │   └── orlando_kim/            # 올랜도킴 전략 (자료 추가 시 반영)
│   └── order/
│       └── manager.py              # 주문/손절/익절 관리
├── database/
│   ├── db.py                       # SQLite 연결
│   └── models.py                   # 거래내역/포지션/신호 모델
├── notifications/
│   └── telegram_bot.py             # 텔레그램 봇
├── static/
│   └── index.html                  # 웹 대시보드 (모바일 반응형)
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 🛠 개발환경

| 항목 | 내용 |
|------|------|
| **언어** | Python 3.11+ |
| **백엔드** | FastAPI + uvicorn |
| **프론트엔드** | 순수 HTML/CSS/JS + Chart.js |
| **LLM** | Claude API (anthropic) |
| **데이터** | KIS API (KOSPI), Alpaca API (NASDAQ) |
| **DB** | SQLite3 |
| **알림** | python-telegram-bot |
| **스케줄러** | asyncio 기반 내장 |

---

## 🚀 배포환경

| 항목 | 내용 |
|------|------|
| **실행 환경** | Windows PC (항상 켜져 있어야 함) |
| **접속 방법** | 같은 WiFi: `http://[PC IP]:8000` |
| **외부 접속** | ngrok 사용 (예정) |
| **모바일** | 브라우저로 위 URL 접속 |

---

## 🎨 디자인 가이드

### 색상 팔레트 (다크 테마)

| 역할 | 색상 |
|------|------|
| 배경 Primary | `#1E1E2E` |
| 배경 Secondary | `#2A2A3E` |
| Accent | `#5B9BD5` |
| 상승 | `#26A69A` |
| 하락 | `#EF5350` |
| 텍스트 Primary | `#FFFFFF` |
| 텍스트 Secondary | `#A0A0B8` |

---

## 🔑 필요한 API 키

| API | 용도 | 발급처 |
|-----|------|--------|
| KIS App Key/Secret | KOSPI 매매 | https://apiportal.koreainvestment.com |
| Alpaca Key/Secret | NASDAQ 매매 | https://alpaca.markets |
| Anthropic API Key | LLM 판단 | https://console.anthropic.com |
| Telegram Bot Token | 알림/명령 | @BotFather |

---

## ⚠️ 주의사항

- API 키는 절대 git에 커밋하지 않습니다 (`.env` 파일 사용)
- 반드시 모의투자(`KIS_MOCK=true`)로 충분히 테스트 후 실전 전환
- 손절 설정은 필수

---

## 📅 개발 이력

| 날짜 | 내용 |
|------|------|
| 2026-08-12 | 프로젝트 초기화, 문서화 |
| 2026-08-12 | 전략 엔진, 브로커 API, 주문 관리, DB 구현 |
| 2026-08-12 | FastAPI 백엔드, 웹 대시보드, 텔레그램 봇, Claude LLM 판단 엔진 구현 |
