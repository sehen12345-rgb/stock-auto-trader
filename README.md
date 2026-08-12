# 주식 자동매매 시스템 (KOSPI & NASDAQ)

> Python + PyQt6 기반 국내(KOSPI) 및 해외(NASDAQ) 주식 자동매매 데스크톱 애플리케이션

---

## 📋 TODO 리스트

### ✅ 완료
- [x] 프로젝트 초기화 및 문서화 (README, 아키텍처, 디자인 가이드)
- [x] 프로젝트 디렉터리 구조 설계

### 🚧 진행 중
- [ ] 개발환경 세팅 (requirements.txt, 가상환경)
- [ ] PyQt6 메인 윈도우 기본 레이아웃 구현

### 📌 추가 예정
#### 1단계 - 기본 인프라
- [ ] 한국투자증권(KIS) API 연동 (KOSPI)
- [ ] Alpaca / Interactive Brokers API 연동 (NASDAQ)
- [ ] API 인증 및 토큰 관리 모듈

#### 2단계 - 데이터 수집
- [ ] 실시간 시세 조회 (WebSocket)
- [ ] 종목 정보 조회 (종목명, 현재가, 등락률)
- [ ] 차트 데이터 수집 (OHLCV)
- [ ] 뉴스/공시 데이터 수집

#### 3단계 - 매매 전략
- [ ] 전략 엔진 베이스 클래스 설계
- [ ] 이동평균선 전략 (MA Cross)
- [ ] RSI 전략
- [ ] 볼린저 밴드 전략
- [ ] 백테스팅 모듈

#### 4단계 - 주문 관리
- [ ] 시장가/지정가 주문
- [ ] 손절/익절 자동 설정
- [ ] 포지션 관리 (잔고, 수익률)
- [ ] 주문 이력 저장 (SQLite)

#### 5단계 - GUI
- [ ] 메인 대시보드
- [ ] 실시간 차트 (PyQtGraph)
- [ ] 종목 검색 & 관심종목 관리
- [ ] 전략 설정 패널
- [ ] 포트폴리오 현황 패널
- [ ] 거래 내역 테이블
- [ ] 알림 / 로그 패널

#### 6단계 - 고도화
- [ ] 스케줄러 (장 시작/종료 자동 처리)
- [ ] 텔레그램 알림 봇
- [ ] 설정 저장/불러오기 (JSON/SQLite)
- [ ] 다크모드 / 라이트모드 전환

---

## 🛠 개발환경

| 항목 | 내용 |
|------|------|
| **언어** | Python 3.11+ |
| **GUI 프레임워크** | PyQt6 |
| **차트** | PyQtGraph |
| **데이터 처리** | pandas, numpy |
| **기술적 분석** | ta-lib, pandas-ta |
| **HTTP 클라이언트** | requests, httpx |
| **WebSocket** | websocket-client |
| **데이터베이스** | SQLite3 (내장) |
| **스케줄러** | APScheduler |
| **알림** | python-telegram-bot |
| **패키징** | PyInstaller (Windows EXE) |
| **버전 관리** | Git + GitHub |
| **가상환경** | venv |

### 로컬 개발 세팅

```bash
# 1. 저장소 클론
git clone https://github.com/YOUR_USERNAME/stock-auto-trader.git
cd stock-auto-trader

# 2. 가상환경 생성 및 활성화
python -m venv venv
# Windows
venv\Scripts\activate
# Mac/Linux
source venv/bin/activate

# 3. 의존성 설치
pip install -r requirements.txt

# 4. 환경변수 설정
cp .env.example .env
# .env 파일에 API 키 입력

# 5. 실행
python main.py
```

---

## 🏗 아키텍처

```
stock-auto-trader/
├── main.py                    # 애플리케이션 진입점
├── requirements.txt
├── .env.example
├── config/
│   ├── settings.py            # 전역 설정
│   └── constants.py           # 상수 정의
├── core/
│   ├── broker/
│   │   ├── base.py            # 브로커 베이스 클래스 (추상)
│   │   ├── kis.py             # 한국투자증권 API (KOSPI)
│   │   └── alpaca.py          # Alpaca API (NASDAQ)
│   ├── strategy/
│   │   ├── base.py            # 전략 베이스 클래스
│   │   ├── ma_cross.py        # 이동평균선 전략
│   │   ├── rsi.py             # RSI 전략
│   │   └── bollinger.py       # 볼린저 밴드 전략
│   ├── data/
│   │   ├── fetcher.py         # 시세 데이터 수집
│   │   └── websocket.py       # 실시간 WebSocket
│   ├── order/
│   │   ├── manager.py         # 주문 관리자
│   │   └── portfolio.py       # 포트폴리오 관리
│   └── scheduler/
│       └── job_scheduler.py   # 매매 스케줄러
├── database/
│   ├── db.py                  # DB 연결 관리
│   └── models.py              # 데이터 모델
├── gui/
│   ├── main_window.py         # 메인 윈도우
│   ├── widgets/
│   │   ├── dashboard.py       # 대시보드 위젯
│   │   ├── chart_widget.py    # 실시간 차트
│   │   ├── watchlist.py       # 관심종목
│   │   ├── order_panel.py     # 주문 패널
│   │   ├── portfolio.py       # 포트폴리오 현황
│   │   └── log_panel.py       # 로그/알림
│   ├── dialogs/
│   │   ├── settings_dialog.py # 설정 다이얼로그
│   │   └── strategy_dialog.py # 전략 설정
│   └── styles/
│       ├── dark_theme.qss     # 다크 테마
│       └── light_theme.qss    # 라이트 테마
├── notifications/
│   └── telegram_bot.py        # 텔레그램 알림
├── backtest/
│   └── engine.py              # 백테스팅 엔진
└── tests/
    ├── test_strategy.py
    ├── test_broker.py
    └── test_order.py
```

### 데이터 흐름

```
[실시간 시세 WebSocket]
        ↓
[데이터 수집 레이어]
        ↓
[전략 엔진] ──── 매매 신호 생성
        ↓
[주문 관리자] ──── [브로커 API (KIS / Alpaca)]
        ↓
[포트폴리오 관리자]
        ↓
[SQLite DB] ←→ [GUI 대시보드]
        ↓
[텔레그램 알림]
```

---

## 🚀 배포환경

| 항목 | 내용 |
|------|------|
| **타겟 OS** | Windows 10/11 (주력), macOS (보조) |
| **배포 방식** | PyInstaller → 단일 EXE 파일 |
| **자동 실행** | Windows 작업 스케줄러 등록 |
| **로그** | 로컬 파일 (`logs/` 디렉터리) |
| **DB** | 로컬 SQLite (`data/trading.db`) |
| **API 키** | 로컬 `.env` 파일 (암호화 저장 권장) |

### EXE 빌드

```bash
pyinstaller --onefile --windowed --icon=assets/icon.ico main.py
```

---

## 🎨 디자인 가이드

### 색상 팔레트 (다크 테마 기본)

| 역할 | 색상 코드 | 용도 |
|------|-----------|------|
| **배경 (Primary)** | `#1E1E2E` | 메인 배경 |
| **배경 (Secondary)** | `#2A2A3E` | 패널/카드 배경 |
| **배경 (Tertiary)** | `#313145` | 입력창, 테이블 행 |
| **Accent Blue** | `#5B9BD5` | 버튼, 강조, 링크 |
| **상승 (Green)** | `#26A69A` | 주가 상승, 수익 |
| **하락 (Red)** | `#EF5350` | 주가 하락, 손실 |
| **텍스트 Primary** | `#FFFFFF` | 주요 텍스트 |
| **텍스트 Secondary** | `#A0A0B8` | 보조 텍스트, 레이블 |
| **테두리** | `#404058` | 위젯 테두리 |

### 폰트

| 용도 | 폰트 | 크기 |
|------|------|------|
| **헤더** | Noto Sans KR Bold | 16px |
| **본문** | Noto Sans KR Regular | 13px |
| **수치 (숫자)** | JetBrains Mono | 13px |
| **소형 레이블** | Noto Sans KR Regular | 11px |

### 레이아웃

```
┌─────────────────────────────────────────────────────────┐
│  [로고]  주식 자동매매   [KOSPI ●] [NASDAQ ●]  [설정] │  ← 상단 헤더
├──────────┬──────────────────────────┬────────────────────┤
│          │                          │                    │
│ 관심종목  │      실시간 차트          │   포트폴리오 현황  │
│ 목록     │   (PyQtGraph)            │   잔고 / 수익률    │
│          │                          │                    │
├──────────┼──────────────────────────┤                    │
│          │  전략 설정 패널           │                    │
│ 종목검색  │  [전략선택] [파라미터]    ├────────────────────┤
│          │  [시작] [중지]            │   거래 내역        │
│          │                          │   (테이블)         │
├──────────┴──────────────────────────┴────────────────────┤
│  로그 패널 (실시간 로그 / 주문 알림)                      │  ← 하단 로그
└─────────────────────────────────────────────────────────┘
```

### UI 컴포넌트 규칙

- **버튼**: 라운드 코너 `border-radius: 6px`, 호버 시 밝기 +10%
- **패널**: `border-radius: 8px`, 1px 테두리
- **테이블**: 홀수/짝수 행 색상 교차, 헤더 고정
- **차트**: 배경 다크, 상승 캔들 초록(`#26A69A`), 하락 캔들 빨강(`#EF5350`)
- **수치 색상**: 양수 초록, 음수 빨강, 0은 회색

---

## 🔑 필요한 API

### KOSPI (국내주식)
- **한국투자증권 KIS Developers API**
  - 가입: https://apiportal.koreainvestment.com
  - App Key / App Secret 발급 필요
  - 실전투자 / 모의투자 계좌 구분

### NASDAQ (해외주식)
- **Alpaca Markets API** (권장 - 무료 페이퍼트레이딩 지원)
  - 가입: https://alpaca.markets
  - API Key / Secret 발급
- 또는 **Interactive Brokers TWS API**

---

## ⚠️ 주의사항

- 자동매매는 **실제 자산 손실** 위험이 있습니다
- 반드시 **모의투자**로 충분히 테스트 후 실전 적용
- API 키는 절대 git에 커밋하지 않습니다 (`.env` 파일 사용)
- 손절 비율 설정은 필수입니다

---

## 📅 개발 이력

| 날짜 | 내용 |
|------|------|
| 2026-08-12 | 프로젝트 초기화, 문서화 완료 |
