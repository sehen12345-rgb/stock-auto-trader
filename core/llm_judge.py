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

### 반도체 섹터 특이사항 (올랜도킴 2026-08 시황)
- SK하이닉스(000660): 쌍바닥+20일선 돌파 확인, 위 매물대 소화 기간 필요, 눌림목 시 매수
- 삼성전자(005930): 완만한 상승 각도, 급등 기대 금지, 매물대 소화 중
- MU(마이크론): 단기 급등 후 반락 패턴, 금리 외부 요인이 누름 → 조정 후 매수
- NVDA: 장기 보유 시 낙폭 축소 효과, 단기 변동성 무시하고 장기 보유
- IREN: 고점 대비 37% 하락, 단기 매매 금지, 장기 보유 관점
- DRAM: 하락추세선 돌파 → 2~3일 추세선 위 유지 확인 필수 후 매수
- SOX(반도체지수): 50일선 돌파 힘 부족, 급등 기대 금지

### 국채 금리 불균형 리스크 (2026-08 핵심 리스크)
- 10년물 5% 이상, 30년물 4.7% → 채권 매력↑, 주식 유동성↓
- 유가 상승폭보다 금리 상승폭이 더 큼 → 불균형 → 증시 부담
- 미국 국채 과잉 발행(부채 25% 국채로 상환) → 금리 구조적 상승 압력
- 엔화 강세 → 일본의 미국채 매도 → 금리 추가 상승 압력
- 호르무즈 협상 미타결 → 유가 불안 → 반도체 상승 제한
- 금리 5% 이상 구간: 신규 매수 극도로 신중, 소량 분할매수만 허용

### 올랜도킴 관심종목 (2026 하반기 장기 유망주)

**우량주 (안정적 장기 보유)**
- NVDA, AVGO, TSM, MU, AMD: 반도체/AI 핵심, 조정 시 분할매수
- MRVL(Marvell): EPS 4.05→9.16→11.92 고성장, 매출 2배 전망
- AMZN: 200달러 or 200일선 지지 확인 후 매수
- MSFT: 470달러 눌림목 매수 (소프트웨어/클라우드)
- ORCL, PANW: 소프트웨어/보안 섹터
- GOOG: 클라우드 실적 양호
- TSLA, CAT, GEV: 산업/에너지
- CLS, LITE, COHR, VRT: AI 인프라/광통신
- DELL: 350~360달러 눌림목 매수
- LLY: 헬스케어 장기 보유
- BAC 또는 JPM: 금융 섹터 대표주

**적자주식 (고위험 소량 투기)**
- IONQ, NBIS, RKLB, IREN, PL, ASTS, SPLX
- 급등 추격 절대 금지, 소량 분할매수, 손절 철저

**공통 매수 원칙**
- 급등 후 추격 금지 → 반드시 눌림목(되돌림)에서 분할매수
- AMD: 바닥 확인 후 진입 (선취매 금지)
- 장기 보유 관점 유지, 단기 변동성에 흔들리지 않기

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
        if _ANTHROPIC_API_KEY:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
                logger.info("[LLM] Anthropic 클라이언트 초기화 완료")
            except Exception as e:
                logger.warning(f"[LLM] Anthropic 클라이언트 초기화 실패: {e}")
        else:
            logger.info("[LLM] ANTHROPIC_API_KEY 없음 — 규칙 기반 판단 모드")

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
    ) -> dict[str, Any]:
        if self._client is None:
            result = self._rule_based_judge(market_data, positions)
            logger.info(f"[LLM] 규칙 판단: {result.get('decision')} {result.get('ticker')} "
                        f"확신도:{result.get('confidence')}%")
            return result

        prompt = self._build_prompt(
            market_data, positions, watchlist, trading_mode,
            fear_greed=fear_greed, kospi_change=kospi_change, nasdaq_change=nasdaq_change,
            news_context=news_context,
        )
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=512,
                system=SYSTEM_PROMPT,
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
            qty = max(1, int(2_500_000 // price)) if price > 0 else 1
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

            # 쌍바닥
            double_bottom = data.get("double_bottom", False)

            # MACD 방향
            macd_dir = ""
            if macd is not None and macd_sig is not None:
                macd_dir = "골든크로스↑" if macd > macd_sig else "데드크로스↓"

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
                f"눌림목={pullback}, "
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

        lines.append(
            f"\n현재 매매 모드는 **{mode_label}**입니다. "
            "위 데이터를 바탕으로 현재 모드의 전략 규칙에 따라 "
            "지금 당장 실행할 최선의 매매 판단을 JSON으로 반환하세요."
        )
        return "\n".join(lines)
