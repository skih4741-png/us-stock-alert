"""Regression tests for trading-performance corrections and comparison engine."""
import unittest
import json
from unittest.mock import patch

import pandas as pd

import performance
from validation.compare_strategies import metrics, net_return, signals
from validation.portfolio import _risk_metrics, opening_regimes, rank_signal_candidates
from validation.promotion import assess_strategy
from execution_rules import entry_fill, exit_fill, next_open_market_exit
import simtrade
import config
import operations_health
from validation.oos_review import holdout_review
from validation.policy_publisher import compose_policy
from datetime import date
from unittest.mock import patch
from strategy_policy import allowed, sign_policy
from validation.diagnostics import trade_attribution
from validation.historical_universe import read_membership_csv
from validation.research_pipeline import acquire
from pathlib import Path
import tempfile


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


class TestCausalMarketFilter(unittest.TestCase):
    def test_current_close_cannot_change_current_open_regime(self):
        idx = pd.bdate_range("2023-01-01", periods=280)
        spy = pd.DataFrame({"Close": [100 + i * 0.2 for i in range(len(idx))]}, index=idx)
        baseline = opening_regimes(spy)
        altered = spy.copy()
        altered.iloc[-1, 0] = 1
        changed = opening_regimes(altered)
        self.assertEqual(baseline.iloc[-1], changed.iloc[-1])

    def test_no_current_regime_at_first_observation(self):
        idx = pd.bdate_range("2023-01-01", periods=3)
        spy = pd.DataFrame({"Close": [100, 101, 102]}, index=idx)
        self.assertTrue(pd.isna(opening_regimes(spy).iloc[0]))


class TestAttribution(unittest.TestCase):
    def test_exit_and_regime_diagnostics_use_closed_pnl(self):
        d = trade_attribution([
            {"ticker": "AAA", "reason": "stop", "regime": "bull", "pnl": -20},
            {"ticker": "AAA", "reason": "target", "regime": "bull", "pnl": 30},
        ])
        self.assertEqual(d["regime"]["bull"]["trades"], 2)
        self.assertEqual(d["regime"]["bull"]["profit_factor"], 1.5)
        self.assertEqual(d["reason"]["stop"]["realized_pnl_usd"], -20)


class TestHistoricalMembership(unittest.TestCase):
    def test_membership_boundaries(self):
        with tempfile.TemporaryDirectory() as td:
            file = Path(td) / "membership.csv"
            file.write_text(
                "ticker,start_date,end_date\nAAA,2020-01-01,2021-12-31\n"
                "BBB,2021-02-03,\n", encoding="utf-8"
            )
            member = read_membership_csv(file)
            self.assertTrue(member.includes("AAA", "2021-12-31"))
            self.assertFalse(member.includes("AAA", "2022-01-01"))
            self.assertTrue(member.includes("BBB", "2024-01-01"))
            self.assertFalse(member.includes("CCC", "2024-01-01"))


class TestReproducibleResearch(unittest.TestCase):
    def test_rank_uses_previous_close_information_only(self):
        ix = pd.bdate_range("2024-01-01", periods=2)
        a = pd.DataFrame({"ret63": [0.5, -9], "dv20": [200, 1]}, index=ix)
        b = pd.DataFrame({"ret63": [0.2, 999], "dv20": [100, 999]}, index=ix)
        pending = pd.Series([False, True], index=ix)
        result = rank_signal_candidates({"B": (b, pending), "A": (a, pending)}, ix[-1])
        self.assertEqual(result, ["A", "B"])

    def test_missing_requested_ticker_fails_instead_of_biasing_results(self):
        ix = pd.bdate_range("2024-01-01", periods=300)
        frame = pd.DataFrame({
            "Open": 100.0, "High": 102.0, "Low": 99.0,
            "Close": 100.0, "Volume": 100000,
        }, index=ix)
        listing = pd.DataFrame({
            "yf_ticker": ["AAA", "BBB"],
            "price": [100, 100], "volume": [10000, 10000],
        })
        with patch("validation.research_pipeline.universe.load_universe",
                   return_value=(listing, "mock")), patch(
                   "validation.research_pipeline.prices.download_history",
                   return_value={"SPY": frame, "AAA": frame}):
            with self.assertRaisesRegex(ValueError, "Data coverage incomplete"):
                acquire({}, 2, 2, None)


class _MemoryStore:
    def __init__(self):
        self.data = {}

    def get_blob(self, key):
        return self.data.get(key)

    def put_blob(self, key, value):
        self.data[key] = value


class TestPaperExecutionCompatibility(unittest.TestCase):
    def test_prior_close_exit_uses_next_open_and_no_future_prices(self):
        dates = pd.bdate_range("2024-01-15", "2024-03-06")
        prices_ = pd.DataFrame({
            "Open": 110.0, "High": 112.0, "Low": 98.0,
            "Close": 110.0, "Volume": 100000,
        }, index=dates)
        prices_.loc["2024-03-04", ["Open", "High", "Low", "Close"]] = [100, 110, 97, 100]
        prices_.loc["2024-03-05", ["Open", "High", "Low", "Close"]] = [104, 110, 100, 105]
        prices_.loc["2024-03-06", ["Open", "High", "Low", "Close"]] = [1, 2, 0.5, 1]
        store = _MemoryStore()
        st = simtrade.start(store, "2024-02-10", budget=1000)
        st["checked"] = "2024-03-01"
        st["cfg"]["stale_days"] = 100
        st["cash"] = 900.0
        st["positions"] = [{
            "t": "AAA", "qty": 1, "entry": 100.0, "date": "2024-02-28",
            "stop": 90.0, "target": 150.0, "peak": 150.0, "half": True,
        }]
        simtrade.save(store, st)
        with patch("simtrade.prices.download_history", return_value={
            "AAA": prices_, "SPY": prices_,
        }):
            first = simtrade.step(
                store, [], "2024-03-04",
                {"regime": "sideways", "rest_day": True}, "2024-03-04T20:00"
            )
            self.assertEqual(len(first["closed"]), 0)
            self.assertEqual(len(first["positions"]), 1)
            self.assertEqual(first["positions"][0]["scheduled_at"], "2024-03-04")
            second = simtrade.step(
                store, [], "2024-03-05",
                {"regime": "sideways", "rest_day": True}, "2024-03-05T20:00"
            )
            self.assertEqual(len(second["closed"]), 1)
            self.assertAlmostEqual(second["closed"][0]["exit"], 104 * (1-0.0015), places=3)
            self.assertEqual(len(second["positions"]), 0)

    def test_shared_market_exit_is_not_prior_close(self):
        self.assertAlmostEqual(next_open_market_exit(120).price, 120 * 0.9985)


class TestProductionDefaults(unittest.TestCase):
    def test_verified_stock_alert_filter_is_off(self):
        merged, warnings = config.merge_settings({})
        self.assertEqual(merged["검증 전략만 표시"], "아니오")
        self.assertEqual(warnings, [])

    def test_verified_policy_missing_rejects_candidate(self):
        from strategy_policy import allowed
        ok, _ = allowed("돌파", enabled=True, policy_path=Path("/nonexistent-policy-for-test.json"))
        self.assertFalse(ok)


class TestOperationsHealth(unittest.TestCase):
    def test_failed_step_overrides_successful_process(self):
        r = operations_health.build_health(
            kind="daily", at="2026-11-09T07:00:00",
            success=True, checks=[
                {"n": "메일·슬랙 발송", "ok": False, "d": "not sent"},
                {"n": "앱 데이터 저장", "ok": True, "d": "saved"},
                {"n": "자동 모의투자", "ok": True, "d": "updated"},
            ])
        self.assertEqual(r["state"], "failed")
        self.assertIn("메일·슬랙 발송", r["failed"])

    def test_missing_evidence_cannot_be_reported_as_ok(self):
        r = operations_health.build_health(
            kind="daily", at="2026-11-09T07:00",
            success=True, checks=[{"n": "앱 데이터 저장", "ok": True}])
        self.assertEqual(r["state"], "incomplete")
        self.assertIn("자동 모의투자", r["missing"])

    def test_persisted_status_is_read_back(self):
        store = _MemoryStore()
        r = operations_health.build_health(
            kind="daily", at="2026-11-09T07:00",
            success=True, checks=[{"n": name, "ok": True} for name in operations_health.CRITICAL])
        operations_health.save_health(store, r)
        self.assertEqual(operations_health.read_health(store)["state"], "ok")

    def test_saved_daily_bar_date_must_match(self):
        store = _MemoryStore()
        store.put_blob("daily", json.dumps({"date": "2026-11-08", "summary": {"buy": 1}}))
        result = operations_health.verify_daily_artifacts(store, "2026-11-09")
        self.assertFalse(result[0]["ok"])


class TestOOSReview(unittest.TestCase):
    def test_positive_metrics_cannot_be_auto_approved_without_provenance(self):
        ix = pd.bdate_range("2020-01-01", periods=450)
        spy = pd.DataFrame({"Close": [100 + i * 0.1 for i in range(len(ix))]}, index=ix)
        with patch("validation.oos_review.simulate_portfolio",
                   return_value={"metrics": {"closed_trades": 300,
                                             "profit_factor": 2.5,
                                             "mdd_pct": -3,
                                             "excess_return_pct": 20}}):
            review = holdout_review({}, spy, {}, None)
        self.assertEqual(review["eligible_for_paper_review"], [])
        self.assertTrue(all(not v["eligible"] for v in review["decisions"].values()))


class TestSignedPromotion(unittest.TestCase):
    def test_unsigned_or_tampered_policy_fails_closed(self):
        payload = {
            "policy_version": 1, "issued_on": "2026-11-09", "valid_until": "2026-11-23",
            "independent_oos_verified": True, "historical_universe_verified": True,
            "forward_paper_verified": True, "source_dataset_sha256": "a"*64,
            "approved_strategies": ["breakout"],
        }
        secret = "a-long-32-character-test-secret-key-12345"
        signed = sign_policy(payload, secret)
        with patch.dict("os.environ", {"STRATEGY_POLICY_HMAC_KEY": secret}):
            self.assertTrue(allowed("돌파", enabled=True, today=date(2026, 11, 10),
                                    policy_text=json.dumps(signed))[0])
            signed["approved_strategies"] = ["breakout", "pullback"]
            self.assertFalse(allowed("눌림목", enabled=True, today=date(2026, 11, 10),
                                     policy_text=json.dumps(signed))[0])

    def test_old_or_expired_policy_fails_closed(self):
        secret = "another-long-32-character-secret-key-123"
        base = {
            "policy_version": 1, "issued_on": "2026-10-01", "valid_until": "2026-10-15",
            "independent_oos_verified": True, "historical_universe_verified": True,
            "forward_paper_verified": True, "source_dataset_sha256": "b"*64,
            "approved_strategies": ["breakout"]
        }
        with patch.dict("os.environ", {"STRATEGY_POLICY_HMAC_KEY": secret}):
            self.assertFalse(allowed("돌파", enabled=True, today=date(2026, 11, 9),
                                     policy_text=json.dumps(sign_policy(base, secret)))[0])

    def test_no_approved_strategy_from_unverified_inputs(self):
        with self.assertRaises(ValueError):
            compose_policy(
                {"independent_oos_verified": False},
                {"metrics": {}}, {"verified": True, "days": 100},
                today=date(2026, 11, 9),
                secret="very-long-32-character-valid-secret-123",
            )


class TestSafeRecoveryAndWeeklyStatistics(unittest.TestCase):
    def test_weekly_success_rate_and_duration(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 9, 9, tzinfo=timezone.utc)
        runs = [
            {"kind": "daily", "at": "2026-11-09T07:00:00+00:00", "ok": True, "took": 40},
            {"kind": "daily", "at": "2026-11-08T07:00:00+00:00", "ok": "warn", "took": 100},
            {"kind": "daily", "at": "2026-11-07T07:00:00+00:00", "ok": False, "took": 160},
            {"kind": "intraday", "at": "2026-11-09T08:00:00+00:00", "ok": True, "took": 4},
            {"kind": "daily", "at": "2026-10-20T07:00:00+00:00", "ok": True, "took": 99},
        ]
        m = operations_health.weekly_metrics(runs, now)
        self.assertEqual(m["total"], 3)
        self.assertEqual(m["success"], 1)
        self.assertEqual(m["failed"], 1)
        self.assertEqual(m["partial"], 1)
        self.assertEqual(m["success_rate_pct"], 33.3)
        self.assertEqual(m["mean_seconds"], 100.0)

    def test_missing_timestamps_do_not_count_as_success(self):
        from datetime import datetime, timezone
        m = operations_health.weekly_metrics(
            [{"kind": "daily", "at": "2026-11-09T07:00", "ok": True, "took": 8}],
            datetime(2026, 11, 9, 9, tzinfo=timezone.utc))
        self.assertIsNone(m["success_rate_pct"])

    def test_restore_daily_snapshot_without_trading_or_notification(self):
        store = _MemoryStore()
        source = json.dumps({"date": "2026-11-09", "summary": {"buy": 1}})
        out = operations_health.repair_daily_blob(store, "2026-11-09", source)
        self.assertEqual(out["status"], "repaired")
        self.assertEqual(store.get_blob("daily"), source)
        self.assertEqual(operations_health.repair_daily_blob(store, "2026-11-09", source)["status"], "verified")

    def test_newer_data_cannot_be_overwritten(self):
        store = _MemoryStore()
        store.put_blob("daily", json.dumps({"date": "2026-11-10", "summary": {}}))
        source = json.dumps({"date": "2026-11-09", "summary": {}})
        self.assertEqual(operations_health.repair_daily_blob(store, "2026-11-09", source)["status"], "blocked")

    def test_unsafe_steps_cannot_be_automatically_replayed(self):
        p = operations_health.recovery_plan([
            {"n": "자동 모의투자", "ok": False},
            {"n": "메일·슬랙 발송", "ok": False},
            {"n": "앱 데이터 읽기 검증", "ok": False},
        ])
        self.assertEqual([x["mode"] for x in p], ["manual", "manual", "auto_safe"])


if __name__ == "__main__":
    unittest.main()
