"""분기 공시 비교 (경제정리노트 '클로드로 주식 분석하는 8가지' 02번: 10-Q/10-K를 직전 분기와 비교).

SEC EDGAR의 XBRL 숫자(companyfacts)를 직접 읽어 직전 분기·작년 같은 분기와 비교해요. GPT 없이 계산 → 숫자를 지어내지 않아요.
SEC는 요청마다 연락처(이메일)를 적도록 해요 → 구글 시트 '설정' 탭 'SEC 연락 이메일'이 있으면 SEC부터 시도하고,
SEC에 못 닿으면(403 등) 야후가 10-Q에서 옮겨 둔 분기 재무제표로 같은 비교를 해요.
(문장으로 된 부분 — 고객·공급망·소송·규제 — 은 숫자 자료에 없어서 다루지 않아요.)
"""
from __future__ import annotations

import json
import logging
import time

import requests

log = logging.getLogger(__name__)

# (이름, 후보 태그들, 흐름(분기 값)인지)
ITEMS = [
    ("매출", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet", "InterestAndDividendIncomeOperating"], True),
    ("영업이익", ["OperatingIncomeLoss"], True),
    ("순이익", ["NetIncomeLoss", "ProfitLoss"], True),
    ("주당순이익(희석)", ["EarningsPerShareDiluted"], True),
    ("영업현금흐름", ["NetCashProvidedByUsedInOperatingActivities"], True),
    ("현금", ["CashAndCashEquivalentsAtCarryingValue", "Cash"], False),
    ("재고", ["InventoryNet"], False),
    ("매출채권", ["AccountsReceivableNetCurrent"], False),
    ("장기 부채", ["LongTermDebtNoncurrent", "LongTermDebt"], False),
    ("총부채", ["Liabilities"], False),
    ("자본", ["StockholdersEquity"], False),
]
_CIK: dict = {}


def _get(url: str, email: str):
    r = requests.get(url, headers={"User-Agent": f"us-stock-alert personal research {email}", "Accept-Encoding": "gzip"}, timeout=30)
    r.raise_for_status()
    time.sleep(0.2)  # SEC: 초당 10건 이하
    return r.json()


def cik(t: str, email: str) -> str | None:
    if not _CIK:
        try:
            for v in _get("https://www.sec.gov/files/company_tickers.json", email).values():
                _CIK[v["ticker"].upper()] = str(v["cik_str"]).zfill(10)
        except Exception as e:
            log.warning("SEC 종목 목록 실패: %s", e)
    return _CIK.get(t.upper().replace(".", "-"))


def _series(facts: dict, tags: list[str], flow: bool) -> dict:
    """frame(CY2025Q2 / CY2025Q2I) → 값. 처음 찾은 태그 사용."""
    for ns in ("us-gaap", "ifrs-full"):
        for tag in tags:
            f = (facts.get(ns) or {}).get(tag)
            if not f:
                continue
            for unit, vals in f.get("units", {}).items():
                out = {}
                for v in vals:
                    fr = v.get("frame") or ""
                    if flow and fr.startswith("CY") and "Q" in fr and not fr.endswith("I"):
                        out[fr] = (v["val"], v.get("form"), v.get("filed"), v.get("end"))
                    if not flow and fr.endswith("I") and "Q" in fr:
                        out[fr[:-1]] = (v["val"], v.get("form"), v.get("filed"), v.get("end"))
                if out:
                    return {"tag": tag, "unit": unit, "vals": out}
    return {}


def _prev_q(fr: str) -> str:
    y, q = int(fr[2:6]), int(fr[7])
    return f"CY{y - 1}Q4" if q == 1 else f"CY{y}Q{q - 1}"


def _yago(fr: str) -> str:
    return f"CY{int(fr[2:6]) - 1}Q{fr[7]}"


def compare(t: str, email: str) -> dict | None:
    c = cik(t, email)
    if not c:
        return None
    facts = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{c}.json", email).get("facts", {})
    rows, latest = [], None
    series = {name: _series(facts, tags, flow) for name, tags, flow in ITEMS}
    rev = series.get("매출") or series.get("순이익") or {}
    if not rev:
        return None
    latest = max(rev["vals"])
    filed = rev["vals"][latest][2]
    form = rev["vals"][latest][1]
    for name, _, flow in ITEMS:
        s = series.get(name)
        if not s:
            continue
        v = s["vals"]
        cur, prv, ya = v.get(latest), v.get(_prev_q(latest)), v.get(_yago(latest))
        if not cur:
            continue
        pct = lambda a, b: None if not b or not b[0] else round((a[0] / b[0] - 1) * 100 * (1 if b[0] > 0 else -1), 1)
        rows.append({"항목": name, "단위": s["unit"], "이번 분기": cur[0], "직전 분기": prv[0] if prv else None, "작년 같은 분기": ya[0] if ya else None,
                     "직전 대비 %": pct(cur, prv) if prv else None, "작년 대비 %": pct(cur, ya) if ya else None, "태그": s["tag"]})
    big = sorted([r for r in rows if r["직전 대비 %"] is not None], key=lambda r: -abs(r["직전 대비 %"]))[:5]
    changes = [f"{r['항목']}: 직전 분기보다 {r['직전 대비 %']:+.1f}%" + (f" (작년 같은 분기 대비 {r['작년 대비 %']:+.1f}%)" if r["작년 대비 %"] is not None else "") for r in big]
    return {"quarter": latest.replace("CY", "").replace("Q", " Q"), "form": form, "filed": filed, "cik": c, "rows": rows, "changes": changes,
            "src": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={c}&type=10-Q"}


YQ = [("매출", "is", "Total Revenue"), ("영업이익", "is", "Operating Income"), ("순이익", "is", "Net Income"), ("주당순이익(희석)", "is", "Diluted EPS"),
      ("영업현금흐름", "cf", "Operating Cash Flow"), ("현금", "bs", "Cash And Cash Equivalents"), ("재고", "bs", "Inventory"),
      ("매출채권", "bs", "Accounts Receivable"), ("장기 부채", "bs", "Long Term Debt"), ("총부채", "bs", "Total Liabilities Net Minority Interest"),
      ("자본", "bs", "Stockholders Equity")]


def compare_yahoo(t: str) -> dict | None:
    """SEC에 못 닿을 때: 야후가 10-Q에서 옮겨 둔 분기 재무제표로 같은 비교를 해요."""
    import pandas as pd
    import yfinance as yf
    tk = yf.Ticker(t.replace(".", "-"))
    src = {"is": tk.quarterly_income_stmt, "cf": tk.quarterly_cashflow, "bs": tk.quarterly_balance_sheet}
    q = src["is"]
    if q is None or q.empty or len(q.columns) < 2:
        return None
    cols = list(q.columns)
    cur, prv = cols[0], cols[1]
    ya = next((c for c in cols if 330 <= (cur - c).days <= 400), None)
    rows = []
    for name, k, r in YQ:
        df = src[k]
        if df is None or df.empty or r not in df.index:
            continue
        g = lambda c: None if c is None or c not in df.columns or pd.isna(df.loc[r, c]) else float(df.loc[r, c])
        a, b, y = g(cur), g(prv), g(ya)
        if a is None:
            continue
        pct = lambda x, base: None if x is None or not base else round((x / base - 1) * 100 * (1 if base > 0 else -1), 1)
        rows.append({"항목": name, "단위": "USD", "이번 분기": a, "직전 분기": b, "작년 같은 분기": y, "직전 대비 %": pct(a, b), "작년 대비 %": pct(a, y), "태그": r})
    if not rows:
        return None
    big = sorted([x for x in rows if x["직전 대비 %"] is not None], key=lambda x: -abs(x["직전 대비 %"]))[:5]
    changes = [f"{x['항목']}: 직전 분기보다 {x['직전 대비 %']:+.1f}%" + (f" (작년 같은 분기 대비 {x['작년 대비 %']:+.1f}%)" if x["작년 대비 %"] is not None else "") for x in big]
    return {"quarter": f"{cur:%Y-%m-%d} 끝난 분기", "form": "10-Q/10-K (야후 정리본)", "filed": "", "rows": rows, "changes": changes,
            "src": f"https://www.sec.gov/edgar/search/#/q={t}&forms=10-Q", "via": "yahoo"}


def run(tickers: list[str], email: str, old: dict | None = None) -> dict:
    """신고일이 바뀐 종목만 다시 계산. ETF 등 SEC 재무 숫자가 없는 종목은 건너뛰어요."""
    out = dict(old or {})
    sec_ok = bool(email and "@" in email)
    for t in tickers:
        r = None
        if sec_ok:
            try:
                r = compare(t, email)
            except Exception as e:
                log.info("SEC 비교 실패 %s: %s → 야후로", t, e)
                sec_ok = False if "403" in str(e) else sec_ok   # 막혀 있으면 나머지는 바로 야후로
        if not r:
            try:
                r = compare_yahoo(t)
            except Exception as e:
                log.info("야후 분기 비교 실패 %s: %s", t, e)
        if r:
            out[t] = r
    return {k: v for k, v in out.items() if k in tickers}
