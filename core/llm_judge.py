import json
import os
from typing import Any

from loguru import logger

SYSTEM_PROMPT = """당신은 올랜도킴 매매 전략을 따르는 AI 트레이더입니다.

## 매매 모드별 규칙

### 스캘핑 (scalping) — 10초 틱, 초단타
- 진입: RSI < 35 AND 거래량 1.5배↑ AND 현재가 > EMA9
- 청산: 손절 -1% / 익절 +1.5% (엄격 준수)
- 트레일링 스탑: 최고가 대비 -2% 이탈 즉시 청산
- 주의: 스프레드·슬리피지 고려, 극소량만 매수

### 단타 (day_trading) — 30초 틱
- 진입: MACD 골든크로스 AND RSI 40~65 AND 현재가 > MA20
- 볼린저 하단 터치 후 반등 시 추가 확신 부여
- 청산: 손절 -2% / 익절 +4%
- 당일 청산 원칙

### 스윙 (swing) — 5분 틱
- 진입: 눌림목(고점 대비 3~10% 되돌림 후 반등) AND MA20 위 AND RSI 40~60 AND MACD > 0
- 52주 고점 10% 이내 → 강력 추가 점수
- 청산: 손절 -3.5% / 익절 +8~15%

### 장기 올랜도킴 (long_term) — 5분 틱
- 진입: MA20 위 + 거래량 1.5배↑ + 하락추세선 돌파 + 쌍바닥 패턴
- 청산: 손절 -3.5% / 익절 +4~8% 단계적 청산

## 핵심 매매 규칙

### 매수 조건 (모두 충족해야 진입)
1. 20일 이동평균선 위에 있는 종목만 매수 (현재가 > MA20)
2. 거래량이 20일 평균의 1.5배 이상일 때만 신뢰
3. 하락 추세선 돌파 확인 (돌파 후 2~3일 추세선 위 유지)
4. 쌍바닥 패턴 확인 시 강력 매수 신호
5. 52주 고점 돌파 시 추가 매수 신호

### 매수 금지 조건
- 시장 전체 하락장 (코스피 -1.5% 이하) → 신규 매수 금지
- 10년물 국채금리 5% 이상 → 신규 매수 신중 (위험자산 매력 감소)
- 돌파 후 바로 추격 매수 금지 → 눌림목(되돌림) 구간에서 매수
- 위 매물대 두꺼운 구간 → 매수 신중 (본전 매도 물량 소화 필요)

### 매도/손절 조건
- 손절선: 매수가 -3.5% 이탈 시 즉시 손절
- 익절: +4% ~ +8% 구간에서 단계적 청산
- 20일선 아래로 하락 시 매도 검토

### 캔들 패턴 신호
- 망치형(hammer) + RSI 과매도 → 강력 매수 신호
- 불리시 장악형(bullish_engulfing) → 추세 전환 매수
- 슈팅스타(shooting_star) + 저항선 근처 → 매도 신호
- 베어리시 장악형(bearish_engulfing) → 매도 신호

### 매물대 규칙
- heavy_resistance=True → 위에 두꺼운 매물대, 매수 신중
- near_support=True + 다른 매수 조건 → 매수 강화
- 현재가 POC 위(above_poc=True) → 상승 모멘텀

### 외국인/기관 동향
- foreign_buying=True + institution 순매수 → 매수 신호 강화
- 외국인 순매도 지속 → 매수 금지

### 공포지수 (Fear & Greed)
- Fear & Greed < 25 (극단적 공포) → 역발상 매수 기회
- Fear & Greed > 75 (극단적 탐욕) → 매수 신중

### 추세 강도 (ADX)
- ADX > 25 → 추세 강함, 추세 방향으로 매매
- ADX < 20 → 횡보장, 추세 추종 전략 효과 감소

### 반도체 섹터 특이사항 (올랜도킴 2026-08-13 시황 업데이트)
- SK하이닉스(000660): HBM 선두 — AI 메모리 고마진 구조, 씨티 목표가 310만원, 장기 계약 기반 전환 중
- 삼성전자(005930): 완만한 상승 각도, 급등 기대 금지, 매물대 소화 중
- MU(마이크론): EPS 피크 2027년, 씨티 목표가 $1150(30%↑), 9/29 실적 전후 반등 노려볼 것, $44 저점 유지 예상
  - 매매 전략: 2026년 말~2027년 초까지 보유 후 단계적 매도 (EPS 피크 6개월 선행)
  - 레버리지 ETF AUM 110억→45억 달러 투기 완전 해소 → 추가 조정 후 매수 유효
- NVDA: 8월 26일 실적 발표 = 시장 전체 최대 이벤트, 이후 순환매 유입 기대, 장기 보유
- AVGO(브로드컴): ASIC 가속기 2027년 GPU 추월 → 장기 수혜 1순위, 눌림목마다 분할매수
- MRVL(마벨): EPS 고성장(4.05→9.16→11.92), ASIC 밸류체인 핵심, 강력 장기 보유
- SOX(반도체지수): 시간·기간 조정 중(엔형 패턴), 급등 기대 금지, 분할매수 권고
- AI 가속기 시장 성장률: 2025(+62%)→2026(+43%)→2027 둔화 → 성장 정점 2026, 지금이 핵심 매수 구간

### 소프트웨어·AI 인프라 섹터 (2026-08-08 CNBC 업데이트)
- SaaS 대재앙(AI 소프트웨어 대체 우려) 공포 해소 → 클라우드플레어·아틀라시안 등 IGV ETF 전반 반등
- DDOG(데이터도그): 단일 대형 고객 사용량 감소 코멘트로 주가 급락 → 과잉반응, 전체 사업 오히려 가속화 중
  - 크라우드스트라이크·클라우드플레어보다 밸류에이션 저렴, 성장률 동일 or 우위 → 저평가 매수 기회
- 소프트웨어 매수 조건: KPI 가속화 + 수주 잔고 증가 + 대형 계약 체결 확인 후 분할매수

### GE Aerospace (방산·항공엔진 / 2026-08-09 분석)
- 비즈니스 모델: 매출 70%가 애프터마켓 서비스 → 경기침체 방어력 강함
- 2027년 예상 EPS $9.08, 5년 평균 PER 40배수 → 적정가 $363
- 주봉 전고점 돌파 확인 → $300 이상에서 구조 형성 중, 조정 시 분할매수
- 방산 지출 구조적 증가 (전쟁·분쟁 시대) → 포트폴리오 수비주 역할
- 실적 성장 5분기 연속 20%↑, 수주 잔고 $2100억, IndiGo 1000대 LEAP 엔진 수주

### 블룸에너지(BE) (AI 전력 인프라 / 2026-08-09 분석)
- 26년 2분기 매출 $10.65억(+166% YoY), EPS 0.78 vs 예상 0.40 (95% 상회)
- 2027년 EPS $4.9, PER 47배수 → 적정가 $230 → 현재가 조정 시 매수 구간
- UBS 목표가 $350 매수 유지, 14개 EPS 상향·0개 하향
- AI 전력 수요는 제본스 역설로 구조적 확대 → 전력 공급 인프라 장기 수혜
- 단, 베타 3.83 고변동성, 집중 고객 리스크 존재 → 소량 분할매수

### 핵심 이벤트 캘린더
- 2026-08-26: NVDA 실적 — 반도체 전체 방향성 결정, 가장 중요한 날
- 2026-09-29: MU 실적 — D램 사이클 바닥 확인 or 추가 조정 판단

### 국채 금리·거시경제 리스크 (2026-08-13 시황 기준)
- PPI 0% (예측 0.2% 하회) + CPI 양호 → 9월 금리 동결 거의 확실 → 성장주 매수 편향 강화
- 10년물 금리 4.67% (-0.34%), 30년물 5.2% → 5% 위험 레벨 접근, 매수 시 분할 원칙 준수
- 유가 $90 저항대: $90 하회 시 반도체 랠리 가속 신호, 현재 하락 중 → 긍정적
- 나스닥 숏포지션 잔존 → 숏커버링 발생 시 추가 상승 여력, 신규 자금은 S&P500에 주로 유입
- S&P500: 엔형 패턴(상승→눌림→재상승), 눌림목 구간이 매수 기회, CFRA 목표 8050·탐리 8000
- 미국 증시 체력: 헤지펀드 매도 충격이 도미노 없이 며칠 만에 정리 → 시장 근본 체력 강함 (시겔)
- 금리 5% 이상 구간: 신규 매수 극도로 신중, 소량 분할매수만 허용

### 분할매수 기준 (종목별)
- **월봉 스토캐스틱 낮을 때**: PLTR·IONQ 등 고베타 성장주 분할매수 신호
- **200주 이동평균선 도달 시**: IONQ 핵심 매수 구간, PSR 30배수 확인 병행
- **MU·메모리주**: 씨티 목표가 대비 30% 이상 괴리 or 실적 발표 직전 분할 진입
- **GE·BE**: 적정가(GE $363, BE $230) 대비 10% 이상 하락 시 분할매수
- 공통: 급등 후 추격 절대 금지, 눌림목(되돌림)에서만 분할매수

### 올랜도킴 관심종목 (2026 하반기 장기 유망주 / 2026-08-13 시황 반영)

**ASIC/AI 핵심 (최우선 분할매수)**
- AVGO(브로드컴): 2027년 ASIC가 GPU 추월 → 장기 수혜 1순위, 눌림목마다 분할매수
- MRVL(Marvell): EPS 4.05→9.16→11.92 고성장, ASIC 밸류체인 핵심, 매출 2배 전망

**반도체 대형주 (조정 시 분할매수)**
- NVDA: 8/26 실적 핵심 이벤트, 장기 보유, 단기 변동성 무시
- MU(마이크론): 9/29 실적 전후 반등 기회, 2027년 초까지 보유 후 단계적 매도 준비
- TSM: 파운드리 독점, ASIC 고객 증가 수혜
- AMD: 바닥 확인 후 진입 (선취매 금지)

**클라우드/AI 하이퍼스케일러 (AI 밸류체인 29.7% 이익 선취)**
- AMZN: 200달러 or 200일선 지지 확인 후 매수 (낸시 텐글러 비중 확대)
- MSFT: 470달러 눌림목 매수, AI capex → 수익 전환 확인
- GOOG: 클라우드 실적 양호, AI 밸류체인 핵심

**AI 인프라/방산/전력**
- GE(GE Aerospace): 방산 방어주, 적정가 $363, 조정 시 분할매수, 10% 이상 하락 구간 매수
- BE(블룸에너지): AI 전력 인프라, 적정가 $230, 고변동성 소량 분할매수
- VRT(Vertiv): AI 데이터센터 전력 수혜
- DELL: 350~360달러 눌림목 매수

**소프트웨어 (저평가 회복)**
- DDOG(데이터도그): 단일 고객 우려 과잉반응 하락 → 사업 가속화 중, 저평가 매수 기회

**적자주식 (고위험 소량 투기 — 스토캐스틱/PSR 조건 시만 진입)**
- PLTR: 월봉 스토캐스틱 낮을 때 + PSR 30~70배수 구간 분할매수, 급등 추격 금지
- IONQ: 200주 이동평균선 도달 + PSR 30배수 + 스토캐스틱 저점 시 분할매수
- NBIS, RKLB, IREN, PL, ASTS, SPLX: 소량, 손절 철저

**공통 매수 원칙**
- 급등 후 추격 절대 금지 → 반드시 눌림목(되돌림)에서 분할매수
- 장기 보유 관점 유지 (3년 내 수익 실현 목표), 단기 변동성에 흔들리지 않기
- SOX 시간 조정 구간: 반도체 전반 분할매수 권고 (급등 기대 금지)

### 포지션 관리
- 동시 보유 최대 2종목 (시드 100만원 기준)
- 종목당 최대 25만원
- 일 손실 한도 3만원 초과 시 당일 매매 중단

## 응답 형식 (반드시 JSON만 반환)
{
  "decision": "BUY" | "SELL" | "HOLD",
  "ticker": "종목코드",
  "quantity": 수량(정수),
  "confidence": 확신도(0-100 정수),
  "reason": "한국어 근거 (2-3문장)"
}

매수/매도 신호가 없으면 decision을 "HOLD"로, ticker를 ""로 설정하세요."""

_ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")


class LLMJudge:
    def __init__(self) -> None:
        self._client = None
        self._last_signal_hash: str = ""  # 신호 변화 없으면 LLM 호출 스킵
        if _ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
                logger.info("[LLM] Anthropic 클라이언트 초기화 완료")
            except Exception as e:
                logger.warning(f"[LLM] Anthropic 클라이언트 초기화 실패: {e}")
        else:
            logger.info("[LLM] ANTHROPIC_API_KEY 없음 — 규칙 기반 판단 모드")

    @staticmethod
    def _fetch_research_context(tickers: list[str]) -> dict[str, list[dict]]:
        """종목 리스트에 대한 최근 리서치 이력을 반환한다. 실패 시 빈 dict."""
        try:
            from database.research_repo import get_research_repo
            repo = get_research_repo()
            result = {}
            for ticker in tickers:
                notes = repo.find_by_ticker(ticker, limit=5)
                if notes:
                    result[ticker] = notes
            return result
        except Exception as e:
            logger.warning(f"[LLM] 리서치 이력 조회 실패: {e}")
            return {}

    async def judge(
        self,
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
        watchlist: dict[str, str],
        trading_mode: str = "long_term",
        fear_greed: dict[str, Any] | None = None,
        kospi_change: float = 0.0,
        nasdaq_change: float = 0.0,
        news_context: dict[str, Any] | None = None,
        factor_scores: dict[str, float] | None = None,  # 추가
    ) -> dict[str, Any]:
        if self._client is None:
            result = self._rule_based_judge(market_data, positions)
            logger.info(f"[LLM] 규칙 판단: {result.get('decision')} {result.get('ticker')} "
                        f"확신도:{result.get('confidence')}%")
            return result

        # 신호 해시 — RSI/MACD/pullback 등 핵심 지표 변화 없으면 LLM 스킵
        import hashlib
        signal_key = json.dumps({
            t: {
                "rsi": round(d.get("rsi") or 0, 0),
                # macd_hist: 1자리 반올림으로 노이즈 억제 (macd_hist 없으면 macd 사용)
                "macd": round((d.get("macd_hist") or d.get("macd") or 0) * 10) / 10,
                "pullback": d.get("pullback_detected"),
                "above_ma20": d.get("above_ma20"),
                "volume_surge": d.get("volume_surge"),
            }
            for t, d in market_data.items()
        }, sort_keys=True) + str([p.get("symbol") for p in positions])
        signal_hash = hashlib.md5(signal_key.encode()).hexdigest()

        if signal_hash == self._last_signal_hash:
            logger.debug("[LLM] 신호 변화 없음 — API 호출 스킵")
            return {"decision": "HOLD", "ticker": "", "quantity": 0, "confidence": 0, "reason": "신호 변화 없음, 관망"}
        self._last_signal_hash = signal_hash

        # 리서치 이력 수집
        all_tickers = list(market_data.keys()) + list(watchlist.keys())
        research_map = self._fetch_research_context(list(dict.fromkeys(all_tickers)))

        prompt = self._build_prompt(
            market_data, positions, watchlist, trading_mode,
            fear_greed=fear_greed, kospi_change=kospi_change, nasdaq_change=nasdaq_change,
            news_context=news_context,
            research_map=research_map,
            factor_scores=factor_scores,
        )
        try:
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=384,
                system=[{
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            result: dict[str, Any] = json.loads(text)
            logger.info(f"[LLM] 판단: {result.get('decision')} {result.get('ticker')} "
                        f"확신도:{result.get('confidence')}%")
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[LLM] JSON 파싱 실패: {e}")
            return {"decision": "HOLD", "ticker": "", "quantity": 0, "confidence": 0, "reason": "JSON 파싱 오류"}
        except Exception as e:
            logger.error(f"[LLM] API 호출 실패: {e}")
            return {"decision": "HOLD", "ticker": "", "quantity": 0, "confidence": 0, "reason": str(e)}

    def _rule_based_judge(
        self,
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        held_symbols = {p.get("symbol") for p in positions}
        slot_available = len(held_symbols) < 4

        # 보유 포지션 손절 체크
        for p in positions:
            sym = p.get("symbol", "")
            current = p.get("current_price", 0)
            stop = p.get("stop_price", 0)
            target = p.get("target_price", 0)
            if stop > 0 and current > 0 and current <= stop:
                return {
                    "decision": "SELL",
                    "ticker": sym,
                    "quantity": p.get("quantity", 1),
                    "confidence": 90,
                    "reason": f"손절가 도달. 현재가 {current:,.0f}원이 손절가 {stop:,.0f}원 이하. 즉시 매도.",
                }
            if target > 0 and current > 0 and current >= target:
                return {
                    "decision": "SELL",
                    "ticker": sym,
                    "quantity": p.get("quantity", 1),
                    "confidence": 85,
                    "reason": f"익절가 도달. 현재가 {current:,.0f}원이 목표가 {target:,.0f}원 이상. 수익 실현.",
                }

        if not slot_available:
            return {
                "decision": "HOLD",
                "ticker": "",
                "quantity": 0,
                "confidence": 60,
                "reason": "4종목 보유 한도 도달. 신규 매수 불가.",
            }

        # 매수 신호 탐색
        best_ticker = ""
        best_confidence = 0
        best_reason = ""

        for ticker, data in market_data.items():
            if ticker in held_symbols:
                continue

            above_ma20 = data.get("above_ma20", False)
            volume_surge = data.get("volume_surge", False)
            volume_ratio = data.get("volume_ratio", 0)
            pct_from_high = data.get("pct_from_high", 100)
            current_price = data.get("current_price", 0)
            ma20 = data.get("ma20", 0)

            if not above_ma20 or current_price <= 0:
                continue

            confidence = 50
            reasons = []

            if above_ma20:
                confidence += 15
                reasons.append(f"20일선 위({current_price:,.0f} > MA20 {ma20:,.0f})")

            if volume_surge:
                confidence += 20
                reasons.append(f"거래량 급증(평균 대비 {volume_ratio:.1f}배)")

            if pct_from_high is not None and pct_from_high <= 3:
                confidence += 15
                reasons.append(f"52주 고점 근접(-{pct_from_high:.1f}%)")
            elif pct_from_high is not None and pct_from_high <= 10:
                confidence += 5

            if confidence > best_confidence:
                best_confidence = confidence
                best_ticker = ticker
                best_reason = ". ".join(reasons) + ". 올랜도킴 규칙 충족으로 매수 신호."

        if best_ticker and best_confidence >= 55:
            price = market_data[best_ticker].get("current_price", 0)
            qty = 1  # 엔진이 예수금 기반으로 재계산
            return {
                "decision": "BUY",
                "ticker": best_ticker,
                "quantity": qty,
                "confidence": best_confidence,
                "reason": best_reason,
            }

        return {
            "decision": "HOLD",
            "ticker": "",
            "quantity": 0,
            "confidence": 50,
            "reason": "매수 조건 미충족. 20일선 위 + 거래량 급증 종목 없음. 관망.",
        }

    @staticmethod
    def _build_prompt(
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
        watchlist: dict[str, str],
        trading_mode: str = "long_term",
        fear_greed: dict[str, Any] | None = None,
        kospi_change: float = 0.0,
        nasdaq_change: float = 0.0,
        news_context: dict[str, Any] | None = None,
        research_map: dict[str, list[dict]] | None = None,
        factor_scores: dict[str, float] | None = None,
    ) -> str:
        mode_labels = {
            "scalping": "스캘핑 (손절-1%/익절+1.5%)",
            "day_trading": "단타 (손절-2%/익절+4%)",
            "swing": "스윙 (손절-3.5%/익절+8~15%)",
            "long_term": "장기/올랜도킴 (손절-3.5%/익절+4~8%)",
        }
        mode_label = mode_labels.get(trading_mode, trading_mode)

        lines = [f"## 현재 매매 모드: {mode_label}", ""]

        # 시장 환경 섹션
        fg_val = (fear_greed or {}).get("value", 50)
        fg_rating = (fear_greed or {}).get("rating", "Neutral")
        lines.append("## 시장 환경")
        lines.append(f"- 코스피 변동률: {kospi_change:+.2f}%")
        lines.append(f"- 나스닥 변동률: {nasdaq_change:+.2f}%")
        lines.append(f"- Fear & Greed 지수: {fg_val} ({fg_rating})")
        lines.append(
            f"- 시장 매수 적합: {'예' if kospi_change >= -1.5 and fg_val >= 25 else '아니오'}"
        )
        lines.append("")

        # 팩터 점수 TOP 종목 강조
        if factor_scores:
            top = sorted(factor_scores.items(), key=lambda x: x[1], reverse=True)[:5]
            lines.append("[퀀트 팩터 스코어 TOP5]")
            for t, s in top:
                lines.append(f"  {t}: {s:.0f}/100점")
            lines.append("")

        # 실시간 뉴스 섹션
        if news_context:
            lines.append("## 실시간 뉴스 (최근 5분)")
            summary = news_context.get("summary", "")
            if summary:
                lines.append(f"- 요약: {summary}")
            for label, key in [("코스피", "kospi_news"), ("반도체", "semiconductor_news"),
                                ("거시경제", "macro_news"), ("미국주식", "us_news")]:
                items = news_context.get(key, [])
                if items:
                    lines.append(f"- {label}: " + " | ".join(items[:3]))
            lines.append("")

        lines.append("## 현재 시세 데이터 (기술 지표 포함)")
        for ticker, data in market_data.items():
            rsi = data.get("rsi")
            macd = data.get("macd")
            macd_sig = data.get("macd_signal")
            bb_upper = data.get("bb_upper")
            bb_lower = data.get("bb_lower")
            atr = data.get("atr")
            ema9 = data.get("ema9")
            pullback = data.get("pullback_detected", False)
            adx = data.get("adx")
            stoch_k = data.get("stoch_k")
            stoch_d = data.get("stoch_d")
            vwap = data.get("vwap")

            # 캔들 패턴
            candle_signals = []
            if data.get("hammer"):
                candle_signals.append("망치형")
            if data.get("doji"):
                candle_signals.append("도지")
            if data.get("bullish_engulfing"):
                candle_signals.append("불리시장악형")
            if data.get("bearish_engulfing"):
                candle_signals.append("베어리시장악형")
            if data.get("shooting_star"):
                candle_signals.append("슈팅스타")
            if data.get("morning_star"):
                candle_signals.append("모닝스타")
            candle_str = ",".join(candle_signals) if candle_signals else "없음"

            # 매물대
            poc = data.get("poc")
            heavy_res = data.get("heavy_resistance", False)
            above_poc = data.get("above_poc", False)

            # 지지/저항
            support = data.get("support")
            resistance = data.get("resistance")
            near_support = data.get("near_support", False)
            near_resistance = data.get("near_resistance", False)

            # 외국인/기관
            foreign_net = data.get("foreign_net", 0)
            institution_net = data.get("institution_net", 0)
            foreign_buying = data.get("foreign_buying", False)

            # Finnhub (해외주식)
            finnhub_sentiment = data.get("finnhub_sentiment")
            insider_net_shares = data.get("insider_net_shares", 0)
            insider_buy_count  = data.get("insider_buy_count", 0)
            insider_sell_count = data.get("insider_sell_count", 0)
            finnhub_news: list[str] = data.get("finnhub_news", [])

            # 쌍바닥
            double_bottom = data.get("double_bottom", False)

            # MACD 방향
            macd_dir = ""
            if macd is not None and macd_sig is not None:
                macd_dir = "골든크로스↑" if macd > macd_sig else "데드크로스↓"

            pullback_score = data.get("pullback_score", 0)
            pullback_depth = data.get("pullback_depth_pct", 0.0)
            pullback_reasons = data.get("pullback_reasons", [])
            pullback_str = (
                f"감지(점수={pullback_score}/100, 깊이={pullback_depth:.1f}%, {','.join(pullback_reasons)})"
                if pullback else "없음"
            )
            lines.append(
                f"- {ticker}: 현재가={data.get('current_price')}, "
                f"MA20={data.get('ma20')}, "
                f"거래량비율={data.get('volume_ratio')}, "
                f"52주고점대비=-{data.get('pct_from_high')}%, "
                f"MA20상위={data.get('above_ma20')}, "
                f"거래량급증={data.get('volume_surge')}, "
                f"RSI={rsi if rsi is not None else 'N/A'}, "
                f"MACD={macd_dir}({round(macd, 4) if macd is not None else 'N/A'}), "
                f"BB상단={bb_upper}, BB하단={bb_lower}, "
                f"ATR={atr}, EMA9={ema9}, "
                f"눌림목={pullback_str}, "
                f"ADX={adx if adx is not None else 'N/A'}, "
                f"Stoch%K={stoch_k if stoch_k is not None else 'N/A'}, "
                f"Stoch%D={stoch_d if stoch_d is not None else 'N/A'}, "
                f"VWAP={vwap if vwap is not None else 'N/A'}, "
                f"캔들패턴=[{candle_str}], "
                f"쌍바닥={double_bottom}, "
                f"POC={poc}, POC위={above_poc}, 두꺼운매물대={heavy_res}, "
                f"지지={support}, 저항={resistance}, "
                f"지지근처={near_support}, 저항근처={near_resistance}, "
                f"외국인순매수={foreign_net:+,}, 기관순매수={institution_net:+,}, "
                f"외국인매수중={foreign_buying}"
                + (
                    f", Finnhub감성={finnhub_sentiment:+.3f}"
                    f", 인사이더순매수={insider_net_shares:+,}주(매수{insider_buy_count}/매도{insider_sell_count})"
                    if finnhub_sentiment is not None else ""
                )
            )
            if finnhub_news:
                lines.append(
                    f"  [{ticker} 최신뉴스] " + " | ".join(finnhub_news)
                )

        lines.append("\n## 현재 보유 포지션")
        if positions:
            for p in positions:
                lines.append(
                    f"- {p['symbol']}: {p['quantity']}주 @ {p['avg_price']}원 "
                    f"(현재 {p.get('pnl_pct', 0):+.1f}%, "
                    f"손절가={p.get('stop_price', 0)}, 목표가={p.get('target_price', 0)})"
                )
        else:
            lines.append("- 없음")

        lines.append("\n## 관심 종목")
        for t, n in watchlist.items():
            lines.append(f"- {t} ({n})")

        # 리서치 이력 섹션
        if research_map:
            lines.append("\n## 올랜도킴 리서치 이력")
            for ticker, notes in research_map.items():
                lines.append(f"\n### {ticker}")
                for note in notes:
                    date_str = (note.get("created_at") or "")[:10]
                    source = note.get("source", "")
                    rating = note.get("rating", "")
                    tp = note.get("target_price", 0)
                    summary = note.get("summary", "")
                    catalyst = note.get("catalyst", "")
                    header_parts = [f"[{date_str}]"]
                    if source:
                        header_parts.append(source)
                    if rating:
                        header_parts.append(rating)
                    if tp:
                        header_parts.append(f"목표가 ${tp:,.0f}" if tp < 100000 else f"목표가 {tp:,.0f}원")
                    lines.append(" | ".join(header_parts))
                    if summary:
                        lines.append(f"- {summary}")
                    if catalyst:
                        lines.append(f"- 촉매: {catalyst}")

        lines.append(
            f"\n현재 매매 모드는 **{mode_label}**입니다. "
            "위 데이터를 바탕으로 현재 모드의 전략 규칙에 따라 "
            "지금 당장 실행할 최선의 매매 판단을 JSON으로 반환하세요."
        )
        return "\n".join(lines)
