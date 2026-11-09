"""Regression tests for trading-performance corrections and comparison engine."""
import unittest
from unittest.mock import patch

import pandas as pd

import performance
from validation.compare_strategies import metrics, net_return, signals


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


if __name__ == "__main__":
    unittest.main()
