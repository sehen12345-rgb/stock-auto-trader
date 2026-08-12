import json
import os
from typing import Any

from loguru import logger

SYSTEM_PROMPT = """당신은 올랜도킴 매매 전략을 따르는 AI 트레이더입니다.

## 핵심 규칙
1. 20일 이동평균선 위에 있는 종목만 매수 (현재가 > MA20)
2. 거래량이 20일 평균의 1.5배 이상일 때만 신뢰
3. 52주 고점 돌파 시 강력 매수 신호
4. 손절선: 매수가 -3.5%
5. 익절: +4% ~ +8% 구간에서 단계적 청산
6. 동시 보유 최대 4종목, 종목당 최대 시드의 25%
7. 시장 전체 하락장(코스피 -1.5% 이하)에서는 신규 매수 금지

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

# 데모용 판단 풀
_DEMO_REASONS = [
    "삼성전자가 20일 이동평균선 위에서 거래량 급증 중. 52주 고점 돌파 임박으로 강력 매수 신호.",
    "SK하이닉스 HBM 수요 증가로 외국인 순매수 지속. MA20 상위에서 목표가 +6% 단계적 익절 예정.",
    "NVDA 실적 발표 앞두고 옵션 시장 강세. 현재가 MA20 상위 유지 중.",
    "코스피 전체 -0.8% 하락으로 신규 매수 보류. 현재 포지션 유지 (HOLD).",
    "AAPL 52주 고점 -2.3% 수준. 거래량 평균 대비 1.7배, 돌파 시 추가 매수 검토.",
    "LG화학 목표가 도달(-3.5% 손절선 접근). 리스크 관리 차원에서 매도 신호 발생.",
    "시장 전체 상승세이나 MSFT 거래량 부족 (평균 대비 0.9배). 신뢰도 낮아 관망.",
    "TSLA 변동성 확대 구간. 올랜도킴 전략상 4종목 보유 한도 검토 필요.",
    "NAVER 20일 이평선 하향 이탈. 매수 조건 미충족으로 관망 유지.",
    "삼성SDI 52주 고점 대비 -18% 수준. 반등 가능성 있으나 이평선 조건 미충족.",
]
_DEMO_POOL = [
    {"decision": "BUY",  "ticker": "005930", "quantity": 10, "confidence": 78},
    {"decision": "BUY",  "ticker": "NVDA",   "quantity": 5,  "confidence": 82},
    {"decision": "HOLD", "ticker": "",        "quantity": 0,  "confidence": 55},
    {"decision": "SELL", "ticker": "000660",  "quantity": 8,  "confidence": 71},
    {"decision": "HOLD", "ticker": "",        "quantity": 0,  "confidence": 62},
    {"decision": "BUY",  "ticker": "AAPL",   "quantity": 3,  "confidence": 69},
]


def _demo_decision() -> dict[str, Any]:
    import random
    base = random.choice(_DEMO_POOL).copy()
    base["reason"] = random.choice(_DEMO_REASONS)
    return base


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
            logger.info("[LLM] ANTHROPIC_API_KEY 없음 — 데모 판단 모드")

    async def judge(
        self,
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
        watchlist: dict[str, str],
    ) -> dict[str, Any]:
        if self._client is None:
            result = _demo_decision()
            logger.info(f"[LLM] 데모 판단: {result.get('decision')} {result.get('ticker')} "
                        f"확신도:{result.get('confidence')}%")
            return result

        prompt = self._build_prompt(market_data, positions, watchlist)
        try:
            response = self._client.messages.create(
                model="claude-sonnet-4-5",
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

    @staticmethod
    def _build_prompt(
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
        watchlist: dict[str, str],
    ) -> str:
        lines = ["## 현재 시세 데이터"]
        for ticker, data in market_data.items():
            lines.append(
                f"- {ticker}: 현재가={data.get('current_price')}, "
                f"MA20={data.get('ma20')}, "
                f"거래량={data.get('volume')}, "
                f"평균거래량={data.get('avg_volume_20')}, "
                f"52주고점={data.get('week52_high')}, "
                f"MA20상위={data.get('above_ma20')}, "
                f"거래량급증={data.get('volume_surge')}"
            )

        lines.append("\n## 현재 보유 포지션")
        if positions:
            for p in positions:
                lines.append(
                    f"- {p['symbol']}: {p['quantity']}주 @ {p['avg_price']}원 "
                    f"(현재 {p.get('pnl_pct', 0):+.1f}%)"
                )
        else:
            lines.append("- 없음")

        lines.append("\n## 관심 종목")
        for t, n in watchlist.items():
            lines.append(f"- {t} ({n})")

        lines.append("\n위 데이터를 바탕으로 올랜도킴 전략의 핵심 규칙에 따라 지금 당장 실행할 최선의 매매 판단을 JSON으로 반환하세요.")
        return "\n".join(lines)
