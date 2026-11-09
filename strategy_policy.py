"""Optional fail-closed paper-trading strategy policy.

This module never trades or approves a strategy from raw backtest performance.
Only an explicitly created, vetted JSON policy may enable named research setups.
DEFAULT OFF: existing paper and live recommendation paths are unchanged.
"""
from __future__ import annotations

import json
import os
import hmac
import hashlib
from datetime import date
from pathlib import Path

POLICY_FILE = Path(__file__).parent / "data" / "validated_strategy_policy.json"
SETUPS = {"돌파": "breakout", "눌림목": "pullback", "과매도 반등": "oversold"}


def sign_policy(payload: dict, secret: str) -> dict:
    """Sign an independently approved policy; never create evidence here."""
    if not secret or len(secret) < 32:
        raise ValueError("signing secret must contain >= 32 characters")
    data = {k: v for k, v in payload.items() if k != "signature"}
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {**data, "signature": sig}


def valid_signature(payload: dict, secret: str | None = None) -> bool:
    secret = secret if secret is not None else os.environ.get("STRATEGY_POLICY_HMAC_KEY", "")
    if len(secret) < 32 or not isinstance(payload.get("signature"), str):
        return False
    expected = sign_policy(payload, secret)["signature"]
    return hmac.compare_digest(expected, payload["signature"])


def allowed(setup: str | None, *, enabled: bool = False,
            policy_path: Path = POLICY_FILE, today: date | None = None,
            policy_text: str | None = None) -> tuple[bool, str]:
    if not enabled:
        return True, "strategy policy disabled (legacy mode)"
    # In enabled mode, missing or tampered policy MUST NEVER approve trading.
    try:
        p = json.loads(policy_text if policy_text is not None else
                       Path(policy_path).read_text(encoding="utf-8"))
        if not isinstance(p, dict) or not valid_signature(p):
            return False, "전략 정책 서명 미확인"
        t = today or date.today()
        if p.get("policy_version") != 1 or p.get("independent_oos_verified") is not True:
            return False, "독립 검증된 정책 없음"
        if p.get("historical_universe_verified") is not True:
            return False, "상장폐지 포함 과거 종목 검증 없음"
        if p.get("forward_paper_verified") is not True:
            return False, "장기 모의매매 검증 없음"
        if not p.get("source_dataset_sha256") or len(str(p["source_dataset_sha256"])) != 64:
            return False, "검증 데이터 지문 누락"
        issued = date.fromisoformat(p["issued_on"])
        expiry = date.fromisoformat(p["valid_until"])
        if issued > t or expiry < t or (expiry - issued).days > 31:
            return False, "정책 발행일·유효기간 오류"
        name = SETUPS.get(setup)
        if name is None or name not in p.get("approved_strategies", []):
            return False, "전략 검증 통과 기록 없음"
        return True, "서명된 검증 정책 허용 (모의매매/선택적 알림)"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False, "유효한 전략 정책 파일 없음"
