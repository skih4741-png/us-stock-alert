"""실행 기록(proof of work) · 점검 정직성 테스트 — 시트 없이 가짜 저장소로 돌려요. python -m pytest tests"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import appdata  # noqa: E402


class FakeStore:
    def __init__(self):
        self.b = {}

    def get_blob(self, k):
        return self.b.get(k, "")

    def put_blob(self, k, v):
        self.b[k] = v


def runs(st):
    return json.loads(st.b["perf"])["runs"]


def test_add_run_keeps_other_perf_fields_and_order():
    st = FakeStore()
    st.put_blob("perf", json.dumps({"sim": {"equity": 1000}}))
    appdata.add_run(st, "daily", "2026-10-16T07:01+09:00", True, 30, ["후보 3개"], [{"n": "가격 기준일", "ok": True, "d": ""}])
    appdata.add_run(st, "intraday", "2026-10-16T23:00+09:00", True, 5, [], [])
    p = json.loads(st.b["perf"])
    assert p["sim"]["equity"] == 1000
    assert [r["kind"] for r in p["runs"]] == ["intraday", "daily"]
    assert p["runs"][1]["label"] == "아침 리포트"


def test_failed_check_downgrades_success_to_warn():
    st = FakeStore()
    appdata.add_run(st, "daily", "t", True, 1, [], [{"n": "경제뉴스", "ok": False, "d": "x"}, {"n": "AI", "ok": None, "d": ""}])
    assert runs(st)[0]["ok"] == "warn"


def test_unchecked_is_not_counted_as_pass():
    st = FakeStore()
    appdata.add_run(st, "daily", "t", True, 1, [], [{"n": "AI", "ok": None, "d": "GPT 꺼짐"}])
    r = runs(st)[0]
    assert r["ok"] is True and r["checks"][0]["ok"] is None


def test_keep_limit_and_err_tail():
    st = FakeStore()
    for i in range(70):
        appdata.add_run(st, "intraday", f"t{i}", False, 1, [], [], err="x" * 2000)
    r = runs(st)
    assert len(r) == 60 and len(r[0]["err"]) == 600


def test_save_perf_preserves_runs(monkeypatch):
    import main
    st = FakeStore()
    appdata.add_run(st, "daily", "t", True, 1, ["a"], [])
    monkeypatch.setattr(main.performance, "update", lambda s: {"signals": {}, "paper": {"trades": []}})
    monkeypatch.setattr(main.simtrade, "load", lambda s, k=None: None)
    main.save_perf(st, pd.Timestamp("2026-10-16T07:00"))
    assert runs(st)[0]["changed"] == ["a"]


def test_watch_records_failure_and_reraises(monkeypatch):
    import main
    st = FakeStore()
    monkeypatch.setattr(main, "Store", lambda: st)

    def boom(kind, dry, changed):
        main.chk("실시간 시세", False, "끊김")
        raise RuntimeError("시세 서버 응답 없음")
    monkeypatch.setattr(main, "_run_watch", boom)
    with pytest.raises(RuntimeError):
        main.run_watch("intraday", False)
    r = runs(st)[0]
    assert r["ok"] is False and r["checks"][0]["n"] == "실시간 시세" and "응답 없음" in r["err"]


def test_watch_closed_market_leaves_no_record(monkeypatch):
    import main
    st = FakeStore()
    monkeypatch.setattr(main, "_run_watch", lambda k, d, c: None)
    main.run_watch("intraday", False)
    assert "perf" not in st.b


def _ohlc(n=260, drift=0.001, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.cumprod(1 + drift + rng.normal(0, 0.01, n))
    idx = pd.bdate_range("2025-09-01", periods=n)
    return pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)


def test_chart_uptrend_labels():
    import chart
    r = chart.analyze(_ohlc(drift=0.004))
    assert r["trend"] == "상승 추세" and r["lo52"] < r["price"] <= r["hi52"] * 1.0001
    assert r["ma"][20] > r["ma"][60] > r["ma"][120]


def test_portfolio_concentration_flag():
    import portfolio
    hist = {"AAA": _ohlc(seed=1), "BBB": _ohlc(seed=2), "SPY": _ohlc(seed=3)}
    holds = [{"t": "AAA", "qty": 9, "price": 100, "avg": 90}, {"t": "BBB", "qty": 1, "price": 100, "avg": 100}]
    r = portfolio.analyze(holds, hist, lambda t: "기술")
    assert r["items"][0]["t"] == "AAA" and r["items"][0]["weight"] == 90.0
    assert any("한 바구니" in f for f in r["flags"])
