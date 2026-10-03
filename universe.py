"""F-01 전체 종목 목록 · F-03 기본 거름망 (1차: 목록 단계)."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json, text/plain, */*"}
CACHE = Path(__file__).parent / "data" / "universe_cache.json"

BAD_NAME_WORDS = ("warrant", "right", "unit", "preferred", "depositary share", "notes due", "% notes", "debenture")


def _from_screener() -> pd.DataFrame:
    """나스닥 스크리너: 미국 상장 보통주 전체 + 마지막 가격·거래량."""
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    rows = r.json()["data"]["rows"]
    df = pd.DataFrame(rows)
    df = df.rename(columns={"symbol": "ticker", "name": "name", "lastsale": "price", "volume": "volume",
                            "sector": "sector", "industry": "industry", "marketCap": "market_cap"})
    df["price"] = pd.to_numeric(df["price"].astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df["is_etf"] = False
    return df[["ticker", "name", "price", "volume", "sector", "industry", "is_etf"]]


def _etfs() -> pd.DataFrame:
    url = "https://api.nasdaq.com/api/screener/etf?tableonly=true&download=true&limit=10000"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        data = r.json()["data"]
        rows = data.get("data", {}).get("rows") or data.get("rows") or []
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df = df.rename(columns={"symbol": "ticker", "companyName": "name", "lastSalePrice": "price"})
        df["price"] = pd.to_numeric(df["price"].astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")
        df["volume"] = None
        df["sector"] = "ETF"
        df["industry"] = "ETF"
        df["is_etf"] = True
        return df[["ticker", "name", "price", "volume", "sector", "industry", "is_etf"]]
    except Exception as e:  # ETF 목록은 실패해도 보통주만으로 진행
        log.warning("ETF 목록 실패: %s", e)
        return pd.DataFrame()


def _from_nasdaqtrader() -> pd.DataFrame:
    """대체 경로: 나스닥 트레이더 기호 목록 (가격 없음)."""
    txt = requests.get("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt", headers=HEADERS, timeout=60).text
    df = pd.read_csv(io.StringIO(txt), sep="|")
    df = df[(df["Test Issue"] == "N") & (df["NextShares"] == "N")]
    out = pd.DataFrame({
        "ticker": df["Symbol"].astype(str),
        "name": df["Security Name"].astype(str),
        "price": None, "volume": None, "sector": None, "industry": None,
        "is_etf": df["ETF"].eq("Y"),
    })
    return out


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["ticker"]).copy()
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    # 우선주·워런트·유닛·권리 (기호에 ^ / . $ 가 있거나 이름에 해당 단어)
    df = df[~df["ticker"].str.contains(r"[\^/\.\$ ]", regex=True)]
    name = df["name"].astype(str).str.lower()
    mask = pd.Series(False, index=df.index)
    for w in BAD_NAME_WORDS:
        mask |= name.str.contains(w, regex=False)
    df = df[~mask]
    df["yf_ticker"] = df["ticker"].str.replace(".", "-", regex=False)
    return df.drop_duplicates("ticker").reset_index(drop=True)


def load_universe(cfg: dict, include_etf: bool = True) -> tuple[pd.DataFrame, str]:
    """반환: (종목 표, 메모). 실패하면 전날 목록을 써요."""
    note = ""
    try:
        df = _from_screener()
        if include_etf:
            etf = _etfs()
            if not etf.empty:
                df = pd.concat([df, etf], ignore_index=True)
    except Exception as e:
        log.warning("스크리너 실패, 기호 목록으로 대체: %s", e)
        try:
            df = _from_nasdaqtrader()
            note = "종목 목록을 대체 경로로 받았어요"
        except Exception as e2:
            log.error("종목 목록 실패: %s", e2)
            if CACHE.exists():
                df = pd.DataFrame(json.loads(CACHE.read_text(encoding="utf-8")))
                return df, "종목 목록을 못 받아 전날 목록을 썼어요"
            raise
    df = clean(df)
    # 1차 거름망: 가격을 아는 종목은 여기서 동전주·거래대금 미달을 미리 뺌
    known = df["price"].notna()
    cheap = known & (df["price"] < float(cfg["최소 주가(달러)"]))
    thin = known & df["volume"].notna() & (df["price"] * df["volume"] < float(cfg["최소 거래대금(달러)"]) * 0.5)
    df = df[~(cheap | thin)].reset_index(drop=True)
    try:
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_text(df.to_json(orient="records", force_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return df, note
