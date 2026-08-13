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

### 반도체 섹터 특이사항 (올랜도킴 2026-08 시황)
- SK하이닉스(000660): 20일선 돌파 + 쌍바닥 → 상승 추세 전환 확인
- 삼성전자(005930): 매물대 소화 중, 완만한 상승 각도 예상
- 반도체 전반: 급등보다 울퉁불퉁한 시간조정 후 상승 예상
- 호르무즈 리스크, 엔화 강세, 금리 불균형 → 상승 속도 제한 요인

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
    ) -> dict[str, Any]:
        if self._client is None:
            result = self._rule_based_judge(market_data, positions)
            logger.info(f"[LLM] 규칙 판단: {result.get('decision')} {result.get('ticker')} "
                        f"확신도:{result.get('confidence')}%")
            return result

        prompt = self._build_prompt(market_data, positions, watchlist, trading_mode)
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

            if confidence > best_confidence and volume_surge:
                best_confidence = confidence
                best_ticker = ticker
                best_reason = ". ".join(reasons) + ". 올랜도킴 규칙 충족으로 매수 신호."

        if best_ticker and best_confidence >= 70:
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
    ) -> str:
        mode_labels = {
            "scalping": "스캘핑 (손절-1%/익절+1.5%)",
            "day_trading": "단타 (손절-2%/익절+4%)",
            "swing": "스윙 (손절-3.5%/익절+8~15%)",
            "long_term": "장기/올랜도킴 (손절-3.5%/익절+4~8%)",
        }
        mode_label = mode_labels.get(trading_mode, trading_mode)

        lines = [f"## 현재 매매 모드: {mode_label}", "", "## 현재 시세 데이터 (기술 지표 포함)"]
        for ticker, data in market_data.items():
            rsi = data.get("rsi")
            macd = data.get("macd")
            macd_sig = data.get("macd_signal")
            bb_upper = data.get("bb_upper")
            bb_lower = data.get("bb_lower")
            atr = data.get("atr")
            ema9 = data.get("ema9")
            pullback = data.get("pullback_detected", False)

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
                f"눌림목={pullback}"
            )

        lines.append("\n## 현재 보유 포지션")
        if positions:
            for p in positions:
                ts_info = ""
                lines.append(
                    f"- {p['symbol']}: {p['quantity']}주 @ {p['avg_price']}원 "
                    f"(현재 {p.get('pnl_pct', 0):+.1f}%, "
                    f"손절가={p.get('stop_price', 0)}, 목표가={p.get('target_price', 0)})"
                    f"{ts_info}"
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
