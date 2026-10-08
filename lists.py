"""F-07 가격대·예산 분류 · F-22 매일 바뀌는 표시."""
from __future__ import annotations

import pandas as pd

from config import budgets, price_bands


def yesterday_state(today_df_prev: pd.DataFrame) -> dict[str, dict]:
    """어제 '오늘 리스트'에서 매수 후보만 {종목: {연속 일수, 날짜}}."""
    out = {}
    if today_df_prev is None or today_df_prev.empty:
        return out
    buys = today_df_prev[today_df_prev["판정"] == "매수 후보"]
    for _, r in buys.iterrows():
        try:
            streak = int(float(r.get("연속 일수") or 1))
        except ValueError:
            streak = 1
        out[r["종목"]] = {"streak": streak, "date": r.get("날짜", ""), "band": r.get("가격대", "")}
    return out


def build_bands(cands: list[dict], cfg: dict, prev: dict[str, dict], today_iso: str) -> tuple[list[dict], int]:
    """cands: 매수 판정 종목들 (총점 순 정렬 전). 반환: (가격대 목록, 신규 수)."""
    n = int(cfg["보여줄 개수"])
    bands = []
    new_count = 0
    shown = set()
    for lo, hi, name in price_bands(cfg):
        inside = sorted([c for c in cands if lo <= c["price"] < hi], key=lambda c: -c["total"])
        picks = inside[:n]
        for i, p in enumerate(picks, 1):
            p["rank"] = i
            p["band"] = name
            if p["ticker"] in prev and prev[p["ticker"]]["date"] != today_iso:
                p["streak"] = prev[p["ticker"]]["streak"] + 1
                p["tags"].insert(0, f"연속 {p['streak']}일")
            else:
                p["streak"] = 1
                p["tags"].insert(0, "신규")
                new_count += 1
            shown.add(p["ticker"])
        bands.append({"name": name, "lo": lo, "hi": hi, "count": len(inside), "picks": picks, "dropped": []})
    return bands, new_count


def dropped_reasons(bands: list[dict], prev: dict[str, dict], why: dict[str, str]):
    """어제 있었는데 오늘 빠진 종목 + 이유 한 줄."""
    today = {p["ticker"] for b in bands for p in b["picks"] + b.get("etf_picks", [])}
    for t, info in prev.items():
        if t in today:
            continue
        reason = why.get(t, "순위 밖으로 밀림")
        for b in bands:
            if b["name"] == info.get("band"):
                b["dropped"].append(f"{t} · {reason}")
                break


def budget_table(cands: list[dict], cfg: dict) -> dict[int, list[dict]]:
    out = {}
    for b in budgets(cfg):
        ok = sorted([c for c in cands if c["price"] <= b], key=lambda c: -c["total"])[: int(cfg["보여줄 개수"])]
        out[b] = [{"ticker": c["ticker"], "price": c["price"], "shares": int(b // c["price"]),
                   "left": round(b - int(b // c["price"]) * c["price"], 2)} for c in ok]
    return out
