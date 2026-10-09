"""경제뉴스 → 미국주식 트렌드 리포트 (초등학생도 5초에 이해하게).

매일 아침 리포트 끝에 한 번 돌아요 (GPT가 꺼져 있으면 숫자·뉴스 목록만 저장).
자료(무료): 야후 시세(지수·금리·달러·유가·업종 ETF), 야후 뉴스, 구글 뉴스 RSS(영어·한국어).
결과는 '앱 데이터'의 ai 묶음 안 news 로 저장 → 앱 홈 '오늘의 경제뉴스' 카드와 뉴스 화면.

GPT 지시에는 사용자가 공유한 프롬프트 카드(경제정리노트 15가지, 클로드 금융 6가지)를 반영했어요.
  - 뉴스 영향 분석: 호재·악재·단순 소음 구분 (15가지 12번)
  - 투자 리스크 점검·시나리오 3가지(낙관·기준·비관) (7·8번)
  - 재무 위험 신호·밸류에이션(PER·PBR) (3·5번), 매도 기준(14번)
  - '기업명 + 지표 + 기간'을 구체적으로 (클로드 가이드 핵심) → '더 물어보기' 질문
  - TradingAgents(멀티 에이전트) 구조 중 '강세·약세 토론 → 위험관리 3관점(공격·중립·보수)'을 관심 주제에 한 번의 호출로 흉내 내요.
    (실제 주문을 내는 부분은 쓰지 않아요)
관심 주제는 구글 시트 '설정' 탭 '뉴스 관심 주제'(쉼표로 구분, 기본: 헬스케어, 모기지 리츠).
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
SECTORS = {"XLK": "기술", "XLV": "헬스케어", "XLF": "금융", "XLE": "에너지", "XLY": "쓰고 싶은 소비(자동차·쇼핑)", "XLP": "꼭 쓰는 소비(식품·생필품)",
           "XLI": "산업재", "XLU": "전기·가스(유틸리티)", "XLRE": "부동산 리츠", "XLC": "통신·미디어", "XLB": "소재", "REM": "모기지 리츠"}
# 관심 주제: ETF · 뉴스 검색어 · 보유 종목을 고를 업종 단어
TOPICS = {
    "헬스케어": {"etf": ["XLV", "IBB"], "q_en": "healthcare stocks", "q_ko": "미국 헬스케어주", "ind": ["health", "drug", "medical", "biotech", "pharma", "diagnostic"]},
    "모기지 리츠": {"etf": ["REM", "MORT"], "q_en": "mortgage REIT", "q_ko": "모기지 리츠", "ind": ["reit - mortgage", "mortgage"]},
    "기술": {"etf": ["XLK", "SMH"], "q_en": "tech stocks", "q_ko": "미국 기술주", "ind": ["software", "semiconductor", "technology"]},
    "에너지": {"etf": ["XLE"], "q_en": "energy stocks oil", "q_ko": "미국 에너지주", "ind": ["oil", "gas", "energy"]},
    "금융": {"etf": ["XLF", "KBE"], "q_en": "bank stocks", "q_ko": "미국 은행주", "ind": ["bank", "capital markets", "insurance", "credit"]},
    "부동산 리츠": {"etf": ["XLRE", "VNQ"], "q_en": "REIT stocks", "q_ko": "미국 리츠", "ind": ["reit"]},
    "배당 BDC": {"etf": ["BIZD"], "q_en": "BDC business development company", "q_ko": "BDC 배당주", "ind": ["asset management", "credit services"]},
}

TASK = """목표: 경제뉴스를 거의 안 보는 초보자에게 오늘 미국 주식 흐름을 '초등학생도 5초에 이해'하게 알려줘.
규칙:
- 문장은 짧게(한 줄 40자 안팎). 어려운 말은 쓰지 말고, 꼭 써야 하면 괄호로 풀어.
- 모든 트렌드에 생활 속 '예시'(가게·용돈·장보기·학교 같은 비유)를 하나씩 붙여.
- 숫자는 '자료'의 시세 표에 있는 것만. 뉴스 내용은 자료의 제목·요약에 있는 것만.
- 뉴스마다 호재(좋은 소식)·악재(나쁜 소식)·소음(주가에 오래 영향 없을 소식)으로 나눠 (뉴스 영향 분석).
- 관심 주제는 '사도 된다/안 된다'로 답하지 말고, 지금 신호를 신호등(초록·노랑·빨강)과 '확인할 것'으로 보여줘.
  신호등 뜻: 초록=뉴스·흐름이 대체로 좋음, 노랑=좋고 나쁜 게 섞임, 빨강=조심할 신호가 더 많음.
- 관심 주제마다 리스크 점검, 시나리오 3가지(낙관·기준·비관과 각각의 조건), 숫자로 확인할 것(PER·PBR·부채·배당 같은 지표)을 넣어.
- 모기지 리츠는 금리·대출 이자차이·빚(레버리지)·배당 삭감·장부가치 대비 가격·조기상환을 꼭 짚고, '팔아야 하는 신호'(매도 기준)도 적어.
- 관심 주제마다 TradingAgents식 '토론'을 해: 강세 연구원(좋게 보는 근거)과 약세 연구원(나쁘게 보는 근거)이 자료로 한 줄씩 주장하고,
  위험관리 3명(공격형·중립형·보수형)이 한 줄씩 의견을 낸 뒤 '정리'에서 어느 쪽 근거가 더 많은지만 말해 (사라·팔라 결론 금지).
- '내 보유와 닿는 곳'은 자료의 보유 목록에 있는 종목만.
- '더 물어보기'는 '기업명 + 지표 + 기간'이 구체적인 질문 3개 (예: "NLY의 최근 4개 분기 주당 장부가치와 배당 변화를 정리해줘").
출력 JSON:
{"기준일":"YYYY-MM-DD","5초 요약":["이모지+한 줄","",""],
 "시장 날씨":{"날씨":"맑음|구름 조금|흐림|비|폭풍","한 줄":"","예시":""},
 "숫자 3개":[{"이름":"","값":"자료 숫자","쉬운 뜻":""}],
 "트렌드":[{"제목":"","한 줄":"","예시":"","구분":"호재|악재|소음","왜 중요":"","관련 업종":"","출처":[{"제목":"","링크":""}]}],
 "업종 날씨":[{"업종":"","1주":"자료 숫자 %","한 줄":""}],
 "관심 주제":[{"이름":"","신호등":"초록|노랑|빨강","5초 답":"","좋은 점":[""],"조심할 점":[""],"예시":"",
   "시나리오":{"낙관":"","기준":"","비관":""},"확인할 것":[""],"팔아야 하는 신호":[""],"내 보유와 닿는 곳":"",
   "토론":{"강세":"","약세":"","공격형":"","중립형":"","보수형":"","정리":""},"출처":[{"제목":"","링크":""}]}],
 "내 보유와 닿는 소식":[{"종목":"","한 줄":"","구분":"호재|악재|소음"}],
 "오늘의 단어":[{"말":"","쉬운 뜻":"","예시":""}],
 "더 물어보기":["","",""]}
- 트렌드 3~5개, 업종 날씨는 가장 많이 오른 2개·내린 2개, 오늘의 단어 2~3개."""


def _pct(a, b):
    try:
        return round((float(a) / float(b) - 1) * 100, 2)
    except Exception:
        return None


def market_table() -> dict:
    import yfinance as yf
    syms = list(MARKET) + list(SECTORS) + sorted({e for t in TOPICS.values() for e in t["etf"]} - set(SECTORS))
    out = {}
    try:
        df = yf.download(syms, period="3mo", interval="1d", progress=False, auto_adjust=True, threads=True)["Close"]
    except Exception as e:
        log.warning("시세 실패: %s", e)
        return out
    for s in syms:
        if s not in df:
            continue
        c = df[s].dropna()
        if len(c) < 6:
            continue
        last = float(c.iloc[-1])
        row = {"이름": MARKET.get(s) or SECTORS.get(s) or s, "날짜": str(c.index[-1])[:10], "값": round(last, 2),
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
        title = (it.findtext("title") or "").strip()
        src = it.find("source")
        out.append({"제목": title, "링크": it.findtext("link") or "", "시각": it.findtext("pubDate") or "",
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
    for t in tickers:
        c = cache.get(t)
        if c and c.get("at", "") >= (datetime.now(KST) - timedelta(days=30)).strftime("%Y-%m-%d"):
            continue
        try:
            info = yf.Ticker(t.replace(".", "-")).info or {}
            cache[t] = {"sector": info.get("sector") or "", "industry": info.get("industry") or info.get("quoteType") or "", "at": today,
                        "pb": info.get("priceToBook"), "pe": info.get("trailingPE"), "div": info.get("dividendYield"), "payout": info.get("payoutRatio"),
                        "de": info.get("debtToEquity")}
        except Exception:
            cache[t] = {"sector": "", "industry": "", "at": today}
    return cache


def topics_from(cfg: dict) -> list[str]:
    raw = str(cfg.get("뉴스 관심 주제") or "헬스케어, 모기지 리츠")
    return [x.strip() for x in re.split(r"[,，/]", raw) if x.strip() in TOPICS][:4] or ["헬스케어", "모기지 리츠"]


def build(store, cfg: dict, holdings: list[str]) -> dict:
    """자료를 모으고(GPT 없이도), GPT가 켜져 있으면 쉬운 리포트를 붙여요."""
    ab = _load_ai(store)
    cache = ab.get("news_ind") or {}
    now = datetime.now(KST)
    topics = topics_from(cfg)
    mk = market_table()
    data = {"기준(한국 시각)": now.strftime("%Y-%m-%d %H:%M"), "시세 표(야후, 종가 기준, 1일·1주·1달 %)": mk, "시장 뉴스": [], "관심 주제": {}, "보유 목록": []}
    seen = set()

    def add(lst, items):
        for x in items:
            k = (x.get("제목") or "")[:60]
            if k and k not in seen:
                seen.add(k)
                lst.append(x)

    add(data["시장 뉴스"], yahoo_news("SPY", 10))
    add(data["시장 뉴스"], gnews("stock market Fed economy", n=10))
    add(data["시장 뉴스"], gnews("미국 증시", ko=True, n=8))
    cache = _industries(holdings[:20], cache)
    for name in topics:
        t = TOPICS[name]
        lst = []
        for e in t["etf"][:1]:
            add(lst, yahoo_news(e, 6))
        add(lst, gnews(t["q_en"], n=6))
        add(lst, gnews(t["q_ko"], ko=True, n=5))
        mine = [h for h in holdings if any(w in (cache.get(h, {}).get("industry", "") + " " + cache.get(h, {}).get("sector", "")).lower() for w in t["ind"])]
        data["관심 주제"][name] = {"ETF 시세": {e: mk.get(e) for e in t["etf"] if mk.get(e)}, "뉴스": lst[:14],
                                 "내 보유 중 이 주제": [{"종목": h, **{k: v for k, v in cache.get(h, {}).items() if k != "at"}} for h in mine]}
    data["보유 목록"] = [{"종목": h, "업종": cache.get(h, {}).get("industry", "")} for h in holdings[:20]]
    ab["news_ind"] = cache

    out = {"at": now.isoformat(timespec="minutes"), "date": now.strftime("%Y-%m-%d"), "topics": topics,
           "market": {k: v for k, v in mk.items() if k in MARKET},
           "sectors": sorted([{"t": k, **v} for k, v in mk.items() if k in SECTORS], key=lambda x: -(x.get("1주") or -99)),
           "headlines": data["시장 뉴스"][:10], "report": None}
    ok, why = ai.enabled()
    if ok:
        rep = ai.checked("경제뉴스 리포트", TASK, data, "big", 6000)
        if rep:
            out["report"] = rep
        else:
            out["why"] = "GPT 답이 검사를 통과하지 못했어요(숫자 확인 실패). 숫자·뉴스 목록만 보여 드려요."
    else:
        out["why"] = "GPT 꺼짐: " + why
    hist = [h for h in (ab.get("news_hist") or []) if h.get("date") != out["date"]]
    if out["report"]:
        hist = ([{"date": out["date"], "summary": out["report"].get("5초 요약") or [],
                  "topics": [{"이름": x.get("이름"), "신호등": x.get("신호등"), "5초 답": x.get("5초 답")} for x in out["report"].get("관심 주제") or []]}] + hist)[:30]
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
    rep = out.get("report")
    if not rep:
        return
    try:
        import rag
        docs = [{"종목": "공통", "날짜": out["date"], "종류": "시장 뉴스", "제목": "경제뉴스 5초 요약 " + out["date"],
                 "출처": "news.py", "내용": " / ".join(rep.get("5초 요약") or []) + " / " + " / ".join(f"{x.get('제목')}: {x.get('한 줄')}" for x in rep.get("트렌드") or [])}]
        for x in rep.get("관심 주제") or []:
            docs.append({"종목": "공통", "날짜": out["date"], "종류": "시장 뉴스", "제목": f"{x.get('이름')} 주제 {out['date']}", "출처": "news.py",
                         "내용": f"{x.get('신호등')} · {x.get('5초 답')} · 좋은 점 {x.get('좋은 점')} · 조심할 점 {x.get('조심할 점')} · 팔아야 하는 신호 {x.get('팔아야 하는 신호')}"})
        rag.add(store, docs)
    except Exception as e:
        log.info("뉴스 RAG 저장 실패: %s", e)


def slack_text(out: dict) -> str:
    rep = out.get("report") or {}
    if not rep:
        return ""
    w = rep.get("시장 날씨") or {}
    lines = [f"*오늘 시장 날씨: {w.get('날씨', '')}* — {w.get('한 줄', '')}", ""] + [f"• {x}" for x in rep.get("5초 요약") or []]
    dot = {"초록": "🟢", "노랑": "🟡", "빨강": "🔴"}
    for x in rep.get("관심 주제") or []:
        lines.append(f"{dot.get(x.get('신호등'), '⚪')} *{x.get('이름')}*: {x.get('5초 답', '')}")
    lines.append("\n앱 홈 → '오늘의 경제뉴스'에서 예시·시나리오까지 볼 수 있어요. (투자 권유 아님)")
    return "\n".join(lines)


if __name__ == "__main__":  # python news.py — 지금 한 번 만들기 (수동 실행·점검용)
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
    rep = res.get("report") or {}
    print("시세", len(res.get("market") or {}), "· 헤드라인", len(res.get("headlines") or []), "· 리포트", "있음" if rep else "없음 (" + str(res.get("why")) + ")")
    for x in rep.get("5초 요약") or []:
        print(" ", x)
    for x in rep.get("관심 주제") or []:
        print(" ", x.get("이름"), x.get("신호등"), x.get("5초 답"))
    if "--send" in sys.argv and rep:
        notify.send_slack("오늘의 경제뉴스 5초 요약", [{"type": "header", "text": {"type": "plain_text", "text": "오늘의 경제뉴스 5초 요약"}},
                                                {"type": "section", "text": {"type": "mrkdwn", "text": slack_text(res)[:2900]}}])
        appdata.add_alert(st, "news", "오늘의 경제뉴스", " / ".join(rep.get("5초 요약") or [])[:200], res["at"], "info")
    sys.exit(0)
