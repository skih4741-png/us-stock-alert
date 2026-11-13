"""AI 투자 에이전트 팀 — 종목 하나를 6개 역할 관점으로 한눈에(표시·종합용).

커리큘럼 STEP 03 '멀티에이전트'를 이 앱에 맞춰 옮긴 거예요. 새로 분석하지 않고,
이미 만들어진 신호(재무 요약·적정가·지표/리스크·시장국면·점수)를 역할별로 '모아 보여줘요'.
  - 펀더멘탈: 재무 건전성(F스코어·Z·버핏) + 적정가(안전마진)
  - 기술적:   추세·RSI·MACD·메인 신호
  - 퀀트:     피오트로스키 F스코어 · 알트만 Z
  - 마켓:     시장 국면(상승/횡보/하락)
  - 리스크:   변동성·MDD·부도위험(Z)·고평가
  - 포트폴리오 매니저: 위 다섯을 묶은 한 줄 종합 + 투자 의사결정(비중 확대/유지/축소)
각 역할은 stance(긍정/중립/주의)와 score(0~100, radar용)를 내요.
매수·매도 '판단'은 기존대로 setups/위원회/적정가가 해요. 이 파일은 '보여주기·종합'만 — 관찰·참고용.
"""
from __future__ import annotations

VERSION = "agents-2"
ROLES = ("펀더멘탈", "기술적", "퀀트", "마켓", "리스크", "포트폴리오 매니저")
# stance: 긍정 / 중립 / 주의  (화면 색: 긍정=파랑, 주의=빨강, 중립=회색 — 한국식)
_RANK = {"긍정": 1, "중립": 0, "주의": -1}
_BASE = {"긍정": 75, "중립": 50, "주의": 28}


def _role(name, stance, line, score=None):
    stance = stance if stance in _RANK else "중립"
    return {"role": name, "stance": stance, "line": line,
            "score": int(score) if score is not None else _BASE[stance]}


def fundamental(fin: dict | None, val: dict | None) -> dict:
    fin, val = fin or {}, val or {}
    v, vv = fin.get("verdict"), val.get("verdict")
    bits = []
    if fin.get("verdict_text"):
        bits.append(fin["verdict_text"])
    if val.get("fair_mid") is not None and val.get("margin_pct") is not None:
        bits.append(f"적정가 ~${val['fair_mid']} (안전마진 {val['margin_pct']}%)")
    stance = "중립"
    if v == "bad" or vv == "고평가":
        stance = "주의"
    elif (v == "good" and vv in ("저평가", "적정")) or vv == "저평가":
        stance = "긍정"
    # 점수: 재무(good/warn/bad) + 안전마진 가미
    score = {"good": 72, "info": 55, "warn": 42, "bad": 25, "none": 50}.get(v, 50)
    mp = val.get("margin_pct")
    if isinstance(mp, (int, float)):
        score = max(0, min(100, score + max(-20, min(20, mp / 2))))
    return _role("펀더멘탈", stance, " · ".join(bits) or "재무 자료 부족", score)


def technical(pick: dict | None, ind: dict | None) -> dict:
    pick, ind = pick or {}, ind or {}
    sig = ind.get("main_signal")
    rsi = ind.get("rsi14")
    bits = []
    if sig:
        bits.append(f"메인 신호 {sig}")
    if rsi is not None:
        bits.append(f"RSI {rsi:g}")
    if ind.get("macd") is not None and ind.get("macd_signal") is not None:
        bits.append("MACD " + ("상향" if ind["macd"] > ind["macd_signal"] else "하향"))
    if not bits:   # 지표 없으면 추세 점수로 폴백
        cats = pick.get("cats") or {}
        trend = cats.get("추세") if isinstance(cats, dict) else None
        if trend is not None:
            bits.append(f"추세 점수 {trend}")
    stance = {"매수": "긍정", "매도": "주의"}.get(sig, "중립")
    score = {"매수": 74, "매도": 30}.get(sig, 50)
    if rsi is not None and rsi >= 75:
        stance, score = "중립", min(score, 48)   # 과매수 경계
    return _role("기술적", stance, " · ".join(bits) or "지표 없음", score)


def quant(fin: dict | None) -> dict:
    fin = fin or {}
    fs, fmax = fin.get("fscore"), fin.get("fscore_max")
    z, zone = fin.get("z"), fin.get("z_zone")
    bits = []
    if fs is not None and fmax:
        bits.append(f"F스코어 {fs}/{fmax}")
    if z is not None:
        bits.append(f"Z {z}")
    stance, score = "중립", 50
    if zone == "distress" or (fs is not None and fmax and fs <= fmax * 0.4):
        stance, score = "주의", 30
    elif (fs is not None and fmax and fs >= fmax * 0.7) and zone != "distress":
        stance, score = "긍정", 72
    if fs is not None and fmax:
        score = int(max(0, min(100, fs / fmax * 100)))
    return _role("퀀트", stance, " · ".join(bits) or "퀀트 지표 없음", score)


def market_view(market: dict | None) -> dict:
    market = market or {}
    regime = market.get("regime")
    label = market.get("label") or regime or "확인 못 함"
    stance = {"bull": "긍정", "bear": "주의"}.get(regime, "중립")
    return _role("마켓", stance, f"시장 국면: {label}")


def risk(fin: dict | None, val: dict | None, ind: dict | None) -> dict:
    fin, val, ind = fin or {}, val or {}, ind or {}
    rm = ind.get("risk") or {}
    bits, stance, score = [], "중립", 55
    if rm.get("vol30") is not None:
        bits.append(f"변동성 {rm['vol30']:g}%")
    if rm.get("mdd") is not None:
        bits.append(f"MDD {rm['mdd']:g}%")
    if rm.get("beta") is not None:
        bits.append(f"베타 {rm['beta']:g}")
    bad = []
    if fin.get("z_zone") == "distress":
        bad.append("부도위험 구간")
    if val.get("verdict") == "고평가":
        bad.append("고평가")
    if rm.get("vol30") is not None and rm["vol30"] >= 45:
        bad.append("고변동성")
    if bad:
        stance, score = "주의", 30
        bits = bad + bits
    elif fin.get("verdict") == "good" and (rm.get("vol30") or 99) < 30:
        stance, score = "긍정", 70
    return _role("리스크", stance, " · ".join(bits) or "특이 위험 신호 없음", score)


def portfolio_manager(roles: list[dict]) -> dict:
    """다섯 역할을 묶은 종합 + 투자 의사결정. '주의가 강하면 보수적으로'."""
    five = [r for r in roles if r["role"] != "포트폴리오 매니저"]
    scores = [_RANK[r["stance"]] for r in five]
    cautions = [r["role"] for r in five if r["stance"] == "주의"]
    goods = [r["role"] for r in five if r["stance"] == "긍정"]
    total = sum(scores)
    if "펀더멘탈" in cautions or "리스크" in cautions:
        stance, decision = "주의", "축소"
        line = "재무·리스크 주의 — 보수적으로 접근"
    elif total >= 2:
        stance, decision = "긍정", "비중 확대"
        line = "여러 관점 우호적 — 단, 규칙·적정가 통과 시에만"
    elif total <= -2:
        stance, decision = "주의", "축소"
        line = "여러 관점이 부정적"
    else:
        stance, decision = "중립", "유지"
        line = "관점이 엇갈림 — 서두르지 않기"
    confidence = round(min(5.0, 2.5 + abs(total) * 0.6), 1)   # 역할 합의 강도(0~5)
    avg = int(sum(r["score"] for r in five) / len(five)) if five else 50
    if cautions:
        line += f" (주의: {', '.join(cautions)})"
    r = _role("포트폴리오 매니저", stance, line, avg)
    r["decision"] = decision
    r["confidence"] = confidence
    return r


def team(t: str, *, fin: dict | None = None, val: dict | None = None,
         market: dict | None = None, pick: dict | None = None,
         ind: dict | None = None) -> dict:
    """한 종목의 6역할 팀 뷰. 반환: {t, roles:[...6...], summary:{stance,line,decision,confidence,scores}}."""
    five = [
        fundamental(fin, val),
        technical(pick, ind),
        quant(fin),
        market_view(market),
        risk(fin, val, ind),
    ]
    pm = portfolio_manager(five)
    scores = {r["role"]: r["score"] for r in five}
    return {"t": t, "version": VERSION, "roles": five + [pm],
            "summary": {"stance": pm["stance"], "line": pm["line"],
                        "decision": pm["decision"], "confidence": pm["confidence"],
                        "scores": scores}}


if __name__ == "__main__":
    import json
    print(json.dumps(team(
        "DEMO",
        fin={"verdict": "good", "verdict_text": "재무는 튼튼한 편이에요", "fscore": 7, "fscore_max": 9, "z": 3.1, "z_zone": "safe"},
        val={"verdict": "저평가", "fair_mid": 220.0, "margin_pct": 40.0},
        market={"regime": "bull", "label": "상승장"},
        ind={"main_signal": "매수", "rsi14": 61.2, "macd": 1.6, "macd_signal": 1.2,
             "risk": {"vol30": 24.0, "mdd": -12.3, "beta": 1.1}},
    ), ensure_ascii=False, indent=2))
