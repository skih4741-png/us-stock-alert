"""펀드매니저 4단계 — 배분(skfolio)·백테스트(Nautilus)·예측 채점. 가짜 시세로 돌려요."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("skfolio")
import fund  # noqa: E402


def _hist(n=520, names=("AAA", "BBB", "CCC", "SPY"), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-06-03", periods=n)
    out = {}
    for k, t in enumerate(names):
        c = 100 * np.cumprod(1 + 0.0003 * (k + 1) + rng.normal(0, 0.012, n))
        out[t] = pd.DataFrame({"Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c, "Volume": 1e6}, index=idx)
    return out


def test_allocate_weights_sum_and_cap():
    h = _hist()
    X = fund._returns(h, ["AAA", "BBB", "CCC"])
    w = fund.allocate(X, {"AAA": 0.002, "BBB": -0.001})
    for k in ("meanrisk", "hrp", "equal"):
        assert abs(sum(w[k].values()) - 1) < 1e-3
    assert max(w["meanrisk"].values()) <= fund._max_w(3) + 1e-6
    assert "Black-Litterman" in w["prior"]


def test_allocate_without_views_uses_history():
    X = fund._returns(_hist(), ["AAA", "BBB", "CCC"])
    assert "과거" in fund.allocate(X, None)["prior"]


def test_walk_forward_weights_ignore_future():
    h = _hist()
    day = h["AAA"].index[300]
    past = {t: df.loc[df.index <= day] for t, df in h.items()}
    w1 = fund.weight_fn("meanrisk")(day, past)
    # 미래 자료를 망가뜨려도 그날 비중은 같아야 해요
    h2 = {t: df.copy() for t, df in h.items()}
    for df in h2.values():
        df.loc[df.index > day, "Close"] *= 3
    past2 = {t: df.loc[df.index <= day] for t, df in h2.items()}
    assert fund.weight_fn("meanrisk")(day, past2) == w1


def test_backtest_runs_three_strategies_and_spy():
    pytest.importorskip("nautilus_trader")
    bt = fund.backtest(_hist(), ["AAA", "BBB", "CCC"])
    for k in ("meanrisk", "hrp", "equal", "spy"):
        assert "ret" in bt[k], k
    assert bt["equal"]["trades"] > 10 and bt["equal"]["fees"] > 0


def test_score_forecasts_direction():
    h = _hist()
    d = h["AAA"].index[400]
    last = float(h["AAA"]["Close"].loc[d])
    real5 = float(h["AAA"]["Close"].iloc[405])
    rec = [{"date": str(d.date()), "items": {"AAA": {"last": last, "pred": [last] * 4 + [real5 * 1.001]}}}]
    s = fund.score_forecasts(rec, h)
    assert s["n"] == 1 and s["hit"] == (100 if (real5 > last) == (real5 * 1.001 > last) else 0)
