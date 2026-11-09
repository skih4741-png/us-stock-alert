"""Regression tests for trading-performance corrections and comparison engine."""
import unittest
from unittest.mock import patch

import pandas as pd

import performance
from validation.compare_strategies import metrics, net_return, signals
from validation.portfolio import _risk_metrics
from validation.promotion import assess_strategy
from execution_rules import entry_fill, exit_fill
from strategy_policy import allowed


class TestMetrics(unittest.TestCase):
    def test_profit_factor_uses_total_profit_and_total_loss(self):
        v = performance._stats([10, 10, 10, -8, -8, -8, -8, -8, -8])
        self.assertAlmostEqual(v["pf"], 0.62, places=2)

    def test_compare_profit_factor(self):
        v = metrics([0.10, 0.10, -0.20])
        self.assertAlmostEqual(v["profit_factor"], 1.0)

    def test_cost_reduces_return(self):
        self.assertLess(net_return(0.0), 0.0)
        self.assertLess(net_return(0.05), 0.05)


class TestSignalCausality(unittest.TestCase):
    def test_future_bars_do_not_change_past_signal(self):
        n = 300
        idx = pd.bdate_range("2020-01-01", periods=n)
        close = pd.Series([100 + i * 0.12 for i in range(n)], index=idx)
        frame = pd.DataFrame(index=idx)
        frame["close"] = close
        frame["ma20"] = close.rolling(20).mean()
        frame["ma50"] = close.rolling(50).mean()
        frame["ma200"] = close.rolling(200).mean()
        frame["volr"] = 1.8
        frame["rsi"] = 50.0
        a = signals(frame)
        changed = frame.copy()
        changed.loc[changed.index[-1], "close"] = 100000.0
        b = signals(changed)
        for name in a:
            self.assertEqual(a[name].iloc[:-1].tolist(), b[name].iloc[:-1].tolist())


class TestSharedFills(unittest.TestCase):
    def test_limit_fill_and_no_fill(self):
        self.assertAlmostEqual(entry_fill(100, 98, 99, 103, 94).price, 99)
        self.assertIsNone(entry_fill(104, 98, 99, 103, 94))
        self.assertIsNone(entry_fill(100, 99.5, 99, 103, 94))

    def test_stop_priority_on_ambiguous_bar(self):
        d = exit_fill(100, 120, 90, 95, 110)
        self.assertEqual(d.reason, "stop")
        self.assertLess(d.price, 95)

    def test_target_disabled_on_entry_bar(self):
        self.assertIsNone(exit_fill(100, 120, 97, 95, 110, fresh=True))
        self.assertEqual(exit_fill(100, 120, 97, 95, 110).reason, "target")


class TestPortfolioMetrics(unittest.TestCase):
    def test_mdd_and_spy_comparison(self):
        ix = pd.bdate_range("2024-01-01", periods=3)
        spy = pd.DataFrame({"Close": [100, 105, 110]}, index=ix)
        e = [{"date": d.strftime("%Y-%m-%d"), "equity": v}
             for d, v in zip(ix, [10000, 9000, 10500])]
        result = _risk_metrics(e, spy, 10000, [])
        self.assertAlmostEqual(result["mdd_pct"], -10.0)
        self.assertAlmostEqual(result["total_return_pct"], 5.0)
        self.assertAlmostEqual(result["spy_return_pct"], 10.0)
        self.assertAlmostEqual(result["excess_return_pct"], -5.0)


class TestFailClosedGate(unittest.TestCase):
    def test_unverified_performance_never_promotes(self):
        metrics = {"closed_trades": 200, "profit_factor": 2.0,
                   "mdd_pct": -5, "excess_return_pct": 15}
        d = assess_strategy(metrics, independent_oos=False, verified_universe=False)
        self.assertFalse(d["eligible"])
        self.assertEqual(d["action"], "observe_only")

    def test_paper_policy_opt_in_rejects_missing_evidence(self):
        self.assertTrue(allowed("돌파", enabled=False)[0])
        ok, reason = allowed("돌파", enabled=True)
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_missing_metrics_fail_closed(self):
        self.assertFalse(assess_strategy({}, independent_oos=True,
                                         verified_universe=True)["eligible"])


if __name__ == "__main__":
    unittest.main()
