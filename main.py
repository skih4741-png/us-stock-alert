"""미국주식 매수·매도 알림 — 전체 순서를 차례로 실행해요.

사용법
  python main.py daily              아침 리포트 (평일 한국 07:00)
  python main.py premarket          장 시작 전 점검 (슬랙)
  python main.py intraday           장중 감시 (슬랙)
  python main.py weekly             주간 요약 + 신호 성적 갱신 (메일)
  python main.py fail "<메시지>"     실패 알림
옵션
  --limit 300   전체 대신 거래대금 상위 300개만 (시험용)
  --dry         보내지 않고 화면에만 출력
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

import appdata
import config
import lists
import market
import notify
import prices
import scoring
import timing
import universe
from explain import explain
from sheets import Store
from terms import REASON_LABEL, REGIME, SELL_ACTION, VERDICT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("main")
STATE = Path(__file__).parent / "data" / "state.json"
import re as _re
FUND_NAME = _re.compile(r"\bETF\b|\bFund\b|Term Trust|Income Trust|Premium Income|Municipal|\bETN\b|Closed[- ]End|Opportunities Trust|Strategies Trust|Equity Trust|Technology Trust|Sciences Trust|Growth Trust", _re.I)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(s: dict):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def label_reasons(keys: list[str]) -> list[str]:
    return [REASON_LABEL.get(k, k) for k in keys]


# ======================================================================
# 아침 리포트
# ======================================================================

def run_daily(limit: int | None, dry: bool) -> dict:
    t0 = time.time()
    now = config.now_kst()
    stage = "시작"
    store = Store()
    cfg, warn = config.merge_settings(store.settings())
    state = load_state()
    holdings = store.holdings()
    try:
        # ---- 시장 국면 ----
        stage = "시장 국면"
        idx = prices.download_history(["SPY", "^VIX"], period="400d", batch=2, pause=0)
        spy, vix = idx.get("SPY"), idx.get("^VIX")
        if spy is None or len(spy) < 200:
            raise RuntimeError("대표 지수(SPY) 가격을 받지 못했어요")
        bar_date = spy.index[-1].strftime("%Y-%m-%d")
        if state.get("last_bar_date") == bar_date and not dry:
            log.info("새 거래일 자료가 없어요(미국 휴장) → 종료")
            store.append("실행 기록", [{"날짜": now.strftime("%Y-%m-%d"), "시각": now.strftime("%H:%M"), "종류": "아침 리포트",
                                      "성공/실패": "건너뜀", "메모": "미국 휴장"}])
            return {"skipped": True}
        mk = market.judge(spy, vix, cfg)
        prev_regime = state.get("regime")
        regime_to_bear = prev_regime not in (None, "bear") and mk["regime"] == "bear"
        spy_ret63 = float(spy["Close"].iloc[-1] / spy["Close"].iloc[-64] - 1)

        # ---- 전체 목록 + 가격 ----
        stage = "종목 목록"
        uni, note = universe.load_universe(cfg)
        if note:
            warn.append(note)
        if limit:
            uni = uni.assign(dv=uni["price"].fillna(0) * uni["volume"].fillna(0)).sort_values("dv", ascending=False).head(limit)
        meta = uni.set_index("yf_ticker")
        hold_t = [h["ticker"].replace(".", "-") for h in holdings]
        stage = "가격 수집"
        tickers = list(dict.fromkeys(list(meta.index) + hold_t))
        hist = prices.download_history(tickers)
        got = len(hist) / max(1, len(tickers))
        if got < 0.5:
            raise RuntimeError(f"가격 자료를 {got:.0%}만 받았어요")
        if got < 0.95:
            warn.append(f"가격 자료를 {got:.0%}만 받았어요(나머지는 오늘 분석에서 빠짐)")

        # ---- 기본 거름망 + 추세 숫자 ----
        stage = "추세 점수"
        tech = {}
        for t, df in hist.items():
            x = scoring.technicals(df, spy_ret63)
            if x is None:
                continue
            tech[t] = x
        before = len(tech)
        base = {t: x for t, x in tech.items()
                if x["close"] >= float(cfg["최소 주가(달러)"]) and x["dollar_vol20"] >= float(cfg["최소 거래대금(달러)"])
                and x["days"] >= float(cfg["최소 상장 기간(일)"])}
        log.info("거름망: %s → %s", before, len(base))
        rs = pd.Series({t: x["ret63"] for t, x in base.items() if x["ret63"] is not None})
        rs_pct = (rs.rank(ascending=False, pct=True)).to_dict()
        market_vol = float(np.median([x["vol60"] for x in base.values()])) if base else 0.3

        # ---- 재무 (추세 상·하위 + 보유) ----
        stage = "재무 점수"
        prelim = {t: scoring._scale(*scoring.score_trend(x, rs_pct.get(t))) for t, x in base.items()}
        fund_cache = prices._load_cache()

        def is_etf(t: str) -> bool:
            """ETF·폐쇄형 펀드·신탁이면 True (재무제표로 평가할 수 없는 종목)."""
            if t in meta.index and not isinstance(meta.loc[t, "is_etf"], pd.Series) and bool(meta.loc[t, "is_etf"]):
                return True
            qt = (fund_cache.get(t) or {}).get("quote_type")
            if qt and qt.upper() in ("ETF", "MUTUALFUND", "CLOSEDENDFUND"):
                return True
            name = str(meta.loc[t, "name"]) if t in meta.index and not isinstance(meta.loc[t, "name"], pd.Series) else ""
            return bool(FUND_NAME.search(name))

        stocks = [t for t in base if not is_etf(t)]
        ranked = sorted(stocks, key=lambda t: -(prelim[t] or 0))
        need_f = list(dict.fromkeys(ranked[:450] + ranked[-120:] + [t for t in hold_t if t in tech]))
        fund = prices.fundamentals(need_f)
        fdf = pd.DataFrame.from_dict(fund, orient="index")
        for col in ("per", "pbr", "fcf_yield", "debt_to_equity"):
            if col in fdf:
                fdf[col] = pd.to_numeric(fdf[col], errors="coerce")

        # ---- 점수 + 판정 ----
        stage = "판정"
        results = {}
        for t, x in list(base.items()) + [(t, tech[t]) for t in hold_t if t in tech and t not in base]:
            f = fund.get(t)
            sector = (f or {}).get("sector") or (meta.loc[t, "sector"] if t in meta.index else None)
            peers = fdf[fdf["sector"] == sector] if (f and "sector" in fdf and sector) else None
            if peers is not None and len(peers) < 8:
                peers = fdf  # 같은 업종이 너무 적으면 전체와 비교
            etf = is_etf(t)
            sc = scoring.combine(x, f, peers, rs_pct.get(t), market_vol, etf)
            v, why = scoring.verdict(x, sc, mk, cfg, etf)
            name = (f or {}).get("long_name") or (f or {}).get("short_name") or (meta.loc[t, "name"] if t in meta.index else t)
            results[t] = {"ticker": t, "name": str(name), "price": x["close"], "total": sc["total"], "cats": sc["cats"],
                          "reasons": label_reasons(sc["reasons"]), "flags": sc["flags"], "verdict": v, "why": why,
                          "tech": x, "etf": etf, "sector": sector}

        # ---- 매수 후보 + 타이밍 ----
        stage = "타이밍"
        today_iso = bar_date
        prev_df = store.read("오늘 리스트")
        prev = lists.yesterday_state(prev_df)
        valid_days = int(cfg["신호 유효 거래일"])
        expired = {t for t, p in prev.items() if p["streak"] >= valid_days}
        buys = []
        for t, r in results.items():
            if t not in base or r["verdict"] != "buy" or t in expired:
                continue
            r["plan"] = timing.buy_plan(r["tech"], mk["rr"], cfg, spy.index[-1].date())
            r["tags"] = list(r["flags"])
            if r["price"] < 5:
                r["tags"].append("출렁임 큼")
            buys.append(r)
        if mk["rest_day"]:
            reference = [b for b in buys if b["total"] >= float(cfg["하락장 참고 기준"])]
            for b in reference:
                b["tags"].append("참고용")
            buys_for_list = []
        else:
            reference = []
            buys_for_list = buys
        # 개별 종목과 ETF·펀드는 따로 순위를 매겨요 (ETF는 재무 점수 없이 추세·안전만으로 점수가 높게 나오기 쉬워서)
        stock_buys = [b for b in buys_for_list if not b["etf"]]
        fund_buys = [b for b in buys_for_list if b["etf"]]
        for b in fund_buys:
            b["tags"].insert(0, "ETF·펀드")
        bands, new_count = lists.build_bands(stock_buys, cfg, prev, today_iso)
        etf_cfg = dict(cfg, **{"보여줄 개수": max(1, int(cfg["ETF 개수"]))})
        etf_bands, etf_new = lists.build_bands(fund_buys if int(cfg["ETF 개수"]) > 0 else [], etf_cfg, prev, today_iso)
        for b, e in zip(bands, etf_bands):
            b["etf_picks"], b["etf_count"] = e["picks"], e["count"]
        new_count += etf_new
        picks = [p for b in bands for p in b["picks"] + b["etf_picks"]]

        # 실적 발표 표시
        stage = "실적 일정"
        ed = prices.earnings_dates([p["ticker"] for p in picks] + hold_t)
        today_d = spy.index[-1].date()
        def days_to(t):
            if t not in ed:
                return None
            return int(np.busday_count(today_d, pd.Timestamp(ed[t]).date()))
        for p in picks:
            d = days_to(p["ticker"])
            if d is not None and 0 <= d <= 10:
                p["tags"].append(f"실적 D-{d}")
                if d <= int(cfg["실적 발표 보류 거래일"]):
                    p["tags"].append("신규 매수 보류")

        # 어제에서 빠진 이유
        why = {}
        for t in prev:
            r = results.get(t)
            if t in expired:
                why[t] = f"신호 만료({valid_days}거래일)"
            elif r is None:
                why[t] = "자료 없음 또는 거래 감소"
            elif r["verdict"] == "surge":
                why[t] = "급등 · 추격 주의"
            elif r["verdict"] != "buy":
                why[t] = r["why"] or f"점수 {r['total']:.0f} (기준 {mk['threshold']:.0f} 미달)"
            else:
                why[t] = "순위 밖으로 밀림"
        lists.dropped_reasons(bands, prev, why)

        # ---- 내 보유 매도 후보 ----
        stage = "보유 종목 점검"
        sells = []
        holdings_view = []
        for h in holdings:
            t = h["ticker"].replace(".", "-")
            if t not in hist:
                warn.append(f"보유 종목 {h['ticker']}의 가격을 못 받았어요")
                holdings_view.append(appdata.holding_view(h, None, [], None))
                continue
            r = results.get(t)
            hits = timing.sell_check(h, hist[t], tech.get(t), r["total"] if r else None, regime_to_bear, days_to(t), cfg)
            lv = timing.levels(h, hist[t], tech.get(t), cfg)
            action = SELL_ACTION[hits[0]["rule"]] if hits else ""
            holdings_view.append(appdata.holding_view(h, lv, hits, r, action))
            if hits:
                top = hits[0]
                sells.append({**top, "ticker": h["ticker"], "action": action,
                              "why": " · ".join(x["why"] for x in hits[:2])})
        tone_rank = {"bad": 0, "warn": 1, "good": 2}
        holdings_view.sort(key=lambda x: (tone_rank.get(x["tone"], 3), x["t"]))

        # ---- AI 설명·경고 ----
        stage = "AI 설명"
        items = []
        for p in picks:
            items.append({"종목코드": p["ticker"], "회사명": p["name"], "구분": "매수 후보", "주가": round(p["price"], 2),
                          "총점": p["total"], "점수": p["cats"], "이유": p["reasons"],
                          "5일 상승률(%)": round((p["tech"]["ret5"] or 0) * 100, 1),
                          "3개월 상승률(%)": round((p["tech"]["ret63"] or 0) * 100, 1),
                          "3개월 대표 지수 상승률(%)": round(spy_ret63 * 100, 1),
                          "거래량 배수": round(p["tech"]["vol_ratio"] or 0, 2),
                          "뉴스": prices.news_headlines(p["ticker"])})
        for s in sells:
            items.append({"종목코드": s["ticker"], "구분": "내 보유 매도 후보", "종가": s["close"], "수익률(%)": s["gain_pct"],
                          "매도 이유": s["why"], "뉴스": prices.news_headlines(s["ticker"].replace(".", "-"))})
        ai = explain(items, cfg)
        for p in picks:
            a = ai.get(p["ticker"], {})
            p["desc"], p["caution"], p["warn"] = a.get("설명", ""), a.get("주의", ""), a.get("경고", "")
            if p["warn"]:
                p["tags"].append("AI 위험 경고")

        # ---- 웹·시트용 피해야 할 종목 / 급등 주의 ----
        extra_rows = []
        for lo, hi, name in config.price_bands(cfg):
            for kind, label in (("avoid", VERDICT["avoid"]), ("surge", "급등 · 추격 주의")):
                group = sorted([r for t, r in results.items() if t in base and r["verdict"] == kind and lo <= r["price"] < hi],
                               key=lambda r: r["total"] if kind == "avoid" else -(r["tech"]["ret5"] or 0))[:3]
                for i, r in enumerate(group, 1):
                    extra_rows.append({"가격대": name, "판정": label, "순위": i, "종목": r["ticker"], "회사명": r["name"],
                                       "주가": f"{r['price']:.2f}", "총점": f"{r['total']:.0f}",
                                       "이유": f"5일 {((r['tech']['ret5'] or 0) * 100):+.0f}%" if kind == "surge" else "하락 추세"})

        # ---- 기록 ----
        stage = "기록"
        rows = []
        for p in picks:
            pl = p["plan"]
            rows.append({"가격대": p["band"], "판정": VERDICT["buy"], "순위": p["rank"], "종목": p["ticker"], "회사명": p["name"],
                         "주가": f"{p['price']:.2f}", "총점": f"{p['total']:.0f}",
                         **{k: ("" if v is None else f"{v:.0f}") for k, v in p["cats"].items()},
                         "이유": " · ".join(p["reasons"]), "매수 구간": f"{pl['zone_low']:.2f}~{pl['zone_high']:.2f}",
                         "손절": f"{pl['stop']:.2f}", "1차 목표": f"{pl['target']:.2f}", "유효 기한": pl["valid_until"],
                         "연속 일수": p["streak"], "어제 대비": "신규" if p["streak"] == 1 else "유지", "표시": " · ".join(p["tags"]),
                         "쉬운 설명": p.get("desc", ""), "주의 한 줄": p.get("caution", ""), "위험 경고": p.get("warn", "")})
        for r in reference:
            pl = r["plan"]
            rows.append({"가격대": "참고(매수 쉬는 날)", "판정": "참고", "종목": r["ticker"], "회사명": r["name"], "주가": f"{r['price']:.2f}",
                         "총점": f"{r['total']:.0f}", "매수 구간": f"{pl['zone_low']:.2f}~{pl['zone_high']:.2f}", "손절": f"{pl['stop']:.2f}",
                         "1차 목표": f"{pl['target']:.2f}"})
        for s in sells:
            rows.append({"가격대": "내 보유", "판정": VERDICT["sell"], "종목": s["ticker"], "주가": f"{s['close']:.2f}",
                         "이유": s["why"], "손절": f"{s['stop']:.2f}", "표시": s["action"]})
        for h in holdings:
            t = h["ticker"].replace(".", "-")
            r = results.get(t)
            if r and not any(s["ticker"] == h["ticker"] for s in sells):
                rows.append({"가격대": "내 보유", "판정": VERDICT["hold"], "종목": h["ticker"], "주가": f"{r['price']:.2f}",
                             "총점": f"{r['total']:.0f}", **{k: ("" if v is None else f"{v:.0f}") for k, v in r["cats"].items()},
                             "이유": " · ".join(r["reasons"]),
                             "표시": f"수익률 {(r['price'] / h['avg'] - 1) * 100:+.1f}%"})
        rows += extra_rows
        for row in rows:
            row["날짜"] = today_iso
            row["시장 국면"] = REGIME[mk["regime"]]
        if not dry:
            store.overwrite("오늘 리스트", pd.DataFrame(rows))
            store.append("신호 기록", [{"날짜": today_iso, "시장 국면": REGIME[mk["regime"]], "종목": p["ticker"], "판정": VERDICT["buy"],
                                     "순위": p["rank"], "가격대": p["band"], "그날 주가": f"{p['price']:.2f}", "총점": f"{p['total']:.0f}",
                                     "손절": f"{p['plan']['stop']:.2f}", "1차 목표": f"{p['plan']['target']:.2f}"} for p in picks])

        # ---- 발송 ----
        stage = "발송"
        report = {"date_label": f"{now.month}월 {now.day}일", "market": mk, "sell": sells, "bands": bands,
                  "buy_total": len(picks), "stock_total": sum(len(b["picks"]) for b in bands), "new_count": new_count, "warnings": warn,
                  "web_url": __import__("os").environ.get("WEB_URL", "")}
        app = appdata.build_daily(report, holdings_view, bar_date, now.isoformat(timespec="minutes"))
        if dry:
            print("\n" + notify.subject(report) + "\n\n" + notify.text_body(report))
            print("\n[앱 데이터] 보유 " + ", ".join(f"{h['t']}={h['conclusion']}" for h in app["holdings"])
                  + f" · 크기 {len(appdata.dumps(app)):,}자")
            sent = {"mail": False, "slack": False}
        else:
            sent = notify.send_report(report)
            try:
                store.put_blob("daily", appdata.dumps(app))
                s = app["summary"]
                appdata.add_alert(store, "daily", "아침 리포트 도착", f"매도 {s['sell']} · 신규 매수 {s['new']} · 매수 후보 {s['buy']}",
                                  now.isoformat(timespec="minutes"), "info")
            except Exception as e:
                log.warning("앱 데이터 저장 실패: %s", e)
        took = int(time.time() - t0)
        store.append("실행 기록", [{"날짜": now.strftime("%Y-%m-%d"), "시각": now.strftime("%H:%M"), "종류": "아침 리포트",
                                  "성공/실패": "성공", "분석한 종목 수": len(base), "걸린 시간(초)": took,
                                  "메모": f"메일 {'O' if sent['mail'] else 'X'} · 슬랙 {'O' if sent['slack'] else 'X'} · 국면 {REGIME[mk['regime']]}"}])
        if not dry:
            state.update({"last_bar_date": bar_date, "regime": mk["regime"], "last_run": now.isoformat()})
            save_state(state)
        return {"report": report, "results": results, "analyzed": len(base)}
    except Exception as e:
        took = int(time.time() - t0)
        msg = f"{stage} 단계에서 멈췄어요: {e}"
        log.error(traceback.format_exc())
        try:
            store.append("실행 기록", [{"날짜": now.strftime("%Y-%m-%d"), "시각": now.strftime("%H:%M"), "종류": "아침 리포트",
                                      "성공/실패": "실패", "걸린 시간(초)": took, "막힌 단계": stage, "메모": str(e)[:200]}])
        except Exception:
            pass
        if not dry:
            notify_fail(msg)
        raise


# ======================================================================
# 장 시작 전 점검 · 장중 감시
# ======================================================================

def _us_market_open(now_utc) -> tuple[bool, bool]:
    """(장중인가, 장 시작 30분 전 창인가). 미국 동부 시간 기준."""
    from zoneinfo import ZoneInfo

    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    if et.weekday() >= 5:
        return False, False
    mins = et.hour * 60 + et.minute
    return (9 * 60 + 30 <= mins <= 16 * 60), (8 * 60 + 30 <= mins < 9 * 60 + 30)


def run_watch(kind: str, dry: bool):
    from datetime import datetime, timezone

    open_now, pre = _us_market_open(datetime.now(timezone.utc))
    if kind == "intraday" and not open_now and not dry:
        log.info("지금은 미국 장중이 아니에요 → 종료")
        return
    if kind == "premarket" and not pre and not dry:
        log.info("장 시작 전 시간이 아니에요 → 종료")
        return
    store = Store()
    cfg, _ = config.merge_settings(store.settings())
    holdings = store.holdings()
    if not holdings:
        return
    state = load_state()
    today = config.now_kst().strftime("%Y-%m-%d")
    sent_today = set(state.get("alerts", {}).get(today, []))
    live = prices.last_price_intraday([h["ticker"].replace(".", "-") for h in holdings])
    lines = []
    app_items = []
    for h in holdings:
        t = h["ticker"].replace(".", "-")
        q = live.get(t)
        if not q:
            continue
        stop = h["stop"] or h["avg"] * (1 - float(cfg["최대 손실(%)"]) / 100)
        price = q["price"]
        chg = (price / q["prev_close"] - 1) * 100 if q["prev_close"] else 0
        if kind == "premarket":
            near = (price / stop - 1) * 100
            if near <= float(cfg["손절선 근접(%)"]):
                lines.append(f"• *{h['ticker']}* {price:.2f} · 손절선 {stop:.2f}까지 {near:.1f}%")
                app_items.append((f"{h['ticker']} 손절선 근접", f"손절선 {stop:.2f}까지 {near:.1f}%", "warn"))
        else:
            reason = None
            if price <= stop:
                reason = f"손절선 {stop:.2f} 도달"
            elif chg <= float(cfg["장중 급락 기준(%)"]):
                reason = f"하루 {chg:.1f}% 하락"
            key = __import__("hashlib").sha1(f"{t}:{reason[:4] if reason else ''}".encode()).hexdigest()[:10]  # 공개 저장소라 종목명은 남기지 않아요
            if reason and key not in sent_today:
                lines.append(f"• *{h['ticker']}* 현재 {price:.2f} · {reason}")
                app_items.append((f"{h['ticker']} {reason}", f"현재 {price:.2f}", "bad" if "손절" in reason else "warn"))
                sent_today.add(key)
    if not lines:
        return
    title = ":hourglass: 장 시작 전 점검 · 손절선에 가까운 보유 종목" if kind == "premarket" else ":rotating_light: 장중 경고 · 내 보유 종목"
    text = title + "\n" + "\n".join(lines) + "\n_무료 시세는 15분가량 늦을 수 있어요. 정확한 손절은 증권사 예약 주문으로._"
    if dry:
        print(text)
        return
    notify.send_slack(text)
    at = config.now_kst().isoformat(timespec="minutes")
    for title_, body_, tone_ in app_items:
        try:
            appdata.add_alert(store, kind, title_, body_, at, tone_)
        except Exception as e:
            log.warning("앱 알림 기록 실패: %s", e)
    state.setdefault("alerts", {})[today] = sorted(sent_today)
    state["alerts"] = {k: v for k, v in state["alerts"].items() if k >= today}  # 오늘 것만 보관
    save_state(state)


# ======================================================================
# 주간 요약 · 신호 성적
# ======================================================================

def run_weekly(dry: bool):
    store = Store()
    log_df = store.read("신호 기록")
    if log_df.empty:
        msg = "아직 신호 기록이 없어요."
        print(msg) if dry else notify.send_text("주간 요약", msg)
        return
    tickers = sorted(set(log_df["종목"]))
    hist = prices.download_history([t.replace(".", "-") for t in tickers], period="90d")
    r5, r20 = [], []
    for _, row in log_df.iterrows():
        df = hist.get(row["종목"].replace(".", "-"))
        v5 = v20 = ""
        try:
            base = float(row["그날 주가"])
            idx = df.index.strftime("%Y-%m-%d")
            pos = int(np.searchsorted(idx, row["날짜"]))
            if pos + 5 < len(df):
                v5 = f"{(df['Close'].iloc[pos + 5] / base - 1) * 100:.1f}"
            if pos + 20 < len(df):
                v20 = f"{(df['Close'].iloc[pos + 20] / base - 1) * 100:.1f}"
        except Exception:
            pass
        r5.append(v5)
        r20.append(v20)
    log_df["5일 뒤 수익률"], log_df["20일 뒤 수익률"] = r5, r20
    if not dry:
        store.overwrite("신호 기록", log_df)
    done = log_df[log_df["5일 뒤 수익률"] != ""].copy()
    done["r5"] = done["5일 뒤 수익률"].astype(float)
    lines = ["■ 지난 신호 성적 (5일 뒤 기준)"]
    if len(done):
        lines.append(f"전체 {len(done)}개 · 수익 비율 {(done['r5'] > 0).mean() * 100:.0f}% · 평균 {done['r5'].mean():+.1f}%")
        for col in ("순위", "시장 국면", "가격대"):
            g = done.groupby(col)["r5"].agg(["count", "mean", lambda s: (s > 0).mean() * 100])
            lines.append(f"\n[{col}별]")
            for k, v in g.iterrows():
                lines.append(f"  {k}: {int(v['count'])}개 · 평균 {v['mean']:+.1f}% · 수익 비율 {v.iloc[2]:.0f}%")
    else:
        lines.append("아직 5거래일이 지난 신호가 없어요.")
    lines.append("\n표본이 적을 때의 숫자는 우연일 수 있어요. 한 달 이상 쌓인 뒤에 판단하세요.")
    text = "\n".join(lines)
    print(text) if dry else notify.send_text("주간 요약 · 신호 성적", text)


def notify_fail(msg: str):
    text = f":x: 오늘 아침 분석이 실패했어요 — {msg}\n깃허브 Actions 기록에서 자세한 내용을 볼 수 있어요."
    notify.send_slack(text)
    notify.send_mail("[미국주식] 아침 분석 실패", text.replace(":x: ", ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["daily", "premarket", "intraday", "weekly", "fail"])
    ap.add_argument("message", nargs="?", default="")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.mode == "daily":
        run_daily(a.limit, a.dry)
    elif a.mode in ("premarket", "intraday"):
        run_watch(a.mode, a.dry)
    elif a.mode == "weekly":
        run_weekly(a.dry)
    else:
        notify_fail(a.message or "원인을 알 수 없어요")
    sys.exit(0)
