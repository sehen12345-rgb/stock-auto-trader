import json
from typing import Any

import anthropic
from loguru import logger

SYSTEM_PROMPT = """당신은 한국 주식 자동매매 AI입니다. 올랜도킴 전략에 따라 매매 판단을 합니다.

## 올랜도킴 전략 핵심 규칙
1. 20일 이동평균선 위에서만 매수 (현재가 > MA20)
2. 거래량이 20일 평균 거래량의 1.5배 이상일 때 매수 신호
3. 52주 고점 대비 -10% 이내일 때 돌파 가능성 높음
4. 손절: 매입가 대비 -7% (자동 설정)
5. 목표: 매입가 대비 +20% (1차 익절)
6. 분산 투자: 종목당 포트폴리오의 최대 25%

## 응답 형식 (반드시 JSON만 반환)
{
  "decision": "BUY" | "SELL" | "HOLD",
  "ticker": "종목코드",
  "quantity": 수량(정수),
  "confidence": 확신도(0-100 정수),
  "reason": "한국어 근거 (2-3문장)"
}

매수/매도 신호가 없으면 decision을 "HOLD"로, ticker를 ""로 설정하세요."""


class LLMJudge:
    def __init__(self) -> None:
        self._client = anthropic.Anthropic()

    async def judge(
        self,
        market_data: dict[str, Any],
        positions: list[dict[str, Any]],
        watchlist: dict[str, str],
    ) -> dict[str, Any]:
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
                f"52주고점={data.get('week52_high')}"
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

        lines.append("\n위 데이터를 바탕으로 지금 당장 실행할 최선의 매매 판단을 JSON으로 반환하세요.")
        return "\n".join(lines)
