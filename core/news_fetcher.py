"""실시간 뉴스/시황 수집 모듈 (5분 캐시)"""
import asyncio
import time
from typing import Any

import httpx
from loguru import logger

_cache: dict[str, Any] = {}
_cache_ts: float = 0
_CACHE_TTL = 300  # 5분


async def fetch_news_context() -> dict[str, Any]:
    global _cache, _cache_ts
    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    results: dict[str, Any] = {
        "kospi_news": [],
        "semiconductor_news": [],
        "us_news": [],
        "macro_news": [],
        "summary": "",
    }

    tasks = [
        _fetch_naver_finance_news(),
        _fetch_investing_macro(),
        _fetch_finviz_headlines(),
    ]
    outputs = await asyncio.gather(*tasks, return_exceptions=True)

    naver_data = outputs[0] if not isinstance(outputs[0], Exception) else {}
    investing_data = outputs[1] if not isinstance(outputs[1], Exception) else {}
    finviz_data = outputs[2] if not isinstance(outputs[2], Exception) else {}

    results["kospi_news"] = naver_data.get("kospi", [])
    results["semiconductor_news"] = naver_data.get("semiconductor", [])
    results["macro_news"] = investing_data.get("macro", [])
    results["us_news"] = finviz_data.get("us", [])

    all_headlines = (
        results["kospi_news"]
        + results["semiconductor_news"]
        + results["macro_news"]
        + results["us_news"]
    )
    results["summary"] = _summarize(all_headlines)

    _cache = results
    _cache_ts = now
    logger.info(f"[News] 뉴스 수집 완료: {len(all_headlines)}건")
    return results


async def _fetch_naver_finance_news() -> dict[str, list[str]]:
    """네이버 금융 RSS — 코스피/반도체 뉴스"""
    result: dict[str, list[str]] = {"kospi": [], "semiconductor": []}
    urls = {
        "kospi": "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258",
        "semiconductor": "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=261",
    }
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    async with httpx.AsyncClient(timeout=10) as client:
        for key, url in urls.items():
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    headlines = _parse_naver_headlines(resp.text)
                    result[key] = headlines[:5]
            except Exception as e:
                logger.debug(f"[News] 네이버 {key} 실패: {e}")
    return result


def _parse_naver_headlines(html: str) -> list[str]:
    import re
    pattern = r'class="articleSubject"[^>]*>\s*<a[^>]*>([^<]+)</a>'
    matches = re.findall(pattern, html)
    return [m.strip() for m in matches if m.strip()][:10]


async def _fetch_investing_macro() -> dict[str, list[str]]:
    """인베스팅닷컴 — 거시경제 뉴스 (RSS)"""
    result: dict[str, list[str]] = {"macro": []}
    rss_urls = [
        "https://kr.investing.com/rss/news_301.rss",  # 채권/금리
        "https://kr.investing.com/rss/news_25.rss",   # 원자재/에너지
    ]
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/rss+xml",
    }
    headlines: list[str] = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for url in rss_urls:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    items = _parse_rss_titles(resp.text)
                    headlines.extend(items[:3])
            except Exception as e:
                logger.debug(f"[News] Investing RSS 실패: {e}")
    result["macro"] = headlines[:6]
    return result


async def _fetch_finviz_headlines() -> dict[str, list[str]]:
    """Finviz — 미국 주식 뉴스 스크래핑"""
    result: dict[str, list[str]] = {"us": []}
    url = "https://finviz.com/news.ashx"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                import re
                pattern = r'class="nn-tab-link"[^>]*>([^<]+)</a>'
                matches = re.findall(pattern, resp.text)
                result["us"] = [m.strip() for m in matches if m.strip()][:6]
    except Exception as e:
        logger.debug(f"[News] Finviz 실패: {e}")
    return result


def _parse_rss_titles(xml: str) -> list[str]:
    import re
    pattern = r"<title><!\[CDATA\[([^\]]+)\]\]></title>|<title>([^<]+)</title>"
    matches = re.findall(pattern, xml)
    titles = [m[0] or m[1] for m in matches if (m[0] or m[1]).strip()]
    # 첫 번째는 채널 제목이므로 제외
    return [t.strip() for t in titles[1:] if t.strip()][:10]


_RISK_KEYWORDS = [
    "금리", "rate", "호르무즈", "전쟁", "war", "긴축", "hawkish",
    "인플레", "inflation", "급락", "crash", "하락", "sell-off",
    "공급망", "제재", "sanction", "채권", "bond", "yield",
]
_BULL_KEYWORDS = [
    "급등", "surge", "AI", "반도체", "semiconductor", "호실적",
    "beat", "earnings", "성장", "growth", "매수", "buy",
    "돌파", "breakout", "상승", "rally",
]


def _summarize(headlines: list[str]) -> str:
    if not headlines:
        return "뉴스 없음"
    risk_count = sum(
        1 for h in headlines
        if any(kw.lower() in h.lower() for kw in _RISK_KEYWORDS)
    )
    bull_count = sum(
        1 for h in headlines
        if any(kw.lower() in h.lower() for kw in _BULL_KEYWORDS)
    )
    sample = " | ".join(headlines[:4])
    if risk_count > bull_count:
        tone = f"⚠️ 리스크 신호 {risk_count}건 감지"
    elif bull_count > risk_count:
        tone = f"📈 강세 신호 {bull_count}건 감지"
    else:
        tone = "중립"
    return f"[뉴스 {len(headlines)}건] {tone} — {sample}"
