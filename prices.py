"""F-02 가격·재무 자료 수집. 무료(야후 파이낸스)로 시작하고, 막히면 이 파일만 바꾸면 돼요."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
FUND_CACHE = Path(__file__).parent / "data" / "fundamentals.json"


def download_history(tickers: list[str], period: str = "400d", batch: int = 200, pause: float = 2.0) -> dict[str, pd.DataFrame]:
    """일봉을 나눠서 천천히 받아요. 반환: {종목: 표(Open High Low Close Volume)}"""
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    tickers = list(dict.fromkeys(tickers))
    for i in range(0, len(tickers), batch):
        chunk = tickers[i:i + batch]
        for attempt in range(3):
            try:
                raw = yf.download(chunk, period=period, interval="1d", auto_adjust=True, group_by="ticker",
                                  threads=True, progress=False)
                break
            except Exception as e:  # 잠깐 쉬고 다시
                log.warning("가격 수집 재시도 %s/%s: %s", attempt + 1, 3, e)
                time.sleep(10 * (attempt + 1))
        else:
            continue
        for t in chunk:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df.dropna(subset=["Close"])
                if len(df) > 0:
                    out[t] = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            except KeyError:
                pass
        time.sleep(pause)
    return out


def _load_cache() -> dict:
    if FUND_CACHE.exists():
        try:
            return json.loads(FUND_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    FUND_CACHE.parent.mkdir(exist_ok=True)
    FUND_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


FIELDS = {
    "trailingPE": "per", "priceToBook": "pbr", "freeCashflow": "fcf", "marketCap": "market_cap",
    "revenueGrowth": "rev_growth", "earningsGrowth": "earn_growth", "returnOnEquity": "roe",
    "debtToEquity": "debt_to_equity", "sector": "sector", "industry": "industry",
    "longName": "long_name", "shortName": "short_name", "quoteType": "quote_type",
}


def fundamentals(tickers: list[str], max_age_days: int = 7, pause: float = 0.3) -> dict[str, dict]:
    """재무는 분기마다 바뀌어서 일주일 저장본을 써요. 오래됐거나 없는 종목만 새로 받아요."""
    import yfinance as yf

    cache = _load_cache()
    fresh_after = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
    changed = False
    for t in tickers:
        item = cache.get(t)
        if item and item.get("_at", "") >= fresh_after:
            continue
        try:
            info = yf.Ticker(t).info or {}
            rec = {v: info.get(k) for k, v in FIELDS.items()}
            mc, fcf = rec.get("market_cap"), rec.get("fcf")
            rec["fcf_yield"] = (fcf / mc) if (mc and fcf is not None and mc > 0) else None
            rec["_at"] = datetime.utcnow().isoformat()
            cache[t] = rec
            changed = True
        except Exception as e:
            log.info("재무 실패 %s: %s", t, e)
        time.sleep(pause)
    if changed:
        _save_cache(cache)
    return {t: cache[t] for t in tickers if t in cache}


def earnings_dates(tickers: list[str]) -> dict[str, str]:
    """다가오는 실적 발표일 (YYYY-MM-DD). 모르면 빠져요."""
    import yfinance as yf

    out = {}
    for t in tickers:
        try:
            cal = yf.Ticker(t).calendar
            d = None
            if isinstance(cal, dict):
                v = cal.get("Earnings Date")
                d = v[0] if isinstance(v, list) and v else v
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                d = cal.loc["Earnings Date"].iloc[0]
            if d is not None:
                out[t] = pd.Timestamp(d).strftime("%Y-%m-%d")
        except Exception:
            pass
    return out


def news_headlines(ticker: str, limit: int = 6) -> list[dict]:
    """최근 뉴스 제목·출처·날짜 (AI 위험 경고용)."""
    import yfinance as yf

    items = []
    try:
        for n in (yf.Ticker(ticker).news or [])[:limit]:
            c = n.get("content", n)
            title = c.get("title")
            date = c.get("pubDate") or c.get("providerPublishTime")
            if isinstance(date, (int, float)):
                date = datetime.utcfromtimestamp(date).strftime("%Y-%m-%d")
            elif isinstance(date, str):
                date = date[:10]
            prov = (c.get("provider") or {}).get("displayName") if isinstance(c.get("provider"), dict) else c.get("publisher")
            if title:
                items.append({"제목": title, "출처": prov or "", "날짜": date or ""})
    except Exception:
        pass
    return items


def last_price_intraday(tickers: list[str]) -> dict[str, dict]:
    """장중 감시용 현재가와 전일 종가 (무료 시세는 15분가량 늦을 수 있어요)."""
    import yfinance as yf

    out = {}
    if not tickers:
        return out
    raw = yf.download(tickers, period="5d", interval="5m", group_by="ticker", progress=False, auto_adjust=True, prepost=False)
    daily = yf.download(tickers, period="5d", interval="1d", group_by="ticker", progress=False, auto_adjust=True)
    for t in tickers:
        try:
            m = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            d = daily[t] if isinstance(daily.columns, pd.MultiIndex) else daily
            m = m.dropna(subset=["Close"])
            d = d.dropna(subset=["Close"])
            last = float(m["Close"].iloc[-1])
            today = m.index[-1].date()
            prev = d[d.index.date < today]["Close"]
            prev_close = float(prev.iloc[-1]) if len(prev) else None
            out[t] = {"price": last, "prev_close": prev_close}
        except Exception:
            pass
    return out
