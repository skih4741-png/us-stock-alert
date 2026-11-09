"""Policy publisher: deploy a *verified* candidate set to paper/alert filters.

Never auto-assert independence or data provenance. An independent audit
manifest and forward-paper evidence MUST be supplied by the operator.
No live broker orders are made. Signature key belongs to a protected secret.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
import os
from pathlib import Path

from strategy_policy import sign_policy
from validation.promotion import assess_strategy


def compose_policy(audit: dict, oos: dict, forward: dict, *, today: date,
                   secret: str) -> dict:
    if not isinstance(audit, dict) or audit.get("independent_oos_verified") is not True:
        raise ValueError("Missing independently audited OOS evidence")
    if audit.get("historical_universe_verified") is not True:
        raise ValueError("Delisted-universe coverage has not been externally verified")
    digest = audit.get("source_dataset_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or any(x not in "0123456789abcdef" for x in digest.lower()):
        raise ValueError("Missing SHA256 provenance")
    if audit.get("auditor") in (None, "", "self"):
        raise ValueError("Independent auditor name is required")
    if forward.get("verified") is not True or float(forward.get("days", 0)) < 90:
        raise ValueError("At least 90 days independently verified forward paper trading required")
    allowed = []
    for name, metrics in oos.get("metrics", {}).items():
        if name not in ("breakout", "pullback", "oversold"):
            continue
        approval = assess_strategy(
            metrics, independent_oos=True, verified_universe=True)
        forward_metrics = forward.get("strategies", {}).get(name, {})
        if (approval["eligible"]
                and float(forward_metrics.get("net_pnl_usd", 0)) > 0
                and int(forward_metrics.get("closed_trades", 0)) >= 30):
            allowed.append(name)
    if not allowed:
        raise ValueError("No strategy passed OOS and forward-paper approval")
    payload = {
        "policy_version": 1,
        "issued_on": today.isoformat(),
        "valid_until": (today + timedelta(days=14)).isoformat(),
        "independent_oos_verified": True,
        "historical_universe_verified": True,
        "forward_paper_verified": True,
        "source_dataset_sha256": digest,
        "auditor": audit["auditor"],
        "approved_strategies": sorted(allowed),
        "scope": "paper_and_opt_in_alerts_only",
    }
    return sign_policy(payload, secret)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--oos", type=Path, required=True)
    parser.add_argument("--forward", type=Path, required=True)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("data/validated_strategy_policy.json"))
    args = parser.parse_args()
    key = os.environ.get("STRATEGY_POLICY_HMAC_KEY", "")
    policy = compose_policy(
        json.loads(args.audit.read_text(encoding="utf-8")),
        json.loads(args.oos.read_text(encoding="utf-8")),
        json.loads(args.forward.read_text(encoding="utf-8")),
        today=date.today(), secret=key,
    )
    output = json.dumps(policy, ensure_ascii=False, sort_keys=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8")
    if args.publish:
        # Explicit operator action: publish only after evidence review.
        from sheets import Store
        store = Store()
        store.put_blob("validated_strategy_policy", output)
        if store.get_blob("validated_strategy_policy") != output:
            raise RuntimeError("Strategy policy write verification failed")
    print("Approved for paper/opt-in alerts only:", policy["approved_strategies"])
    print("Policy expires:", policy["valid_until"])
    print("Published:", bool(args.publish))


if __name__ == "__main__":
    main()
