"""AI 투자 에이전트 팀 — 종목 하나를 6개 역할 관점으로 한눈에(표시·종합용).

커리큘럼 STEP 03 '멀티에이전트'를 이 앱에 맞춰 옮긴 거예요. 새로 분석하지 않고,
이미 만들어진 신호(재무 요약·적정가·월가5인·시장국면·점수)를 역할별로 '모아 보여줘요'.
  - 펀더멘탈: 재무 건전성(F스코어·Z·버핏) + 적정가(안전마진)
  - 기술적:   추세 점수·셋업 태그
  - 퀀트:     피오트로스키 F스코어 · 알트만 Z
  - 마켓:     시장 국면(상승/횡보/하락)
  - 리스크:   부도위험(Z)·고평가·변동 신호
  - 포트폴리오 매니저: 위 다섯을 묶은 한 줄 종합
매수·매도 '판단'은 기존대로 setups/위원회/적정가가 해요. 이 파일은 '보여주기·종합'만 — 관찰·참고용.
"""
from __future__ import annotations

VERSION = "agents-1"
ROLES = ("펀더멘탈", "기술적", "퀀트", "마켓", "리스크", "포트폴리오 매니저")
# stance: 긍정 / 중립 / 주의  (화면 색: 긍정=파랑, 주의=빨강, 중립=회색 — 한국식)
_RANK = {"긍정": 1, "중립": 0, "주의": -1}


def _role(name, stance, line):
    return {"role": name, "stance": stance if stance in _RANK else "중립", "line": line}


def fundamental(fin: dict | None, val: dict | None) -> dict:
    fin, val = fin or {}, val or {}
    v = fin.get("verdict")              # good / warn / bad / info / none
    vv = val.get("verdict")            # 저평가 / 적정 / 고평가 / 확인 못 함
    bits = []
    if fin.get("verdict_text"):
        bits.append(fin["verdict_text"])
    if val.get("fair_mid") is not None and val.get("margin_pct") is not None:
        bits.append(f"적정가 ~${val['fair_mid']} (안전마진 {val['margin_pct']}%)")
    stance = "중립"
    if v == "bad" or vv == "고평가":
        stance = "주의"
    elif v == "good" and vv in ("저평가", "적정"):
        stance = "긍정"
    elif vv == "저평가":
        stance = "긍정"
    return _role("펀더멘탈", stance, " · ".join(bits) or "재무 자료 부족")


def technical(pick: dict | None) -> dict:
    pick = pick or {}
    cats = pick.get("cats") or {}
    trend = cats.get("추세") if isinstance(cats, dict) else None
    tags = pick.get("tags") or []
    stance = "중립"
    if trend is not None:
        stance = "긍정" if trend >= 7 else "주의" if trend <= 3 else "중립"
    line = (f"추세 점수 {trend}" if trend is not None else "추세 점수 없음")
    if tags:
        line += " · " + ", ".join(map(str, tags[:3]))
    return _role("기술적", stance, line)


def quant(fin: dict | None) -> dict:
    fin = fin or {}
    fs, fmax = fin.get("fscore"), fin.get("fscore_max")
    z, zone = fin.get("z"), fin.get("z_zone")
    bits = []
    if fs is not None and fmax:
        bits.append(f"F스코어 {fs}/{fmax}")
    if z is not None:
        bits.append(f"Z {z}")
    stance = "중립"
    if zone == "distress" or (fs is not None and fmax and fs <= fmax * 0.4):
        stance = "주의"
    elif (fs is not None and fmax and fs >= fmax * 0.7) and zone != "distress":
        stance = "긍정"
    return _role("퀀트", stance, " · ".join(bits) or "퀀트 지표 없음")


def market_view(market: dict | None) -> dict:
    market = market or {}
    regime = market.get("regime")
    label = market.get("label") or regime or "확인 못 함"
    stance = {"bull": "긍정", "bear": "주의"}.get(regime, "중립")
    return _role("마켓", stance, f"시장 국면: {label}")


def risk(fin: dict | None, val: dict | None, port: dict | None) -> dict:
    fin, val = fin or {}, val or {}
    bits, stance = [], "중립"
    if fin.get("z_zone") == "distress":
        stance = "주의"; bits.append("부도위험 구간(Z 낮음)")
    if val.get("verdict") == "고평가":
        stance = "주의"; bits.append("적정가 대비 고평가")
    if (fin.get("debt_eq") if isinstance(fin.get("debt_eq"), (int, float)) else None):
        bits.append(f"부채/자본 {fin['debt_eq']:.2f}")
    if not bits:
        bits.append("특이 위험 신호 없음"); stance = "긍정" if fin.get("verdict") == "good" else "중립"
    return _role("리스크", stance, " · ".join(bits))


def portfolio_manager(roles: list[dict]) -> dict:
    """다섯 역할을 묶은 한 줄 종합. 다수결 + '주의가 하나라도 강하면 보수적으로'."""
    scores = [_RANK[r["stance"]] for r in roles if r["role"] != "포트폴리오 매니저"]
    cautions = [r["role"] for r in roles if r["stance"] == "주의"]
    total = sum(scores)
    if "펀더멘탈" in cautions or "리스크" in cautions:
        stance, line = "주의", "재무·리스크에 주의 신호 — 보수적으로 접근"
    elif total >= 2:
        stance, line = "긍정", "여러 관점이 우호적 — 단, 규칙·적정가 통과 시에만"
    elif total <= -2:
        stance, line = "주의", "여러 관점이 부정적"
    else:
        stance, line = "중립", "관점이 엇갈림 — 서두르지 않기"
    if cautions:
        line += f" (주의: {', '.join(cautions)})"
    return _role("포트폴리오 매니저", stance, line)


def team(t: str, *, fin: dict | None = None, val: dict | None = None,
         market: dict | None = None, pick: dict | None = None,
         port: dict | None = None) -> dict:
    """한 종목의 6역할 팀 뷰. 반환: {t, roles:[...6...], summary:{stance,line}}."""
    five = [
        fundamental(fin, val),
        technical(pick),
        quant(fin),
        market_view(market),
        risk(fin, val, port),
    ]
    pm = portfolio_manager(five)
    return {"t": t, "version": VERSION, "roles": five + [pm], "summary": {"stance": pm["stance"], "line": pm["line"]}}


if __name__ == "__main__":
    import json
    print(json.dumps(team(
        "DEMO",
        fin={"verdict": "good", "verdict_text": "재무는 튼튼한 편이에요", "fscore": 7, "fscore_max": 9, "z": 3.1, "z_zone": "safe", "debt_eq": 0.48},
        val={"verdict": "저평가", "fair_mid": 220.0, "margin_pct": 40.0},
        market={"regime": "bull", "label": "상승장"},
        pick={"cats": {"추세": 8}, "tags": ["골든크로스", "신고가"]},
    ), ensure_ascii=False, indent=2))
