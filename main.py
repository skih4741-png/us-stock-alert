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

import ai
import appdata
import config
import financials
import lists
import market
import notify
import performance
import prices
import push
import research
import scoring
import simtrade
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

def run_daily(limit: int | None, dry: bool, app_only: bool = False) -> dict:
    """app_only: 보내거나 기록하지 않고 앱 데이터만 시트에 저장 (앱 첫 설치·시험용)."""
    dry = dry or app_only
    t0 = time.time()
    now = config.now_kst()
    stage = "시작"
    store = Store()
    cfg, warn = config.merge_settings(store.settings())
    ai.init(store, cfg)
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

        # 쉬운 재무제표 (매수 후보 + 내 보유)
        stage = "재무제표"
        fin_meta = {}
        for t in [p["ticker"] for p in picks] + hold_t:
            r0 = results.get(t)
            fin_meta[t] = {"price": (r0 or {}).get("price") or (float(hist[t]["Close"].iloc[-1]) if t in hist else None),
                           "sector": (r0 or {}).get("sector"), "name": (r0 or {}).get("name"),
                           "etf": bool((r0 or {}).get("etf")) or is_etf(t)}
        try:
            fin = financials.summaries(list(fin_meta), fin_meta)
        except Exception as e:
            log.warning("재무제표 단계 실패: %s", e)
            fin = {}
        for p in picks:
            if (fin.get(p["ticker"]) or {}).get("verdict") == "bad":
                p["tags"].append("재무 주의")

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
        ai_out = explain(items, cfg)
        for p in picks:
            a = ai_out.get(p["ticker"], {})
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
        app = appdata.build_daily(report, holdings_view, bar_date, now.isoformat(timespec="minutes"), fin)
        if dry:
            print("\n" + notify.subject(report) + "\n\n" + notify.text_body(report))
            print("\n[앱 데이터] 보유 " + ", ".join(f"{h['t']}={h['conclusion']}" for h in app["holdings"])
                  + f" · 크기 {len(appdata.dumps(app)):,}자")
            if app_only:
                store.put_blob("daily", appdata.dumps(app))
                print("[앱 데이터] 시트 '앱 데이터' 탭에 저장했어요")
                run_sim(store, app, now)
                run_ai(store, app, cfg, now, send=False)
                save_perf(store, now)
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
            try:
                n = push.send(store, "아침 리포트 · " + REGIME[mk["regime"]],
                              f"매도 {s['sell']} · 신규 매수 {s['new']} · 매수 후보 {s['buy']}", "#/home", "daily")
                log.info("푸시 %d개 보냄", n)
            except Exception as e:
                log.warning("푸시 실패: %s", e)
            run_sim(store, app, now)
            run_ai(store, app, cfg, now)
            save_perf(store, now)
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


def run_gap(store, holdings: list[dict], dry: bool):
    """F-A7 장 전 갭 스캐너: 보유 + 어제 후보 + 모의 주문 계획 종목의 장 전 가격 (무료 자료라 대상이 좁아요)."""
    import yfinance as yf
    daily = json.loads(store.get_blob("daily") or "{}")
    picks = [p["t"] for b in daily.get("bands", []) for p in b["picks"] + b.get("etf_picks", [])]
    sim = simtrade.load(store) or {}
    held = {h["ticker"] for h in holdings}
    tickers = list(dict.fromkeys(list(held) + picks + [o["t"] for o in sim.get("pending", [])]))[:60]
    items = []
    for t in tickers:
        try:
            info = yf.Ticker(t.replace(".", "-")).info or {}
            pre, prev = info.get("preMarketPrice"), info.get("regularMarketPreviousClose") or info.get("previousClose")
            if not pre or not prev:
                continue
            gap = (pre / prev - 1) * 100
            vol = info.get("preMarketVolume")
            news = prices.news_headlines(t.replace(".", "-"), 1)
            cond = abs(gap) >= 5 and pre >= 3 and (vol is None or vol >= 50000)
            items.append({"t": t, "gap": round(gap, 2), "pre": round(pre, 2), "prev": round(prev, 2), "vol": vol,
                          "news": news[0]["제목"] if news else "", "held": t in held, "pick": t in picks, "cond": cond})
        except Exception:
            continue
    items.sort(key=lambda x: -abs(x["gap"]))
    blob = {"at": config.now_kst().isoformat(timespec="minutes"), "items": items,
            "note": "보유·어제 후보·모의 주문 종목만 봐요(무료 자료 한계). 장 전 거래량은 자료가 없으면 비어 있어요."}
    if dry:
        print(json.dumps(blob, ensure_ascii=False)[:1500])
        return
    store.put_blob("gap", appdata.dumps(blob))
    big = [x for x in items if x["cond"]]
    if big:
        body = " / ".join(f"{x['t']} {x['gap']:+.1f}%" for x in big[:5])
        appdata.add_alert(store, "gap", "장 전 갭 5% 이상", body, blob["at"], "warn")
        if any(x["held"] or x["t"] in [o["t"] for o in sim.get("pending", [])] for x in big):
            push.send(store, "장 전 갭 · 보유/모의 주문 종목", body, "#/gap", "watch", tag="gap")


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
    if kind == "premarket":
        try:
            run_gap(store, holdings, dry)
        except Exception as e:
            log.warning("장 전 갭 실패: %s", e)
    if kind == "intraday" and not dry:
        try:
            import kisbridge
            kisbridge.run(store)
        except Exception as e:
            log.warning("한국투자증권 모의 연동 실패: %s", e)
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
    if app_items:
        try:
            push.send(store, ("장 시작 전 점검" if kind == "premarket" else "장중 경고") + f" · {len(app_items)}건",
                      " / ".join(t for t, _, _ in app_items[:3]), "#/alerts", "watch")
        except Exception as e:
            log.warning("푸시 실패: %s", e)
    state.setdefault("alerts", {})[today] = sorted(sent_today)
    state["alerts"] = {k: v for k, v in state["alerts"].items() if k >= today}  # 오늘 것만 보관
    save_state(state)


# ======================================================================
# 주간 요약 · 신호 성적
# ======================================================================

def run_ai(store, app: dict, cfg: dict, now, send: bool = True):
    """4단계 GPT 기능 (밤사이 브리핑·실적 카드·4관점·쉬운 리포트·사전 부검). GPT가 꺼져 있으면 건너뛰어요."""
    try:
        blob = research.run_daily(store, app, cfg, simtrade.load(store))
        text = research.brief_text(blob or {})
        items = ((blob or {}).get("brief") or {}).get("items") or []
        if send and text and items:
            notify.send_slack("밤사이 브리핑 · 보유 종목", [{"type": "header", "text": {"type": "plain_text", "text": "밤사이 브리핑 · 보유 종목"}},
                                                     {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}])
            top = [x for x in items if x.get("중요도") == "상"]
            at = now.isoformat(timespec="minutes")
            appdata.add_alert(store, "brief", "밤사이 브리핑", " / ".join(f"{x.get('종목')} {x.get('무슨 일')}" for x in items[:3]), at, "info")
            if top:
                push.send(store, "밤사이 중요 소식 · " + ", ".join(x.get("종목", "") for x in top[:3]),
                          top[0].get("무슨 일", "")[:150], "#/home", "daily", tag="brief")
    except Exception as e:
        log.warning("GPT 기능 실패: %s", e)


def run_sim(store, app: dict, now):
    """자동 모의매매 한 걸음 + 기간이 끝났으면 실전 전환 판단 알림. 실패해도 리포트는 그대로."""
    try:
        picks = [p for b in app.get("bands", []) for p in b["picks"] + b.get("etf_picks", [])]
        st = simtrade.step(store, picks, app["date"], app["market"], now.isoformat(timespec="minutes"))
        try:
            simtrade.step(store, picks, app["date"], app["market"], now.isoformat(timespec="minutes"), key=simtrade.REF_KEY)
        except Exception as e:
            log.warning("참고용 모의 실패: %s", e)
        if st:
            def tell(title, text):
                notify.send_text(title, text)
                appdata.add_alert(store, "sim", title, text.split("\n")[1] if "\n" in text else text, now.isoformat(timespec="minutes"), "info")
                push.send(store, title, "성적 탭 → 자동 모의에서 결과를 봐요", "#/score", "system", tag="sim")
            sig = performance.signal_summary(store.read("신호 기록"))
            # 일일 리포트: 슬랙 매일 + 앱 알림, 사고판 날만 푸시
            title, text, traded = simtrade.daily_text(st, sig)
            at = now.isoformat(timespec="minutes")
            notify.send_slack(title, [{"type": "header", "text": {"type": "plain_text", "text": title[:150]}},
                                      {"type": "section", "text": {"type": "mrkdwn", "text": "```" + text[:2800] + "```"}}])
            appdata.add_alert(store, "sim", title, " / ".join(x for x in (st.get("today") or ["거래 없음"])[:3]), at, "info")
            if traded:
                push.send(store, title, " / ".join(st["today"][:3])[:170], "#/score", "daily", tag="sim")
            simtrade.maybe_evaluate(store, st, tell, sig)
    except Exception as e:
        log.warning("자동 모의매매 실패: %s", e)


def save_perf(store, now, notify_stops: bool = True) -> dict | None:
    """3단계: 신호 성적·모의 계좌를 계산해 앱 '성적' 탭 데이터로 저장. 실패해도 리포트는 그대로."""
    try:
        perf = performance.update(store)
        perf["at"] = now.isoformat(timespec="minutes")
        st = simtrade.load(store)
        perf["sim"] = simtrade.summary(st, perf["signals"]) if st else None
        ref = simtrade.load(store, simtrade.REF_KEY)
        perf["sim_ref"] = simtrade.summary(ref, perf["signals"]) if ref else None
        store.put_blob("perf", appdata.dumps(appdata._clean(perf)))
        hit = [x["t"] for x in perf["paper"]["trades"] if x.get("below_stop")]
        if hit and notify_stops:
            body = ", ".join(hit) + " — 모의 계좌 종목이 손절선 아래예요. 성적 탭에서 팔지 정해 주세요."
            appdata.add_alert(store, "paper", "모의 계좌 손절선 아래", body, perf["at"], "warn")
            push.send(store, "모의 계좌 손절선 아래", body, "#/score", "daily", tag="paper")
        return perf
    except Exception as e:
        log.warning("성적 계산 실패: %s", e)
        return None


def _fmt(v, unit="%"):
    return "—" if v is None else f"{v:+.1f}{unit}"


def run_weekly(dry: bool):
    """F-A12 주간 리포트: 신호 성적 + 모의 계좌 + 보유 결론 변화 + 회고 알림 → 슬랙·메일·앱·푸시."""
    store = Store()
    now = config.now_kst()
    cfg, _ = config.merge_settings(store.settings())
    ai.init(store, cfg)
    perf = save_perf(store, now, notify_stops=False) if not dry else performance.update(store)
    # RAG: 내 거래 기록·회고를 자료로 쌓아요 ('비슷한 지난 거래는 어땠나')
    if not dry:
        try:
            import rag
            docs = []
            for x in (perf.get("paper") or {}).get("trades", []):
                if x.get("sold"):
                    docs.append({"종목": x["t"], "날짜": x.get("sold_date"), "종류": "내 모의 거래",
                                 "제목": f"{x['t']} {x['date']}→{x['sold_date']} {x.get('ret')}%",
                                 "내용": f"{x['t']}를 {x['date']}에 {x['price']}에 사서 {x['sold_date']}에 {x.get('exit')}에 팔았어요. "
                                         f"수익률 {x.get('ret')}%, SPY 대비 {x.get('excess')}%p, 판 이유 {x.get('why_sold')}. 회고: {x.get('note') or '없음'}"})
            for c in ((perf.get("sim") or {}).get("closed") or []):
                docs.append({"종목": c["t"], "날짜": c["exit_date"], "종류": "자동 모의 거래", "제목": f"자동 {c['t']} {c['date']}→{c['exit_date']}",
                             "내용": f"자동 모의매매: {c['t']} {c['qty']}주 {c['entry']}에 사서 {c['exit']}에 팔았어요. 이유 {c['why']}, 손익 {c['pnl']}달러({c['ret']}%)."})
            n = rag.add(store, docs)
            log.info("RAG 거래 기록 %d개 추가", n)
            ai.flush()
        except Exception as e:
            log.warning("RAG 거래 기록 실패: %s", e)
    if perf is None:
        perf = {"signals": {"n": 0}, "paper": {"n": 0}}
    sg, pp = perf["signals"], perf["paper"]
    lines = ["■ 지난 신호 성적"]
    d5, d20 = sg.get("d5", {}), sg.get("d20", {})
    if d5.get("n"):
        lines.append(f"5일 뒤: {d5['n']}개 · 수익 비율 {d5['win']}% · 평균 {_fmt(d5['avg'])} (같은 기간 SPY {_fmt(d5.get('spy'))})")
        lines.append(f"후보마다 100달러씩 샀다면(5일 뒤 팔기): 번 돈 +${d5['usd_gain']:,.2f} · 잃은 돈 -${abs(d5['usd_loss']):,.2f} · 합계 {d5['usd_net']:+,.2f}달러")
    else:
        lines.append("아직 5거래일이 지난 신호가 없어요.")
    if d20.get("n"):
        lines.append(f"20일 뒤: {d20['n']}개 · 수익 비율 {d20['win']}% · 평균 {_fmt(d20['avg'])} (SPY {_fmt(d20.get('spy'))})")
    hit = sg.get("hit", {})
    if hit.get("n"):
        lines.append(f"목표가 먼저 {hit['target']} · 손절 먼저 {hit['stop']} · 20일 안에 둘 다 안 닿음 {hit['none']}")
    for col, g in (sg.get("groups") or {}).items():
        if g:
            lines.append(f"[{col}별 5일] " + " / ".join(f"{x['name']} {x['n']}개 {_fmt(x.get('avg'))}" for x in g[:5]))

    lines.append("\n■ 모의 계좌 (가상 1,000달러)")
    if pp.get("n"):
        lines.append(f"평가 ${pp['equity']:,.2f} ({_fmt(pp['ret'])}) · 같은 돈을 SPY에 넣었을 때보다 {_fmt(pp['excess_pct'])}p")
        m = pp.get("money") or {}
        if m:
            lines.append(f"번 돈 +${m['gain']:,.2f} ({m['wins']}건) · 잃은 돈 -${abs(m['loss']):,.2f} ({m['losses']}건) · "
                         f"판 거래 손익 {m['realized']:+,.2f}달러 · 보유 중 평가손익 {m['unrealized']:+,.2f}달러")
        if pp["pred"]["n"]:
            lines.append(f"예상 적중(목표가 먼저 닿음) {pp['pred']['hit']}/{pp['pred']['n']}")
        if pp["no_note"]:
            lines.append(f"회고를 안 쓴 거래 {pp['no_note']}개 — 앱 성적 탭에서 한 줄 남겨 주세요")
    else:
        lines.append("아직 담은 종목이 없어요. 종목 상세에서 '모의투자에 담기'를 눌러 시작해요.")

    sm = perf.get("sim")
    if sm:
        lines.append(f"\n■ 자동 모의매매 (가상 ${sm['budget']:.0f}, {sm['day']}/{sm['days']}일째)")
        lines.append(f"평가 ${sm['equity']:.2f} ({_fmt(sm['ret'])}) · SPY {_fmt(sm['spy_ret'])} · 번 돈 +${sm['gain']:.2f} · 잃은 돈 -${abs(sm['loss']):.2f}")
        lines.append("실전 기준 " + str(sum(1 for c in sm["checks"] if c[1])) + f"/{len(sm['checks'])} 통과 중 (3개월 끝에 최종 판단)")
        rf = perf.get("sim_ref")
        if rf:
            lines.append(f"참고용 ${rf['budget']:.0f} 모의: {_fmt(rf['ret'])} · 거래 {rf['wins'] + rf['losses']}번 (판단에는 안 써요)")

    # 보유 결론 변화 (지난주 저장본과 비교)
    try:
        daily = json.loads(store.get_blob("daily") or "{}")
        now_c = {h["t"]: h["conclusion"] for h in daily.get("holdings", [])}
        prev_c = json.loads(store.get_blob("weekly_prev") or "{}")
        changed = [f"{t} {prev_c[t]}→{c}" for t, c in now_c.items() if t in prev_c and prev_c[t] != c]
        if prev_c:
            lines.append("\n■ 보유 결론 변화 (지난주 대비)")
            lines.append(", ".join(changed) if changed else "바뀐 종목이 없어요")
        if not dry and now_c:
            store.put_blob("weekly_prev", appdata.dumps(now_c))
    except Exception as e:
        log.info("보유 결론 비교 건너뜀: %s", e)
    lines.append("\n표본이 적을 때의 숫자는 우연일 수 있어요. 한 달 이상 쌓인 뒤에 판단하세요.")
    text = "\n".join(lines)
    if dry:
        print(text)
        return
    notify.send_text("주간 요약 · 신호 성적", text)
    at = now.isoformat(timespec="minutes")
    first = lines[1] if len(lines) > 1 else "지난 신호 성적이 나왔어요"
    try:
        store.put_blob("weekly", appdata.dumps({"at": at, "lines": lines}))
        appdata.add_alert(store, "weekly", "주간 요약", first, at, "info")
        push.send(store, "주간 요약 · 신호 성적", first, "#/score", "weekly")
    except Exception as e:
        log.warning("주간 요약 앱 알림 실패: %s", e)


def notify_fail(msg: str):
    text = f":x: 오늘 아침 분석이 실패했어요 — {msg}\n깃허브 Actions 기록에서 자세한 내용을 볼 수 있어요."
    notify.send_slack(text)
    notify.send_mail("[미국주식] 아침 분석 실패", text.replace(":x: ", ""))
    try:
        push.send(Store(), "아침 분석 실패", msg[:120], "#/alerts", "system")
    except Exception:
        pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["daily", "premarket", "intraday", "weekly", "fail", "pushtest"])
    ap.add_argument("message", nargs="?", default="")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--app-only", action="store_true", help="보내지 않고 앱 데이터만 저장")
    a = ap.parse_args()
    if a.mode == "daily":
        run_daily(a.limit, a.dry, a.app_only)
    elif a.mode in ("premarket", "intraday"):
        run_watch(a.mode, a.dry)
    elif a.mode == "weekly":
        run_weekly(a.dry)
    elif a.mode == "pushtest":
        print("보낸 푸시:", push.send(Store(), "시험 알림", a.message or "푸시 알림이 잘 와요", "#/alerts", "system"))
    else:
        notify_fail(a.message or "원인을 알 수 없어요")
    sys.exit(0)
