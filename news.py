"""경제뉴스 → 미국주식 트렌드 리포트 (초등학생도 5초에 이해하게).

매일 아침 리포트 끝에 한 번 돌아요 (GPT가 꺼져 있으면 숫자·뉴스 목록만 저장).
자료(무료): 야후 시세(지수·금리·달러·유가·업종 ETF), 야후 뉴스, 구글 뉴스 RSS(영어·한국어).
결과는 '앱 데이터'의 ai 묶음 안 news 로 저장 → 앱 '뉴스' 탭과 홈 카드.

GPT 호출
  1) 시장 요약: 시장 날씨·5초 요약·숫자 3개·트렌드(호재·악재·소음)·오늘의 단어·더 물어보기
  2) 업종 13개 전부 깊게 (5개씩 3번): 신호등·예시·좋은 점/조심할 점·시나리오 3가지·
     강세 vs 약세 토론 + 위험관리 3명(TradingAgents식)·확인할 것·팔아야 하는 신호·내 보유
  3) 내 보유 종목 하나하나: 신호등·한 줄·호재/악재/소음·확인할 것
모두 검사관(ai.checked)을 거쳐요.
사용자가 공유한 프롬프트 카드(경제정리노트 15가지·클로드 금융 6가지)를 지시에 반영했어요
(뉴스 영향 분석·리스크 점검·시나리오·재무 위험·밸류에이션·매도 기준·'기업명 + 지표 + 기간').
'설정' 탭 '뉴스 관심 주제'는 업종을 제한하지 않고 목록 맨 위에 고정만 해요.
"""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import requests

import ai

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

MARKET = {"SPY": "S&P500(미국 큰 회사 500개)", "QQQ": "나스닥100(기술주)", "DIA": "다우(전통 대기업)", "IWM": "러셀2000(작은 회사)",
          "^VIX": "공포지수(VIX)", "^TNX": "미국 10년 국채 금리", "DX-Y.NYB": "달러 힘(달러 인덱스)", "CL=F": "국제 유가(WTI)", "GC=F": "금 가격"}

# 업종 13개: 이름 · 대표 ETF(첫째가 기준) · 영어 검색어 · 한국어 검색어 · 보유 종목을 고를 업종 단어
SECTOR_DEF = [
    ("기술", ["XLK", "SMH"], "technology semiconductor stocks", "미국 기술주", ["technology", "software", "semiconductor"]),
    ("헬스케어", ["XLV", "IBB"], "healthcare pharma stocks", "미국 헬스케어주", ["healthcare", "health", "drug", "medical", "biotech", "pharma", "diagnostic"]),
    ("금융", ["XLF", "KBE"], "bank financial stocks", "미국 은행주", ["financial services", "bank", "insurance", "capital markets"]),
    ("에너지", ["XLE"], "energy oil stocks", "미국 에너지주 유가", ["energy", "oil", "midstream"]),
    ("전기·가스(유틸리티)", ["XLU"], "utilities stocks power", "미국 유틸리티주", ["utilities", "utility"]),
    ("쓰고 싶은 소비(자동차·쇼핑)", ["XLY"], "consumer discretionary retail stocks", "미국 소비재 유통주", ["consumer cyclical", "auto", "retail", "restaurant", "travel"]),
    ("꼭 쓰는 소비(식품·생필품)", ["XLP"], "consumer staples stocks", "미국 필수소비재", ["consumer defensive", "food", "tobacco", "beverage", "household"]),
    ("산업재", ["XLI"], "industrial stocks aerospace", "미국 산업재", ["industrials", "aerospace", "machinery", "railroad", "airline"]),
    ("부동산 리츠", ["XLRE", "VNQ"], "REIT real estate stocks", "미국 리츠", ["real estate", "reit"]),
    ("통신·미디어", ["XLC"], "communication media stocks", "미국 통신 미디어주", ["communication", "media", "telecom", "entertainment", "internet content"]),
    ("소재", ["XLB"], "materials chemicals mining stocks", "미국 소재주", ["basic materials", "chemical", "metal", "mining", "gold", "steel"]),
    ("모기지 리츠", ["REM", "MORT"], "mortgage REIT", "모기지 리츠", ["reit - mortgage", "mortgage"]),
    ("배당 BDC", ["BIZD"], "BDC business development company", "BDC 배당주", ["asset management", "credit services"]),
]
SECTOR_NAMES = [x[0] for x in SECTOR_DEF]

COMMON_RULES = """- 문장은 짧게(한 줄 40자 안팎). 어려운 말은 쓰지 말고, 꼭 써야 하면 괄호로 풀어.
- 숫자는 '자료'의 시세 표·종목 정보에 있는 것만. 뉴스 내용은 자료의 제목·요약에 있는 것만.
- 값 칸에는 숫자와 단위만 써(예: +1.2%). 출처 설명은 값 칸에 넣지 마.
- 사라·팔라·추천 금지. 신호등은 지금 뉴스·흐름의 방향만: 초록=대체로 좋음, 노랑=섞임, 빨강=조심할 신호가 더 많음."""

TASK = """목표: 경제뉴스를 거의 안 보는 초보자에게 오늘 미국 주식 흐름을 '초등학생도 5초에 이해'하게 알려줘.
규칙:
""" + COMMON_RULES + """
- 모든 트렌드에 생활 속 '예시'(가게·용돈·장보기·학교 같은 비유)를 하나씩 붙여.
- 뉴스마다 호재(좋은 소식)·악재(나쁜 소식)·소음(주가에 오래 영향 없을 소식)으로 나눠 (뉴스 영향 분석).
- '내 보유와 닿는 소식'은 자료의 보유 목록에 있는 종목만, 구분은 호재·악재·소음 중 하나.
- '더 물어보기'는 '기업명 + 지표 + 기간'이 구체적인 질문 3개 (예: "NLY의 최근 4개 분기 주당 장부가치와 배당 변화를 정리해줘").
출력 JSON:
{"기준일":"YYYY-MM-DD","5초 요약":["이모지+한 줄","",""],
 "시장 날씨":{"날씨":"맑음|구름 조금|흐림|비|폭풍","한 줄":"","예시":""},
 "숫자 3개":[{"이름":"","값":"","쉬운 뜻":""}],
 "트렌드":[{"제목":"","한 줄":"","예시":"","구분":"호재|악재|소음","왜 중요":"","관련 업종":"","출처":[{"제목":"","링크":""}]}],
 "내 보유와 닿는 소식":[{"종목":"","한 줄":"","구분":"호재|악재|소음"}],
 "오늘의 단어":[{"말":"","쉬운 뜻":"","예시":""}],
 "더 물어보기":["","",""]}
- 트렌드 3~5개, 오늘의 단어 2~3개."""

TASK_SEC = """목표: 자료에 있는 미국 주식 업종 하나하나를 초보자가 5초에 이해하게 깊게 정리해줘.
규칙:
""" + COMMON_RULES + """
- '5초 답'은 업종 설명이 아니라 '지금 상황'이야: 이번 주 ETF 흐름(1주 %)과 뉴스로 본 오늘의 한 줄 (예: "유가 급등에 1주 +4%, 당분간 순풍").
- 업종마다 생활 속 '예시' 하나 (가게·용돈·장보기·학교 같은 비유).
- 리스크 점검: 좋은 점 2개, 조심할 점 2~3개 (실적·경쟁·규제·금리·유가·밸류에이션 관점).
- 시나리오 3가지(낙관·기준·비관)와 각각 그렇게 되는 조건.
- TradingAgents식 토론: 강세 연구원(좋게 보는 근거)·약세 연구원(나쁘게 보는 근거) 한 줄씩, 위험관리 3명(공격형·중립형·보수형) 한 줄씩,
  '정리'에서는 어느 쪽 근거가 더 많은지만 말해 (결론 금지).
- '확인할 것'은 숫자로 확인할 지표 2개 (PER·PBR·부채·배당·매출 성장 등, 기업명 + 지표 + 기간이면 더 좋아).
- '팔아야 하는 신호' 2개 (매도 기준: 이렇게 되면 투자 논리가 깨진 것).
- 모기지 리츠는 금리·이자 차이·빚(레버리지)·배당 삭감·장부가치·조기상환을, 유틸리티는 금리·전기 수요(데이터센터)를, 에너지는 유가를 꼭 짚어.
- 뉴스가 적으면 '뉴스 적음'이라고 쓰고 흐름 숫자로만 판단해.
- 자료의 업종을 하나도 빼지 말고 자료의 이름 그대로 써.
출력 JSON:
{"업종":[{"업종":"","ETF":"","신호등":"초록|노랑|빨강","1주":"","5초 답":"","예시":"","좋은 점":["",""],"조심할 점":["",""],
  "시나리오":{"낙관":"","기준":"","비관":""},"토론":{"강세":"","약세":"","공격형":"","중립형":"","보수형":"","정리":""},
  "확인할 것":["",""],"팔아야 하는 신호":["",""],"출처":[{"제목":"","링크":""}]}]}"""

TASK_MINE = """목표: 내 보유 종목 하나하나에 대해 초보자가 5초에 이해하는 한 줄 의견을 줘.
규칙:
""" + COMMON_RULES + """
- 종목마다: 자료의 뉴스 제목으로 무슨 일이 있었는지 한 줄 (뉴스가 있으면 '소식 없음'이라고 하지 마), 호재·악재·소음·소식 없음 구분, 확인할 것 하나(기업명 + 지표 + 기간을 구체적으로).
- 뉴스가 없으면 '최근 소식 없음'과 노랑. 자료의 종목을 하나도 빼지 마.
출력 JSON:
{"종목":[{"종목":"","신호등":"초록|노랑|빨강","한 줄":"","구분":"호재|악재|소음|소식 없음","확인할 것":"","출처":{"제목":"","링크":""}}]}"""


def _pct(a, b):
    try:
        return round((float(a) / float(b) - 1) * 100, 2)
    except Exception:
        return None


def market_table() -> dict:
    import yfinance as yf
    syms = list(dict.fromkeys(list(MARKET) + [e for x in SECTOR_DEF for e in x[1]]))
    out = {}
    try:
        df = yf.download(syms, period="3mo", interval="1d", progress=False, auto_adjust=True, threads=True)["Close"]
    except Exception as e:
        log.warning("시세 실패: %s", e)
        return out
    names = {x[1][0]: x[0] for x in SECTOR_DEF}
    for s in syms:
        if s not in df:
            continue
        c = df[s].dropna()
        if len(c) < 6:
            continue
        last = float(c.iloc[-1])
        row = {"이름": MARKET.get(s) or names.get(s) or s, "날짜": str(c.index[-1])[:10], "값": round(last, 2),
               "1일": _pct(last, c.iloc[-2]), "1주": _pct(last, c.iloc[-6]), "1달": _pct(last, c.iloc[-22]) if len(c) > 22 else None}
        if s == "^TNX":  # 금리는 % 자체가 값 → 변화는 %p
            row.update({"단위": "%", "1일": round(last - float(c.iloc[-2]), 2), "1주": round(last - float(c.iloc[-6]), 2),
                        "1달": round(last - float(c.iloc[-22]), 2) if len(c) > 22 else None, "변화 단위": "%p"})
        out[s] = row
    return out


def _rss(url: str, n: int = 8) -> list[dict]:
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        root = ET.fromstring(r.content)
    except Exception as e:
        log.info("RSS 실패 %s: %s", url[:60], e)
        return []
    out = []
    for it in root.iter("item"):
        src = it.find("source")
        out.append({"제목": (it.findtext("title") or "").strip(), "링크": it.findtext("link") or "", "시각": it.findtext("pubDate") or "",
                    "출처": src.text if src is not None else ""})
        if len(out) >= n:
            break
    return out


def gnews(q: str, ko: bool = False, n: int = 8) -> list[dict]:
    loc = "hl=ko&gl=KR&ceid=KR:ko" if ko else "hl=en-US&gl=US&ceid=US:en"
    return _rss(f"https://news.google.com/rss/search?q={quote(q + ' when:2d')}&{loc}", n)


def yahoo_news(sym: str, n: int = 8) -> list[dict]:
    import yfinance as yf
    out = []
    try:
        for x in (yf.Ticker(sym).news or [])[:n]:
            c = x.get("content", x)
            prov = c.get("provider") if isinstance(c.get("provider"), dict) else {}
            url = (c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else c.get("link")
            out.append({"제목": c.get("title"), "요약": (c.get("summary") or "")[:300], "링크": url,
                        "시각": str(c.get("pubDate") or c.get("providerPublishTime") or ""), "출처": prov.get("displayName") or c.get("publisher")})
    except Exception as e:
        log.info("야후 뉴스 실패 %s: %s", sym, e)
    return out


def _industries(tickers: list[str], cache: dict) -> dict:
    import yfinance as yf
    today = datetime.now(KST).strftime("%Y-%m-%d")
    old = (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d")
    for t in tickers:
        c = cache.get(t)
        if c and c.get("at", "") >= old:
            continue
        try:
            info = yf.Ticker(t.replace(".", "-")).info or {}
            cache[t] = {"sector": info.get("sector") or "", "industry": info.get("industry") or info.get("quoteType") or "", "at": today,
                        "pb": info.get("priceToBook"), "pe": info.get("trailingPE"), "div": info.get("dividendYield"), "payout": info.get("payoutRatio"),
                        "de": info.get("debtToEquity")}
        except Exception:
            cache[t] = {"sector": "", "industry": "", "at": today}
    return cache


def sector_of(h: str, cache: dict) -> str | None:
    """보유 종목 하나를 업종 13개 중 하나에 넣어요 (모기지 리츠·BDC를 먼저 봐요)."""
    c = cache.get(h, {})
    txt = (c.get("industry", "") + " " + c.get("sector", "")).lower()
    if not txt.strip():
        return None
    order = ["모기지 리츠", "배당 BDC"] + [n for n in SECTOR_NAMES if n not in ("모기지 리츠", "배당 BDC")]
    words = {x[0]: x[4] for x in SECTOR_DEF}
    for n in order:
        if any(w in txt for w in words[n]):
            return n
    return None


def pinned_from(cfg: dict, holdings: list[str], cache: dict) -> list[str]:
    """맨 위에 올릴 업종: '뉴스 관심 주제'에 적은 것 + 내 보유가 많은 업종. 보여주는 업종 수는 제한하지 않아요."""
    raw = str(cfg.get("뉴스 관심 주제") or "")
    want = [x.strip() for x in re.split(r"[,，/]", raw) if x.strip()]
    picked = [n for w in want for n in SECTOR_NAMES if w in n]
    cnt = {}
    for h in holdings:
        s = sector_of(h, cache)
        if s:
            cnt[s] = cnt.get(s, 0) + 1
    picked += [k for k, _ in sorted(cnt.items(), key=lambda x: -x[1])]
    return list(dict.fromkeys(picked))


def build(store, cfg: dict, holdings: list[str]) -> dict:
    """자료를 모으고(GPT 없이도), GPT가 켜져 있으면 쉬운 리포트를 붙여요."""
    ab = _load_ai(store)
    cache = ab.get("news_ind") or {}
    now = datetime.now(KST)
    mk = market_table()
    seen = set()

    def uniq(items):
        out = []
        for x in items:
            k = (x.get("제목") or "")[:60]
            if k and k not in seen:
                seen.add(k)
                out.append(x)
        return out

    headlines = uniq(yahoo_news("SPY", 10) + gnews("stock market Fed economy", n=10) + gnews("미국 증시", ko=True, n=8))
    cache = _industries(holdings[:20], cache)
    ab["news_ind"] = cache
    pinned = pinned_from(cfg, holdings, cache)
    holds_by = {n: [h for h in holdings if sector_of(h, cache) == n] for n in SECTOR_NAMES}
    sec_data = {}
    for name, etfs, q_en, q_ko, _ in SECTOR_DEF:
        sec_data[name] = {"ETF": etfs[0], "ETF 시세": {e: mk.get(e) for e in etfs if mk.get(e)},
                          "뉴스": [{"제목": x["제목"], "링크": x["링크"], "출처": x.get("출처")} for x in uniq(gnews(q_en, n=5) + gnews(q_ko, ko=True, n=3))][:8],
                          "내 보유 지표": [{"종목": h, **{k: v for k, v in cache.get(h, {}).items() if k != "at"}} for h in holds_by[name]]}

    out = {"at": now.isoformat(timespec="minutes"), "date": now.strftime("%Y-%m-%d"), "pinned": pinned,
           "market": {k: v for k, v in mk.items() if k in MARKET},
           "sectors": sorted([{"t": x[1][0], **(mk.get(x[1][0]) or {}), "이름": x[0]} for x in SECTOR_DEF if mk.get(x[1][0])],
                             key=lambda x: -(x.get("1주") or -99)),
           "sector_holds": {k: v for k, v in holds_by.items() if v},
           "headlines": headlines[:10], "report": None, "all": None}
    ok, why = ai.enabled()
    if not ok:
        out["why"] = "GPT 꺼짐: " + why
    else:
        base = {"기준(한국 시각)": now.strftime("%Y-%m-%d %H:%M"), "시세 표(야후, 종가 기준, 1일·1주·1달 %)": {k: v for k, v in mk.items() if k in MARKET}}
        # 1) 시장 요약
        d1 = dict(base, **{"업종 시세": {x[0]: mk.get(x[1][0]) for x in SECTOR_DEF}, "시장 뉴스": headlines[:24],
                           "보유 목록": [{"종목": h, "업종": cache.get(h, {}).get("industry", "")} for h in holdings[:20]]})
        rep = ai.checked("경제뉴스 리포트", TASK, d1, "big", 5000, 150)
        if rep:
            out["report"] = rep
        else:
            out["why"] = "시장 요약이 검사를 통과하지 못했어요(숫자 확인 실패). 숫자·뉴스 목록만 보여 드려요."
        # 2) 업종 13개 깊게 (5개씩 3번)
        secs = []
        for i in range(0, len(SECTOR_NAMES), 5):
            part = SECTOR_NAMES[i:i + 5]
            res = ai.checked(f"경제뉴스 업종 {i // 5 + 1}", TASK_SEC, dict(base, 업종={n: sec_data[n] for n in part}), "big", 7000, 180)
            got = {x.get("업종"): x for x in (res or {}).get("업종") or [] if isinstance(x, dict)}
            for n in part:
                x = got.get(n)
                if x:
                    x["업종"], x["내 보유"] = n, holds_by[n]
                    secs.append(x)
        # 3) 내 보유 종목 하나하나
        mine = None
        if holdings:
            d3 = dict(base, 종목={h: {"업종": cache.get(h, {}).get("industry", ""), "PER": cache.get(h, {}).get("pe"), "PBR": cache.get(h, {}).get("pb"),
                                     "배당수익률": cache.get(h, {}).get("div"), "부채비율": cache.get(h, {}).get("de"),
                                     "뉴스": [{"제목": x["제목"], "링크": x["링크"]} for x in (yahoo_news(h.replace(".", "-"), 4) or gnews(f"{h} stock", n=4))]} for h in holdings[:20]})
            mine = ai.checked("경제뉴스 내 종목", TASK_MINE, d3, "big", 5000, 150)
        out["all"] = {"업종": secs, "종목": (mine or {}).get("종목") or []}
    hist = [h for h in (ab.get("news_hist") or []) if h.get("date") != out["date"]]
    secs = (out["all"] or {}).get("업종") or []
    if out["report"] or secs:
        hist = ([{"date": out["date"], "summary": (out["report"] or {}).get("5초 요약") or [],
                  "topics": [{"이름": x.get("업종"), "신호등": x.get("신호등"), "5초 답": x.get("5초 답")} for x in secs]}] + hist)[:30]
    ab["news"], ab["news_hist"] = out, hist
    store.put_blob("ai", json.dumps(ab, ensure_ascii=False, default=str))
    _to_rag(store, out)
    return out


def _load_ai(store) -> dict:
    try:
        return json.loads(store.get_blob("ai") or "{}")
    except Exception:
        return {}


def _to_rag(store, out: dict):
    rep, al = out.get("report") or {}, out.get("all") or {}
    if not rep and not al:
        return
    try:
        import rag
        docs = []
        if rep:
            docs.append({"종목": "공통", "날짜": out["date"], "종류": "시장 뉴스", "제목": "경제뉴스 5초 요약 " + out["date"], "출처": "news.py",
                         "내용": " / ".join(rep.get("5초 요약") or []) + " / " + " / ".join(f"{x.get('제목')}: {x.get('한 줄')}" for x in rep.get("트렌드") or [])})
        for x in al.get("업종") or []:
            docs.append({"종목": "공통", "날짜": out["date"], "종류": "시장 뉴스", "제목": f"{x.get('업종')} 업종 {out['date']}", "출처": "news.py",
                         "내용": f"{x.get('신호등')} · {x.get('5초 답')} · 좋은 점 {x.get('좋은 점')} · 조심할 점 {x.get('조심할 점')} · 팔아야 하는 신호 {x.get('팔아야 하는 신호')}"})
        for x in al.get("종목") or []:
            docs.append({"종목": x.get("종목", ""), "날짜": out["date"], "종류": "시장 뉴스", "제목": f"{x.get('종목')} 뉴스 의견 {out['date']}", "출처": "news.py",
                         "내용": f"{x.get('신호등')} · {x.get('구분')} · {x.get('한 줄')} · 확인할 것 {x.get('확인할 것')}"})
        rag.add(store, docs)
    except Exception as e:
        log.info("뉴스 RAG 저장 실패: %s", e)


def slack_text(out: dict) -> str:
    rep, al = out.get("report") or {}, out.get("all") or {}
    if not rep and not al:
        return ""
    dot = {"초록": "🟢", "노랑": "🟡", "빨강": "🔴"}
    lines = []
    if rep:
        w = rep.get("시장 날씨") or {}
        lines += [f"*오늘 시장 날씨: {w.get('날씨', '')}* — {w.get('한 줄', '')}", ""] + [f"• {x}" for x in rep.get("5초 요약") or []]
    L = al.get("업종") or []
    if L:
        c = {k: [x["업종"] for x in L if x.get("신호등") == k] for k in dot}
        lines.append(f"\n*업종 {len(L)}개*  🟢{len(c['초록'])} 🟡{len(c['노랑'])} 🔴{len(c['빨강'])}")
        lines.append("🟢 좋은 쪽: " + (", ".join(c["초록"]) or "없음"))
        lines.append("🔴 조심: " + (", ".join(c["빨강"]) or "없음"))
    if al.get("종목"):
        lines.append("내 종목: " + " · ".join(f"{dot.get(x.get('신호등'), '⚪')}{x.get('종목')}" for x in al["종목"]))
    lines.append("\n앱 '뉴스' 탭에서 업종 13개·내 종목 하나하나·예시·시나리오까지 볼 수 있어요. (투자 권유 아님)")
    return "\n".join(lines)


if __name__ == "__main__":  # python news.py [--send] — 지금 한 번 만들기 (수동 실행·점검용)
    import sys

    import appdata
    import config
    import notify
    from sheets import Store
    logging.basicConfig(level=logging.INFO)
    st = Store()
    cfg, _ = config.merge_settings(st.settings())
    ai.init(st, cfg)
    try:
        app = json.loads(st.get_blob("daily") or "{}")
    except Exception:
        app = {}
    holds = [h["t"] for h in app.get("holdings", [])]
    res = build(st, cfg, holds)
    ai.flush()
    rep, al = res.get("report") or {}, res.get("all") or {}
    print("시세", len(res.get("market") or {}), "· 헤드라인", len(res.get("headlines") or []), "· 요약", "있음" if rep else "없음 (" + str(res.get("why")) + ")")
    for x in rep.get("5초 요약") or []:
        print(" ", x)
    print("업종", len(al.get("업종") or []), "/", len(SECTOR_NAMES), "· 종목", len(al.get("종목") or []), "/", len(holds), "· 맨 위 고정", res.get("pinned"))
    for x in al.get("업종") or []:
        print(" ", x.get("신호등"), x.get("업종"), x.get("5초 답"))
    if "--send" in sys.argv and (rep or al.get("업종")):
        notify.send_slack("오늘의 경제뉴스 5초 요약", [{"type": "header", "text": {"type": "plain_text", "text": "오늘의 경제뉴스 5초 요약"}},
                                                {"type": "section", "text": {"type": "mrkdwn", "text": slack_text(res)[:2900]}}])
        appdata.add_alert(st, "news", "오늘의 경제뉴스", " / ".join(rep.get("5초 요약") or [])[:200], res["at"], "info")
    sys.exit(0)
