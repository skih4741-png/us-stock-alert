"""Offline regression tests for the observed production failures. No orders or messages."""
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

import ai
import appdata
import config
import main
import operations_health as health
import research
import sheets
import news
import diagnostics


class MemoryStore:
    def __init__(self):
        self.blobs = {}
    def get_blob(self, key):
        return self.blobs.get(key, "")
    def put_blob(self, key, value):
        self.blobs[key] = value


def test_settings_reach_provider_and_sec_consumers():
    cfg, warnings = config.merge_settings({"AI 공급자 순서": "openrouter,groq", "AI 모델 groq": "custom",
                                          "유료 AI 사용": "아니오", "SEC 연락 이메일": "test@example.invalid"})
    assert not warnings
    assert cfg["AI 모델 groq"] == "custom"
    assert cfg["AI 공급자 순서"].startswith("openrouter")
    assert cfg["SEC 연락 이메일"] == "test@example.invalid"


def test_macro_fallback_preserves_date_and_does_not_override_fresh_equivalent():
    old = {"fred": {"이름": "물가", "값": 3.1, "기준일": "2026-09-01"}}
    fallback = news.merge_macro_cache({}, old)
    assert fallback["fred"]["cached"] is True
    assert fallback["fred"]["기준일"] == "2026-09-01"
    fresh = {"bls": {"이름": "물가", "값": 3.2, "기준일": "2026-10-01"}}
    merged = news.merge_macro_cache(fresh, old)
    assert list(merged) == ["bls"] and merged["bls"]["cached"] is False


def test_operating_diagnostics_do_not_write_or_leak_saved_values(monkeypatch):
    store = MemoryStore()
    store.settings = lambda: {}
    store.blobs = {"daily": json.dumps({"date": "2026-11-10", "summary": {}, "private_balance": 12345}),
                   "health": json.dumps({"state": "failed"})}
    before = store.blobs.copy()
    report = diagnostics.check(store)
    assert store.blobs == before
    assert "12345" not in json.dumps(report)


def test_null_portfolio_date_keeps_numeric_result(monkeypatch):
    monkeypatch.setattr("chart.build", lambda ts: {})
    monkeypatch.setattr("news._industries", lambda *a: {})
    monkeypatch.setattr("portfolio.build", lambda *a: {"total": 100})
    monkeypatch.setattr("secq.run", lambda *a: {})
    monkeypatch.setattr("investment_team.attach", lambda *a: None)
    monkeypatch.setattr(ai, "checked", lambda *a: None)
    blob = {"port": {"ai_date": None, "ai": None}}
    research.numeric_cards(blob, {"date": "2026-11-10", "holdings": [], "bands": []}, {}, None, True)
    assert blob["port"]["total"] == 100
    assert blob["port"]["ai_date"] is None
    assert next(c for c in blob["numeric_checks"] if c["n"] == "포트폴리오 진단")["ok"] is True


def test_record_and_health_agree_on_critical_failure(monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(main.notify, "send_slack", lambda *a: True)
    monkeypatch.setattr(main, "CHECKS", [{"n": "앱 데이터 저장", "ok": False, "d": "write error"}])
    outcome = main.record_run(store, "daily", main.time.time(), True, [])
    assert outcome is False
    assert json.loads(store.get_blob("perf"))["runs"][0]["ok"] is False
    assert json.loads(store.get_blob("health"))["state"] == "failed"


def test_optional_failure_remains_partial():
    checks = [{"n": n, "ok": True} for n in health.CRITICAL] + [{"n": "AI 카드", "ok": False}]
    assert health.run_outcome(True, checks, require_daily=True) == "warn"


def test_skip_and_watch_are_not_failed_daily_checks():
    assert health.build_health(kind="daily", at="t", checks=[], success="skip")["state"] == "skipped"
    assert health.build_health(kind="intraday", at="t", checks=[], success=True)["state"] == "ok"
    metrics = health.weekly_metrics([
        {"kind": "daily", "ok": True, "at": "2026-11-10T00:00:00+00:00", "took": 20},
        {"kind": "daily", "ok": "skip", "at": "2026-11-10T01:00:00+00:00", "took": 1},
    ], datetime(2026, 11, 10, 2, tzinfo=timezone.utc))
    assert metrics["total"] == 1 and metrics["success_rate_pct"] == 100


def test_record_write_error_propagates():
    class Broken(MemoryStore):
        def put_blob(self, *a):
            raise OSError("storage unavailable")
    with pytest.raises(OSError):
        appdata.add_run(Broken(), "daily", "t", True, 0, [], [])


def test_health_write_error_downgrades_already_saved_app_record(monkeypatch):
    class BrokenHealth(MemoryStore):
        def put_blob(self, key, value):
            if key == "health":
                raise OSError("health write failed")
            super().put_blob(key, value)
    store = BrokenHealth()
    monkeypatch.setattr(main, "CHECKS", [])
    assert main.record_run(store, "intraday", main.time.time(), True, []) is False
    record = json.loads(store.get_blob("perf"))["runs"][0]
    assert record["ok"] is False
    assert any(c["n"] == "운영 상태 저장" and c["ok"] is False for c in record["checks"])


def test_blob_update_never_clears_first_and_removes_old_tail():
    class Worksheet:
        row_count = 50
        def clear(self):
            raise AssertionError("must not clear live data")
        def update(self, values, *args, **kwargs):
            self.values = values
    ws = Worksheet()
    store = object.__new__(sheets.Store)
    store.gs = type("GS", (), {"worksheet": lambda self, name: ws})()
    old = pd.DataFrame([{"키": "daily", "순번": "0", "내용": "old"},
                        {"키": "daily", "순번": "1", "내용": "tail"},
                        {"키": "sim", "순번": "0", "내용": "keep"}])
    with patch.object(store, "read", return_value=old):
        store.put_blob("daily", "new")
    assert ["sim", "0", "keep"] in ws.values
    assert ["daily", "0", "new"] in ws.values
    assert ws.values[-1] == ["", "", ""]


class Response:
    def __init__(self, status, data=None):
        self.status_code, self.data, self.headers = status, data or {}, {"retry-after": "10"}
    def json(self):
        return self.data


@pytest.fixture(autouse=True)
def reset_ai():
    ai.init(None, {"AI Groq 호출 간격(초)": 0})
    yield
    ai.init(None, {})


def test_groq_413_retry_is_smaller_and_bounded(monkeypatch):
    calls = []
    def post(*a, **kw):
        calls.append(kw["json"])
        return Response(413)
    monkeypatch.setattr(ai.requests, "post", post)
    assert ai._post(ai._BY["groq"], "/chat/completions", {
        "model": "openai/gpt-oss-20b", "messages": [{"role": "user", "content": "x" * 8000}], "max_tokens": 4000
    }, "test") is None
    assert len(calls) == 2
    assert len(calls[1]["messages"][0]["content"]) < len(calls[0]["messages"][0]["content"])
    assert calls[1]["max_tokens"] <= 1500


def test_rate_limit_cools_down_without_disabling_for_entire_run(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(ai.requests, "post", lambda *a, **kw: Response(429))
    ai._post(ai._BY["groq"], "/chat/completions", {"model": "active"}, "test")
    assert "groq" not in ai._S["dead"]
    assert not ai._have(ai._BY["groq"])
    ai._S["cooldown"]["groq"] = 0
    assert ai._have(ai._BY["groq"])


def test_expired_model_not_retried_on_every_card(monkeypatch):
    calls = []
    def post(*a, **kw):
        calls.append(kw["json"]["model"])
        return Response(410)
    monkeypatch.setattr(ai.requests, "post", post)
    p = ai._BY["nvidia"]
    for _ in range(4):
        ai._post(p, "/chat/completions", {"model": "retired"}, "test")
    assert calls == ["retired"]


def test_invalid_ai_output_is_failure_not_key_health(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(ai, "_chain", lambda: [ai._BY["groq"]])
    monkeypatch.setattr(ai, "_post", lambda *a: {"choices": [{"message": {"content": "not JSON"}}]})
    assert ai.chat_json("test", "task", {}) is None
    assert ai.status()["run"] == {"failed": 1, "succeeded": 0}
