"""4단계 GPT 기능 (기획서 12장 카드 → F-C9·F-C12·F-C14·F-A9·F-A10·F-C3 섀도).

매일 아침 리포트 끝에 한 번 돌고, 결과는 '앱 데이터'의 ai 묶음으로 저장돼 앱이 읽어요.
- 밤사이 브리핑 (보유 종목): 지난 하루 뉴스·목표가/등급 변경 → 종목마다 4줄. 없으면 「특이사항 없음」, 어제 본 소식은 다시 안 씀.
- 실적 카드: 최근 3거래일 안에 실적을 발표한 보유·후보 종목.
- 버핏 4관점 · 쉬운 리포트: 보유 + 후보 상위, 종목마다 7일에 한 번.
- 사전 부검 + 거부권(섀도): 자동 모의매매 주문 계획 종목. 거부권은 기록만 하고 주문에는 쓰지 않아요(12장 2단계).
숫자가 들어간 답은 모두 검사관(ai.checked)을 거쳐요. GPT가 꺼져 있으면(키·크레딧·한도) 아무것도 하지 않아요.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

import ai
import rag

log = logging.getLogger(__name__)
KEY = "ai"

BRIEF = """목표: 내 보유 종목에 지난 하루 무슨 일이 있었는지 아침 브리핑.
출력: {"items":[{"종목":"","무슨 일":"한 줄","시각":"자료의 시각","닿는 곳":"매출·마진·밸류에이션·수급 중","중요도":"상|중|하","이유":"한 줄","링크":"자료의 링크 하나"}]}
- 중요한 종목부터. 종목마다 가장 중요한 사건 1~2개. 모두 '중'이면 그 안에서 순서를 매겨.
- 자료에 없는 사건·링크는 쓰지 마."""

EARN = """목표: 방금 나온 분기 실적을 표 하나로.
출력: {"분기":"","발표일":"","표":[{"항목":"매출|영업이익|EPS","실제":"","예상(컨센서스)":"","작년 같은 분기":"","출처":""}],
"가이던스":"자료에 없으면 「확인 못 함」","마진이 변한 이유":"자료로 알 수 있는 만큼, 없으면 「확인 못 함」",
"현금흐름":"영업현금흐름이 순이익만큼 늘었나, 없으면 「확인 못 함」","판정":{"실적":"상회|부합|하회|확인 못 함","가이던스":"상회|부합|하회|확인 못 함"},"한 줄":""}
- 예상치는 자료의 출처(야후 컨센서스)를 그대로 적어. 자료에 없는 칸은 「확인 못 함」."""

B4 = """목표: 워런 버핏식 4관점 점검(사업 이해·경쟁 우위·경영진·가격).
출력: {"관점":[{"이름":"사업 이해|경쟁 우위|경영진|가격","판정":"통과|조건부|탈락","근거":["자료 숫자·사실 1~3개"]}],"종합":"통과|조건부|탈락","한 줄":""}
- 경영진은 자료에 자사주·주식 수·부채 정책 같은 근거가 없으면 '조건부'와 「확인 못 함」.
- 가격은 PER·PBR·잉여현금흐름 수익률 같은 자료 숫자로만."""

REP = """목표: 초보자가 5초에 이해하는 기업 리포트.
출력: {"7줄 요약":["7개 문장"],"신호":[{"지표":"","값":"자료 숫자","좋음/나쁨":"좋음|보통|나쁨","한 줄":""}],"10년 주인이라면":"한 단락"}
- 신호는 4~6개. 숫자는 자료의 재무 요약에서만."""

PM = """목표: 사기 전에 실패부터 가정하는 사전 부검. 이 종목이 6개월 뒤 30% 떨어졌다고 가정해.
출력: {"원인":[{"시나리오":"","가능성":"상|중|하","가장 먼저 보일 신호":"","지금 값":"자료 숫자 또는 「확인 못 함」","다음 확인일":""}],
"이미 반영된 기대":"PER 등 자료 숫자와 계산식","큰 하락 이력":"자료의 하락 구간을 날짜와 함께","맞으려면 필요한 조건":["3개"],
"막을 이유":{"있음":true|false,"이유":"유상증자·소송·감사 의견·실적 경고 같은 위험이 자료에 있으면 한 줄, 없으면 빈칸","출처":"자료 링크"}}
- 원인은 3개, 가능성 순. 매수·매도 결론은 내지 마."""


def _iso(x) -> str:
    try:
        if isinstance(x, (int, float)):
            return datetime.fromtimestamp(x, tz=timezone.utc).isoformat(timespec="minutes")
        return pd.Timestamp(x).isoformat()[:16]
    except Exception:
        return str(x or "")[:16]


def gather(t: str, deep: bool = False) -> dict:
    """무료 자료(야후)만 모아요. 실패한 칸은 비워 둬요."""
    import yfinance as yf
    tk = yf.Ticker(t.replace(".", "-"))
    out = {"종목": t, "뉴스": [], "등급 변경": [], "받은 시각": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    try:
        for n in (tk.news or [])[:12]:
            c = n.get("content", n)
            prov = c.get("provider") if isinstance(c.get("provider"), dict) else {}
            url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
            out["뉴스"].append({"id": n.get("id") or c.get("id") or url, "제목": c.get("title"), "요약": (c.get("summary") or "")[:400],
                              "시각": _iso(c.get("pubDate") or c.get("providerPublishTime")), "출처": prov.get("displayName") or c.get("publisher"),
                              "링크": url})
    except Exception as e:
        log.info("뉴스 실패 %s: %s", t, e)
    try:
        ud = tk.upgrades_downgrades
        if ud is not None and len(ud):
            ud = ud.reset_index().sort_values(ud.reset_index().columns[0], ascending=False).head(8)
            out["등급 변경"] = [{k: (str(v)[:16] if k == ud.columns[0] else v) for k, v in r.items()} for r in ud.to_dict("records")]
    except Exception:
        pass
    if deep:
        try:
            info = tk.info or {}
            keep = ("longName", "sector", "industry", "longBusinessSummary", "fullTimeEmployees", "marketCap", "trailingPE", "forwardPE",
                    "priceToBook", "profitMargins", "operatingMargins", "returnOnEquity", "revenueGrowth", "earningsGrowth",
                    "debtToEquity", "freeCashflow", "targetMeanPrice", "numberOfAnalystOpinions", "heldPercentInsiders",
                    "sharesOutstanding", "dividendYield", "payoutRatio", "beta", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "currentPrice")
            out["회사 정보(야후)"] = {k: info.get(k) for k in keep if info.get(k) is not None}
            if "longBusinessSummary" in out["회사 정보(야후)"]:
                out["회사 정보(야후)"]["longBusinessSummary"] = out["회사 정보(야후)"]["longBusinessSummary"][:1200]
        except Exception:
            pass
        try:
            eh = tk.earnings_history
            if eh is not None and len(eh):
                out["실적 이력(야후 컨센서스)"] = eh.reset_index().astype(str).tail(4).to_dict("records")
        except Exception:
            pass
        try:
            q = tk.quarterly_income_stmt
            rows = [r for r in ("Total Revenue", "Operating Income", "Net Income", "Diluted EPS") if r in q.index]
            out["분기 손익(야후)"] = {str(c)[:10]: {r: (None if pd.isna(q.loc[r, c]) else float(q.loc[r, c])) for r in rows} for c in q.columns[:5]}
        except Exception:
            pass
        try:
            qc = tk.quarterly_cashflow
            if "Operating Cash Flow" in qc.index:
                out["분기 영업현금흐름(야후)"] = {str(c)[:10]: float(qc.loc["Operating Cash Flow", c]) for c in qc.columns[:5] if not pd.isna(qc.loc["Operating Cash Flow", c])}
        except Exception:
            pass
        try:
            h = tk.history(period="5y", interval="1wk")["Close"].dropna()
            peak, drops, start = h.iloc[0], [], None
            for d, v in h.items():
                if v > peak:
                    peak, start = v, d
                dd = v / peak - 1
                if dd < -0.3 and (not drops or (d - pd.Timestamp(drops[-1]["바닥"])).days > 180):
                    drops.append({"고점": str(start)[:10] if start is not None else "", "바닥": str(d)[:10], "하락률": round(dd * 100, 1)})
            out["5년 큰 하락(30% 넘게)"] = drops[:5]
            out["5년 주가 범위"] = {"최저": round(float(h.min()), 2), "최고": round(float(h.max()), 2), "지금": round(float(h.iloc[-1]), 2)}
        except Exception:
            pass
    return out


def last_report_days(t: str) -> int | None:
    """가장 최근 실적 발표가 며칠 전이었나 (야후 실적 일정). 모르면 None."""
    try:
        import yfinance as yf
        ed = yf.Ticker(t.replace(".", "-")).get_earnings_dates(limit=6)
        now = pd.Timestamp.now(tz="UTC")
        past = [d for d in ed.index if d.tz_convert("UTC") <= now]
        return (now - max(past).tz_convert("UTC")).days if past else None
    except Exception:
        return None


def _load(store) -> dict:
    try:
        raw = store.get_blob(KEY)
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def run_daily(store, app: dict, cfg: dict, sim_state: dict | None) -> dict | None:
    ok, why = ai.enabled()
    blob = _load(store)
    blob["status"] = ai.status()
    if not ok:
        blob["off"] = why
        store.put_blob(KEY, json.dumps(blob, ensure_ascii=False, default=str))
        log.info("GPT 기능 건너뜀: %s", why)
        return blob
    blob.pop("off", None)
    today = app.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
    n = int(float(cfg.get("AI 브리핑 종목 수", 8)))
    holds = [h["t"] for h in app.get("holdings", [])]
    picks = sorted([p for b in app.get("bands", []) for p in b["picks"]], key=lambda p: -(p.get("total") or 0))
    pick_t = [p["t"] for p in picks if p["t"] not in holds]
    focus = (holds + pick_t)[:max(n, len(holds[:n]))]
    fin = app.get("fin") or {}
    seen = set(blob.get("seen", []))
    docs, facts_all = [], {}

    # ---- 밤사이 브리핑 (보유) ----
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="minutes")
    brief_in, quiet = {}, []
    for t in holds[:n]:
        f = gather(t)
        facts_all[t] = f
        fresh = [x for x in f["뉴스"] if x.get("id") not in seen and (x.get("시각") or "") >= cutoff[:16]]
        grades = [g for g in f["등급 변경"] if str(list(g.values())[0])[:10] >= cutoff[:10]]
        for x in f["뉴스"]:
            docs.append({"종목": t, "날짜": (x.get("시각") or "")[:10], "종류": "뉴스", "제목": x.get("제목"), "출처": x.get("링크") or "",
                         "내용": f"{x.get('제목')}. {x.get('요약') or ''}"})
        if fresh or grades:
            brief_in[t] = {"뉴스": fresh[:6], "목표가·등급 변경": grades[:4]}
        else:
            quiet.append(t)
        seen |= {x.get("id") for x in fresh}
    items = []
    if brief_in:
        r = ai.checked("밤사이 브리핑", BRIEF, brief_in, "small", 3000)
        if r:
            items = r.get("items", [])
            blob["brief_check"] = r.get("_검사")
    blob["brief"] = {"date": today, "items": items, "quiet": quiet,
                     "note": "보유 종목에 지난 하루 특이사항 없음" if not items and holds else ""}
    blob["seen"] = list(seen)[-400:]

    # ---- 실적 카드 · 4관점 · 쉬운 리포트 ----
    earn, b4, rep = blob.get("earn", {}), blob.get("b4", {}), blob.get("rep", {})
    week_ago = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    for t in focus:
        need_b4 = (b4.get(t) or {}).get("date", "") < week_ago
        need_rep = (rep.get(t) or {}).get("date", "") < week_ago
        need_earn = False
        if (earn.get(t) or {}).get("date", "") < week_ago:
            ld = last_report_days(t)
            need_earn = ld is not None and ld <= 4
        if not (need_b4 or need_rep or need_earn):
            continue
        f = gather(t, deep=True)
        f["재무 요약(앱)"] = fin.get(t)
        facts_all[t] = f
        if need_earn:
            r = ai.checked("실적 카드", EARN, f, "big", 3000)
            if r:
                earn[t] = dict(r, date=today)
        if need_b4:
            r = ai.checked("버핏 4관점", B4, f, "small", 2500)
            if r:
                b4[t] = dict(r, date=today)
        if need_rep:
            r = ai.checked("쉬운 리포트", REP, f, "small", 2500)
            if r:
                rep[t] = dict(r, date=today)
    keep = set(focus) | set(holds)
    blob["earn"] = {k: v for k, v in earn.items() if k in keep and v.get("date", "") >= week_ago}
    blob["b4"] = {k: v for k, v in b4.items() if k in keep}
    blob["rep"] = {k: v for k, v in rep.items() if k in keep}

    # ---- 사전 부검 + 거부권 섀도 (자동 모의 주문 계획) ----
    pm = blob.get("pm", {})
    veto_log = blob.get("veto", [])
    for o in (sim_state or {}).get("pending", []):
        t = o["t"]
        if (pm.get(t) or {}).get("date") == today:
            continue
        f = facts_all.get(t) if (facts_all.get(t) or {}).get("회사 정보(야후)") else gather(t, deep=True)
        f["재무 요약(앱)"] = fin.get(t)
        f["주문 계획"] = {k: o[k] for k in ("qty", "limit", "stop", "target", "why")}
        r = ai.checked("사전 부검", PM, f, "small", 3000)
        if r:
            pm[t] = dict(r, date=today)
            v = r.get("막을 이유") or {}
            veto_log.append({"date": today, "t": t, "veto": bool(v.get("있음")), "why": v.get("이유", ""), "src": v.get("출처", "")})
    blob["pm"] = {k: v for k, v in pm.items() if v.get("date", "") >= week_ago}
    blob["veto"] = veto_log[-200:]

    # ---- RAG 자료 쌓기 ----
    try:
        if docs:
            rag.add(store, docs)
    except Exception as e:
        log.warning("RAG 저장 실패: %s", e)
    ai.flush()
    blob["status"] = ai.status()
    blob["at"] = datetime.utcnow().isoformat(timespec="minutes")
    store.put_blob(KEY, json.dumps(blob, ensure_ascii=False, default=str))
    return blob


def brief_text(blob: dict) -> str:
    b = (blob or {}).get("brief") or {}
    lines = []
    imp = {"상": 0, "중": 1, "하": 2}
    for x in sorted(b.get("items") or [], key=lambda x: imp.get(x.get("중요도"), 3)):
        lines.append(f"[{x.get('중요도', '')}] {x.get('종목')} — {x.get('무슨 일')} ({x.get('시각', '')})\n   닿는 곳: {x.get('닿는 곳', '')} · {x.get('이유', '')}\n   {x.get('링크', '')}")
    if b.get("quiet"):
        lines.append("특이사항 없음: " + ", ".join(b["quiet"]))
    return "\n".join(lines)
