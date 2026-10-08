"""F-A21~F-A24 쉬운 재무제표.

미국 상장사의 연간 재무제표(최근 4~5년, 10-K 기준 · 야후 파이낸스 제공)를 받아
신호등 5개, 체력 점수(피오트로스키 F-score), 부도 위험(알트만 Z), 버핏 체크 8개,
'100달러를 팔면' 흐름, 회사 살림(재무상태·현금흐름)으로 바꿔요.

판정은 '튼튼해요 / 무난해요 / 조심해요 / 위험 신호'까지만 말하고, 사라 말라는 하지 않아요.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
CACHE = Path(__file__).parent / "data" / "financials_cache.json"  # 공개 저장소에 올리지 않음(.gitignore)

INCOME = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cogs": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross": ["Gross Profit"],
    "sga": ["Selling General And Administration"],
    "op": ["Operating Income", "Total Operating Income As Reported"],
    "interest": ["Interest Expense", "Interest Expense Non Operating"],
    "net": ["Net Income Common Stockholders", "Net Income",
            "Net Income From Continuing Operation Net Minority Interest"],
    "ebit": ["EBIT"],
    "shares_avg": ["Diluted Average Shares", "Basic Average Shares"],
}
BALANCE = {
    "assets": ["Total Assets"],
    "liab": ["Total Liabilities Net Minority Interest"],
    "equity": ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"],
    "cur_assets": ["Current Assets"],
    "cur_liab": ["Current Liabilities"],
    "lt_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "retained": ["Retained Earnings"],
    "cash": ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"],
    "shares_out": ["Ordinary Shares Number", "Share Issued"],
    "working_cap": ["Working Capital"],
}
CASHFLOW = {
    "ocf": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"],
    "capex": ["Capital Expenditure", "Capital Expenditure Reported"],
    "fcf": ["Free Cash Flow"],
    "dividends": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "buyback": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    "debt_repay": ["Repayment Of Debt"],
    "invest_cf": ["Investing Cash Flow"],
}
FIN_SECTORS = {"Financial Services", "Real Estate"}
FIN_NAME_HINTS = ("Capital Corp", "BDC", "Investment Corp", "Mortgage", "REIT", "Bancorp", "Financial")


# ---------------------------------------------------------------- 받기

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _pick(df, names: list[str], col) -> float | None:
    for n in names:
        if n in df.index:
            v = _num(df.at[n, col])
            if v is not None:
                return v
    return None


def fetch(ticker: str) -> dict | None:
    """연간 재무제표를 {years:[...], rows:{항목:[연도별 값]}} 로. 오래된 해 → 최근 해 순서."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    inc, bal, cf = t.income_stmt, t.balance_sheet, t.cashflow
    if inc is None or inc.empty:
        return None
    cols = sorted(inc.columns)[-5:]
    years = [c.strftime("%Y-%m-%d") for c in cols]
    rows: dict[str, list] = {}
    for spec, df in ((INCOME, inc), (BALANCE, bal), (CASHFLOW, cf)):
        for key, names in spec.items():
            vals = []
            for c in cols:
                vals.append(_pick(df, names, c) if df is not None and not df.empty and c in df.columns else None)
            rows[key] = vals
    return {"years": years, "rows": rows}


def load_cache() -> dict:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_cache(c: dict):
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- 계산 도구

def _last(xs, k=1):
    """뒤에서 k번째 값 (1 = 최근 해)."""
    return xs[-k] if xs and len(xs) >= k else None


def _div(a, b):
    return a / b if (a is not None and b not in (None, 0)) else None


def _pct(x, nd=1):
    return None if x is None else round(x * 100, nd)


def money(v) -> str:
    """$1.2조 / $340억 / $5,200만 처럼 한국식 단위로."""
    if v is None:
        return "—"
    s = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{s}${a / 1e12:.1f}조"
    if a >= 1e8:
        return f"{s}${a / 1e8:,.0f}억"
    if a >= 1e4:
        return f"{s}${a / 1e4:,.0f}만"
    return f"{s}${a:,.0f}"


def _per100(m: float) -> str:
    v = abs(m) * 100
    return f"{v:.1f}" if v < 1 else f"{v:.0f}"


def _is_financial(sector: str | None, name: str | None) -> bool:
    if sector in FIN_SECTORS:
        return True
    return bool(name) and any(h.lower() in name.lower() for h in FIN_NAME_HINTS)


# ---------------------------------------------------------------- 판단

def analyze(raw: dict, price: float | None, sector: str | None, name: str | None) -> dict:
    r = raw["rows"]
    years = raw["years"]
    g = lambda k, i=1: _last(r.get(k) or [], i)
    rev, net, op, gross = g("revenue"), g("net"), g("op"), g("gross")
    fin_co = _is_financial(sector, name)

    signals = []

    # 1. 돈을 버나
    op_m = _div(op, rev)
    net_m = _div(net, rev)
    if net is None:
        s1 = ("none", "자료가 부족해요")
    elif fin_co:
        s1 = ("good", f"1년 순이익 {money(net)}") if net > 0 else ("bad", f"1년 순손실 {money(net)}")
    elif net <= 0 or (op is not None and op < 0):
        s1 = ("bad", f"100달러 팔면 {_per100(net_m)}달러 손해" if net_m is not None else "손해를 보고 있어요")
    elif op_m is not None and op_m >= 0.10:
        s1 = ("good", f"100달러 팔면 {_per100(net_m)}달러 남음" if net_m is not None else "이익을 내고 있어요")
    else:
        s1 = ("warn", f"100달러 팔면 {_per100(net_m)}달러 남음 (얇은 편)" if net_m is not None else "이익이 얇아요")
    signals.append({"key": "profit", "title": {"good": "돈을 벌어요", "warn": "벌긴 하지만 얇아요",
                                              "bad": "손해를 보고 있어요", "none": "돈을 버나"}[s1[0]],
                    "tone": s1[0], "text": s1[1],
                    "nums": {"영업이익률": _pct(op_m), "순이익률": _pct(net_m), "순이익": money(net)}})

    # 2. 커지고 있나
    revs = [x for x in (r.get("revenue") or []) if x]
    ops = r.get("op") or []
    n = min(3, len(revs) - 1)
    cagr = ((revs[-1] / revs[-1 - n]) ** (1 / n) - 1) if n >= 1 and revs[-1 - n] > 0 and revs[-1] > 0 else None
    ups = sum(1 for a, b in zip(revs[-4:-1], revs[-3:]) if b > a)
    op_up = (ops[-1] is not None and len(ops) > n and ops[-1 - n] is not None and ops[-1] > ops[-1 - n]) if n >= 1 else None
    if cagr is None:
        s2 = ("none", "자료가 부족해요")
    elif cagr < 0:
        s2 = ("bad", f"매출 {n}년 연평균 {cagr * 100:+.0f}%")
    elif cagr >= 0.05 and op_up:
        s2 = ("good", f"매출 {ups}년 연속 증가" if ups >= 3 else f"매출 {n}년 연평균 {cagr * 100:+.0f}%")
    else:
        s2 = ("warn", f"매출 {n}년 연평균 {cagr * 100:+.0f}%" + ("" if op_up else " · 이익은 줄었어요"))
    signals.append({"key": "growth", "title": {"good": "커지고 있어요", "warn": "천천히 크거나 제자리",
                                              "bad": "작아지고 있어요", "none": "커지고 있나"}[s2[0]],
                    "tone": s2[0], "text": s2[1],
                    "nums": {"매출 연평균 성장률": _pct(cagr), "최근 매출": money(rev)}})

    # 3. 빚을 감당하나 (+ 알트만 Z)
    liab, eq, assets = g("liab"), g("equity"), g("assets")
    if liab is None and assets is not None and eq is not None:
        liab = assets - eq
    d2e = _div(liab, eq) if (eq or 0) > 0 else None
    interest = abs(g("interest")) if g("interest") is not None else None
    icov = _div(op, interest) if interest else None
    z = zone = None
    if not fin_co and assets and liab:
        wc = g("working_cap") if g("working_cap") is not None else ((g("cur_assets") or 0) - (g("cur_liab") or 0))
        shares = g("shares_out") or g("shares_avg")
        mv = (price or 0) * (shares or 0)
        ebit = g("ebit") if g("ebit") is not None else op
        if None not in (wc, g("retained"), ebit, rev) and mv > 0:
            z = 1.2 * wc / assets + 1.4 * g("retained") / assets + 3.3 * ebit / assets + 0.6 * mv / liab + 1.0 * rev / assets
            zone = "safe" if z > 2.99 else ("grey" if z >= 1.81 else "distress")
    if fin_co:
        s3 = ("info", "금융·리츠·BDC는 빚을 장사 도구로 써서 다르게 봐요")
    elif eq is not None and eq <= 0:
        strong = zone == "safe" and (icov is None or icov >= 5)
        s3 = ("warn", "주주 몫이 마이너스예요 · 자사주를 많이 사서 생긴 경우가 많아요") if strong \
            else ("bad", "주주 몫이 마이너스예요 (빚이 재산보다 많음)")
    elif d2e is None:
        s3 = ("none", "자료가 부족해요")
    else:
        bad = d2e > 2 or (icov is not None and icov < 1.5) or zone == "distress"
        if bad and zone == "safe" and (icov is None or icov >= 5) and d2e <= 6:
            bad = False  # 부채비율은 높아도 이자를 넉넉히 벌고 부도 위험 점수가 안전하면 '조금 많음'으로
        good = d2e <= 1 and (icov is None or icov >= 5) and zone != "distress"
        txt = f"빚이 주주 몫의 {d2e:.1f}배" + (f" · 이자의 {icov:.0f}배를 벌어요" if icov and icov < 100 else "")
        s3 = ("bad" if bad else "good" if good else "warn", txt)
    signals.append({"key": "debt", "title": {"good": "빚을 잘 감당해요", "warn": "빚이 조금 많아요",
                                            "bad": "빚이 부담돼요", "info": "빚은 업종 기준으로",
                                            "none": "빚을 감당하나"}[s3[0]],
                    "tone": s3[0], "text": s3[1],
                    "nums": {"부채비율(빚÷주주 몫)": None if d2e is None else round(d2e * 100), "이자보상배율": None if icov is None else round(icov, 1),
                             "부도 위험 점수(알트만 Z)": None if z is None else round(z, 2)}})

    # 4. 현금이 실제로 들어오나
    ocf, capex = g("ocf"), g("capex")
    fcf = g("fcf") if g("fcf") is not None else (None if ocf is None or capex is None else ocf + capex)
    if ocf is None:
        s4 = ("none", "자료가 부족해요")
    elif ocf <= 0:
        s4 = ("bad", "장사로 현금이 빠져나가요")
    elif net is not None and ocf >= net and (fcf is None or fcf > 0):
        s4 = ("good", "장사 현금 ≥ 장부상 이익")
    else:
        s4 = ("warn", "현금이 이익보다 적게 들어와요")
    signals.append({"key": "cash", "title": {"good": "현금이 실제로 들어와요", "warn": "현금이 조금 부족해요",
                                            "bad": "현금이 빠져나가요", "none": "현금이 들어오나"}[s4[0]],
                    "tone": s4[0], "text": s4[1],
                    "nums": {"영업현금흐름": money(ocf), "자유현금흐름": money(fcf), "순이익": money(net)}})

    # 5. 내 몫을 지키나 (주식 수)
    sh = [x for x in (r.get("shares_avg") or []) if x] or [x for x in (r.get("shares_out") or []) if x]
    chg = (sh[-1] / sh[-2] - 1) if len(sh) >= 2 and sh[-2] else None
    if chg is None:
        s5 = ("none", "자료가 부족해요")
    elif chg <= 0.005:
        s5 = ("good", f"주식 수 1년 {chg * 100:+.1f}%" + (" · 내 몫이 커져요" if chg < -0.005 else ""))
    elif chg <= 0.03:
        s5 = ("warn", f"주식 수 1년 {chg * 100:+.1f}%")
    else:
        s5 = ("bad", f"1년 {chg * 100:+.0f}% · 내 몫이 줄어요")
    signals.append({"key": "shares", "title": {"good": "내 몫을 지켜요", "warn": "주식 수가 조금 늘었어요",
                                              "bad": "주식 수가 늘었어요", "none": "내 몫을 지키나"}[s5[0]],
                    "tone": s5[0], "text": s5[1],
                    "nums": {"주식 수 변화(1년)": _pct(chg), "배당": money(abs(g("dividends")) if g("dividends") else None),
                             "자사주 매입": money(abs(g("buyback")) if g("buyback") else None)}})

    fscore, fmax = piotroski(r)
    buffett = buffett_checks(r, d2e)

    # 판정
    tones = [s["tone"] for s in signals if s["tone"] not in ("info", "none")]
    reds, greens = tones.count("bad"), tones.count("good")
    if reds >= 2 or zone == "distress":
        verdict = ("bad", "재무에 위험 신호가 있어요")
    elif reds == 1:
        verdict = ("warn", "재무에 조심할 곳이 있어요")
    elif greens >= 4 and fmax == 9 and fscore >= 7:
        verdict = ("good", "재무는 튼튼한 편이에요")
    elif greens >= 4 and fmax < 9 and fscore >= fmax - 2:
        verdict = ("good", "재무는 튼튼한 편이에요")
    else:
        verdict = ("info", "재무는 무난한 편이에요")
    worst = next((s for s in signals if s["tone"] == "bad"), None) or next((s for s in signals if s["tone"] == "warn"), None)
    reason = (f"다만 {worst['title']} — {worst['text']}" if worst and verdict[0] in ("good", "info")
              else f"{worst['title']} — {worst['text']}" if worst else f"신호 {len(tones)}개 중 {greens}개가 초록이에요")
    if len(tones) < 3:
        verdict, reason = ("none", "재무 자료가 부족해요"), "공시 숫자를 충분히 받지 못했어요"

    return {
        "available": True, "fy": years[-1] if years else "", "years": [y[:4] for y in years],
        "verdict": verdict[0], "verdict_text": verdict[1], "reason": reason,
        "financial_company": fin_co,
        "signals": signals, "fscore": fscore, "fscore_max": fmax,
        "z": None if z is None else round(z, 2), "z_zone": zone,
        "buffett": buffett, "buffett_pass": sum(1 for b in buffett if b["ok"] is True),
        "buffett_max": sum(1 for b in buffett if b["ok"] is not None),
        "flow100": flow100(r),
        "trend": {"revenue": r.get("revenue"), "op": r.get("op"), "net": r.get("net")},
        "balance": {"assets": assets, "liab": liab, "equity": eq, "cash": g("cash")},
        "cash": {"ocf": ocf, "capex": capex, "dividends": g("dividends"), "buyback": g("buyback"),
                 "debt_repay": g("debt_repay"), "fcf": fcf},
        "source": "연간 재무제표(10-K) · 야후 파이낸스 제공",
    }


def piotroski(r: dict) -> tuple[int, int]:
    """피오트로스키 F-score. 자료가 없는 항목은 빼고 (통과 수, 계산한 항목 수)."""
    g = lambda k, i=1: _last(r.get(k) or [], i)
    checks = []
    net, assets, assets0 = g("net"), g("assets"), g("assets", 2)
    roa, roa0 = _div(net, assets), _div(g("net", 2), assets0)
    ocf = g("ocf")
    checks.append(None if net is None else net > 0)
    checks.append(None if roa is None else roa > 0)
    checks.append(None if ocf is None else ocf > 0)
    checks.append(None if None in (ocf, net) else ocf > net)
    lev, lev0 = _div(g("lt_debt") or 0, assets), _div(g("lt_debt", 2) or 0, assets0)
    checks.append(None if None in (lev, lev0) else lev <= lev0)
    cr, cr0 = _div(g("cur_assets"), g("cur_liab")), _div(g("cur_assets", 2), g("cur_liab", 2))
    checks.append(None if None in (cr, cr0) else cr > cr0)
    sh, sh0 = g("shares_avg") or g("shares_out"), g("shares_avg", 2) or g("shares_out", 2)
    checks.append(None if None in (sh, sh0) else sh <= sh0 * 1.005)
    gm, gm0 = _div(g("gross"), g("revenue")), _div(g("gross", 2), g("revenue", 2))
    checks.append(None if None in (gm, gm0) else gm > gm0)
    at, at0 = _div(g("revenue"), assets), _div(g("revenue", 2), assets0)
    checks.append(None if None in (at, at0) else at > at0)
    done = [c for c in checks if c is not None]
    return sum(done), len(done)


def buffett_checks(r: dict, d2e: float | None) -> list[dict]:
    """버핏이 '오래 가는 경쟁 우위'의 흔적으로 보는 재무 습관 8개 (참고용, 절대 기준 아님)."""
    g = lambda k, i=1: _last(r.get(k) or [], i)
    rev, gross, sga, op, net = g("revenue"), g("gross"), g("sga"), g("op"), g("net")
    interest = abs(g("interest")) if g("interest") is not None else None
    eq, ltd, capex = g("equity"), g("lt_debt"), g("capex")
    nets = [x for x in (r.get("net") or []) if x is not None]
    gm = _div(gross, rev)
    roe = _div(net, eq) if (eq or 0) > 0 else None

    def item(title, ok, why, val):
        if isinstance(val, (int, float)):
            val = f"{val:g}년치" if "4년치" in title else f"{val:g}%"
        return {"title": title, "ok": ok, "why": why, "value": val}

    ups = sum(1 for a, b in zip(nets[:-1], nets[1:]) if b > a)
    return [
        item("매출총이익률 40% 안팎 이상", None if gm is None else gm >= 0.40,
             "물건값에 비해 원가가 낮다 = 가격을 올려도 손님이 떠나지 않는 힘", _pct(gm)),
        item("판매·관리비가 매출총이익의 절반 아래", None if None in (sga, gross) or not gross else sga / gross < 0.5,
             "벌어들인 돈을 광고·관리에 덜 써도 된다", None if None in (sga, gross) or not gross else _pct(sga / gross)),
        item("이자가 영업이익의 15% 아래", None if op is None or op <= 0 else (interest or 0) / op < 0.15,
             "빚에 기대지 않고 장사한다", None if op is None or op <= 0 else _pct((interest or 0) / op)),
        item("순이익률 10% 이상", None if net is None or not rev else net / rev >= 0.10,
             "100달러 팔면 10달러 넘게 남는다", None if net is None or not rev else _pct(net / rev)),
        item("이익이 여러 해 꾸준히 증가", None if len(nets) < 3 else ups >= len(nets) - 2,
             "한 해 반짝이 아니라 오래 버는 회사", f"{ups}/{max(0, len(nets) - 1)}년 증가" if len(nets) >= 2 else None),
        item("빚 없이도 자기자본이익률 15% 안팎", None if roe is None else (roe >= 0.15 and (d2e is None or d2e <= 1)),
             "주주 돈으로 해마다 15% 넘게 번다(빚으로 부풀린 게 아니라)", _pct(roe)),
        item("장기 빚을 순이익 4년치 안에 갚음", None if net is None or net <= 0 else (ltd or 0) <= 4 * net,
             "나빠져도 몇 년이면 빚을 정리할 수 있다", None if net is None or net <= 0 else round((ltd or 0) / net, 1)),
        item("설비 투자가 순이익의 절반 아래", None if net is None or net <= 0 or capex is None else abs(capex) <= 0.5 * net,
             "돈을 벌려고 큰돈을 계속 쏟지 않아도 된다", None if net is None or net <= 0 or capex is None else _pct(abs(capex) / net)),
    ]


def flow100(r: dict) -> dict | None:
    """매출을 100달러로 바꿨을 때 어디로 가고 얼마 남나."""
    g = lambda k: _last(r.get(k) or [], 1)
    rev, cogs, gross, op, net = g("revenue"), g("cogs"), g("gross"), g("op"), g("net")
    if not rev or rev <= 0 or net is None:
        return None
    if gross is None and cogs is not None:
        gross = rev - cogs
    if cogs is None and gross is not None:
        cogs = rev - gross
    parts = []
    if cogs is not None and gross is not None and op is not None:
        parts = [("물건·서비스 원가", cogs), ("회사 운영비", gross - op), ("세금·이자·기타", op - net)]
    elif op is not None:
        parts = [("원가·운영비", rev - op), ("세금·이자·기타", op - net)]
    else:
        parts = [("모든 비용", rev - net)]
    costs = [max(v, 0) / rev * 100 for _, v in parts]
    target = 100 - net / rev * 100  # 비용 합계는 '100 - 남는 돈'이 되어야 해요
    scale = target / sum(costs) if sum(costs) > 0 else 1
    out = [{"label": k, "per100": round(c * scale, 1)} for (k, _), c in zip(parts, costs)]
    out.append({"label": "남는 돈" if net >= 0 else "손해", "per100": round(net / rev * 100, 1)})
    return {"parts": out, "revenue": money(rev)}


# ---------------------------------------------------------------- 여러 종목

def summaries(tickers: list[str], meta: dict[str, dict], max_age_days: int = 7, pause: float = 0.4) -> dict[str, dict]:
    """meta: {ticker: {price, sector, name, etf}}. 원본 재무제표는 일주일 저장본을 재사용."""
    cache = load_cache()
    fresh_after = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()
    out, changed = {}, False
    for t in dict.fromkeys(tickers):
        m = meta.get(t, {})
        if m.get("etf"):
            out[t] = {"available": False, "reason": "ETF·펀드는 재무제표가 없어요. 담은 종목과 비용을 봐요(다음 단계)."}
            continue
        item = cache.get(t)
        if not item or item.get("_at", "") < fresh_after:
            try:
                raw = fetch(t)
                item = {"raw": raw, "_at": datetime.utcnow().isoformat()}
                cache[t] = item
                changed = True
            except Exception as e:
                log.info("재무제표 실패 %s: %s", t, e)
                item = item or {"raw": None}
            time.sleep(pause)
        raw = item.get("raw")
        if not raw:
            out[t] = {"available": False, "reason": "재무제표를 받지 못했어요"}
            continue
        try:
            out[t] = analyze(raw, m.get("price"), m.get("sector"), m.get("name"))
        except Exception as e:
            log.warning("재무 분석 실패 %s: %s", t, e)
            out[t] = {"available": False, "reason": "재무 계산 중 오류가 났어요"}
    if changed:
        save_cache(cache)
    return out
