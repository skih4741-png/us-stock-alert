"""Optional fail-closed paper-trading strategy policy.

This module never trades or approves a strategy from raw backtest performance.
Only an explicitly created, vetted JSON policy may enable named research setups.
DEFAULT OFF: existing paper and live recommendation paths are unchanged.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

POLICY_FILE = Path(__file__).parent / "data" / "validated_strategy_policy.json"
SETUPS = {"돌파": "breakout", "눌림목": "pullback", "과매도 반등": "oversold"}


def allowed(setup: str | None, *, enabled: bool = False,
            policy_path: Path = POLICY_FILE, today: date | None = None) -> tuple[bool, str]:
    if not enabled:
        return True, "strategy policy disabled (legacy mode)"
    # In enabled mode, missing or corrupt policy must NEVER be an approval.
    try:
        p = json.loads(Path(policy_path).read_text(encoding="utf-8"))
        t = today or date.today()
        if p.get("policy_version") != 1 or p.get("independent_oos_verified") is not True:
            return False, "독립 검증된 정책 없음"
        if p.get("historical_universe_verified") is not True:
            return False, "상장폐지 포함 과거 종목 검증 없음"
        if date.fromisoformat(p["valid_until"]) < t:
            return False, "정책 유효기간 만료"
        name = SETUPS.get(setup)
        if name is None or name not in p.get("approved_strategies", []):
            return False, "전략 검증 통과 기록 없음"
        return True, "검증된 정책 허용 (모의매매에만 적용)"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False, "유효한 전략 정책 파일 없음"
