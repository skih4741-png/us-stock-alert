"""Human-readable research diagnostics from one auditable price snapshot."""


def pct(value):
    return "N/A" if value is None else f"{value:+.2f}%"


def render(portfolio: dict, rolling: dict) -> str:
    meta = portfolio.get("meta", {})
    lines = [
        "# Strategy comparison — research only", "",
        "## Dataset",
        f"- Source: {meta.get('source', 'unknown')}",
        f"- Requested/validated tickers: {len(meta.get('selected_tickers', []))}/{meta.get('downloaded_tickers', 0)}",
        f"- Snapshot SHA256: {meta.get('price_snapshot_sha256', 'unknown')}",
        f"- Verified historical universe: {meta.get('historical_universe_verified', False)}",
        "- No production strategy is approved by this report.", "",
        "## Portfolio results", "",
        "| Strategy | Return | CAGR | MDD | SPY excess | PF | Trades |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in portfolio.get("strategies", {}).items():
        m = item["metrics"]
        pf = m.get("profit_factor")
        lines.append(
            f"| {name} | {pct(m.get('total_return_pct'))} | {pct(m.get('cagr_pct'))}"
            f" | {pct(m.get('mdd_pct'))} | {pct(m.get('excess_return_pct'))}"
            f" | {pf if pf is not None else 'N/A'} | {m.get('closed_trades')} |"
        )
    lines.extend(["", "## Exit reasons and market regimes", ""])
    for name, dims in portfolio.get("trade_attribution", {}).items():
        lines.append(f"### {name}")
        for reason, vals in sorted(dims.get("reason", {}).items(),
                                    key=lambda x: x[1]["realized_pnl_usd"]):
            lines.append(
                f"- {reason}: {vals['trades']} trades, P&L "
                f"USD {vals['realized_pnl_usd']:+,.2f}, win {vals['win_rate_pct']:.1f}%"
            )
        for regime, vals in sorted(dims.get("regime", {}).items()):
            lines.append(
                f"- Regime {regime}: {vals['trades']} closed, "
                f"USD {vals['realized_pnl_usd']:+,.2f}"
            )
        lines.append("")
    lines.extend(["## Cost-stress scenarios", ""])
    for name, item in portfolio.get("cost_stress", {}).items():
        cases = item.get("scenarios", {})
        segments = [f"{factor}x: {pct(val.get('total_return_pct'))}"
                    for factor, val in sorted(cases.items(), key=lambda kv: float(kv[0]))]
        lines.append(f"- {name}: " + ", ".join(segments))
    lines.extend(["", "## Chronological windows", ""])
    for name, item in rolling.get("summary", {}).items():
        lines.append(
            f"- {name}: {item.get('beat_spy_folds', 0)}/{item.get('folds', 0)} windows beat SPY; "
            f"approved: {rolling.get('promotion_gate', {}).get(name, {}).get('eligible', False)}"
        )
    lines.extend([
        "", "## Limitations",
        "- Current listings may exclude historical delistings and introduce survivorship bias.",
        "- OHLC bars cannot establish exact order of target and stop touches.",
        "- Costs are assumptions and are not venue-specific executions.",
        "- Open P&L is outside closed-trade attribution.",
        "- No independent parameter-selection OOS certification or real-money approval.",
    ])
    return chr(10).join(lines) + chr(10)
