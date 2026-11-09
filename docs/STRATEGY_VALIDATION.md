# Strategy validation: phase 1

This change is **research-only** and does not alter production signal selection or
enable real-money trading.

## Correctness changes
- `performance._stats`: Profit Factor now equals total positive returns divided
  by absolute total negative returns. It previously divided the average win by
  the average loss and could show PF > 1 while the aggregate trade returns lost money.
- `setups.edge`: a validation holdout smaller than `HOLDOUT_MIN` no longer
  counts as a pass. `robust` is false for insufficient holdout evidence.

## Comparable entry-strategy experiment
Run from the repository root:

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_strategy_validation.py' -v
python -m validation.compare_strategies --tickers 100 --years 3
```

This creates `data/strategy_comparison.json`. It evaluates breakout,
pullback and oversold-reversal signals with the **same**
`backtest.simulate` exit engine, 20 trading-day maximum holding period,
market regime filter and assumed 0.35% cost on each side.
The output includes per-trade returns and aggregate trade statistics.

**Not a verified profitable strategy.** The experiment currently selects
today's active, liquid listed shares and replays past prices; therefore it
has survivorship / current-universe selection bias. It does not use
historical point-in-time fundamentals, model simultaneous cash limits,
or reproduce the production limit-fill logic. It does not report CAGR
or MDD because returns here are not a portfolio equity curve.

## Next phase before changing production buy signals
1. Snapshot historical point-in-time universe including delisted securities.
2. Share one event-driven execution model across backtest and paper trading.
3. Enforce cash, position count, risk and daily portfolio accounting.
4. Add walk-forward validation, purged overlapping trade windows,
   data completeness checks, and cost stress tests.
5. Compare strategy and SPY risk-adjusted returns on independent periods.
6. Promote a strategy only after forward paper-trading evidence.

Do not merge based on a favorable exploratory result alone.


## Phase 2: shared fills, capital-accounted results and policy

- `execution_rules.py` contains common limit entry / conservative stop-first
  OHLC exit decisions. Research and existing paper simulation now call these
  primitives. This does not make 5-minute and daily bars identical; temporal
  resolution, missed bars, trailing behavior and fill sequencing still differ.
- `validation/portfolio.py` performs daily mark-to-market using finite cash,
  integer shares, position count, cost assumptions and a shared fill model.
- `python -m validation.run_portfolio --tickers 20 --years 2` downloads
  actual Yahoo historical bars, computes strategy CAGR, MDD, Sharpe and
  matched SPY returns. Output: `data/portfolio_comparison.json`.
- `python -m validation.run_rolling --tickers 20 --folds 3 --months 12`
  computes chronological evaluation-fold reports. Output:
  `data/rolling_comparison.json`. No parameter training is performed;
  calling these windows a fully independent OOS test would be inaccurate.
- `validation/promotion.py` assesses strategy evidence and always fails
  closed unless independent tests and historical-universe integrity have
  been independently verified.
- `strategy_policy.py` optionally gates **paper-trading candidates only**.
  `simtrade.DEFAULT["validated_strategy_mode"]` is `False`; existing
  portfolio behavior is preserved. Setting it to exact boolean `True`
  without a valid independently approved, unexpired JSON policy excludes
  all new paper buys, by design. Never enable this before supplying a
  verified policy. No auto-generated example policy is trusted.
- No real-money order endpoint is introduced; production alerts are NOT
  automatically rewritten by backtest results.

## Evidence from first 2026-11-09 research CI trial

The initial 20 current-high-volume-ticker, two-year historical-price sample
reported total portfolio returns: breakout +8.63%, pullback -3.82%,
oversold -15.39%; SPY +27.28%. These are **biased exploratory results**,
not a profit claim, not validated historical investable universe,
and not a basis to turn on strategy policy.

## Remaining blockers before any production strategy promotion

1. Point-in-time historical universe with delisted stocks and corporate actions.
2. Historical point-in-time fundamental data or explicit technical-only strategy.
3. Venue-specific fees, calibrated spreads and intrabar fill audit.
4. True purged/embargoed walk-forward tuning/test separation and adequate sample.
5. A verified, immutable OOS performance record with an independent audit.
6. Risk parity/capacity/concentration analysis and sustained forward paper results.

## Latest corrected research sample (same date; after cash-order temporal fix)

The improved model freezes capital/slots at the preceding close, so today's
exit proceeds are not used to finance orders at today's open. Its subsequent
20-current-ticker, ~2-year run reported:
- Breakout: +8.55% total, CAGR +4.19%, MDD -14.78%, PF 1.275, 64 closed trades.
- Pullback: +0.27% total, CAGR +0.13%, MDD -11.04%, PF 1.020, 112 closed trades.
- Oversold: -15.14% total, CAGR -7.88%, MDD -22.64%, PF 0.488, 51 closed trades.
- SPY: +27.28% total over the same price history.

Rolling 3x12-month research windows: breakout beat SPY in 1 window;
pullback in 0; oversold in 0. All strategy promotions remain denied.

See GitHub Actions: https://github.com/skih4741-png/us-stock-alert/actions/runs/42576462168

## Phase 3: causality, price provenance, and P&L diagnostics (2026-11-09)

- Portfolio opening orders use the *prior close's* confirmed SPY market
  regime, never the close of the current order date.
- A close-based trailing/time exit is scheduled for the *next session open*.
- Candidate ranking uses the *prior close's* 63-day momentum and dollar volume
  instead of alphabetical ticker order.
- Entries enforce the prevailing minimum historical dollar-liquidity filter.
- Research acquisition uses one Yahoo OHLCV snapshot for both portfolio and
  chronological windows and computes a SHA256 digest and the selected symbols.
- Active-listing sampling chooses a fixed N after verifying enough signal
  warmup and full evaluation-window history. The skipped candidate symbols and
  reasons are recorded. This is still **survivorship-biased**.
- Missing coverage for the final set fails the research job rather than
  silently altering the comparison. Supplied as-of CSV membership
  `ticker,start_date,end_date` is enforced at each signal date, but
  completeness and delisted stock OHLCV must be externally verified.
- `data/strategy_diagnostics.md` explains realized exit reasons, market
  regime profit/loss, ticker attribution and cost stress.
- Automatic strategy promotion remains disabled unless independent OOS
  and historical-universe integrity are verified.

Run the single-snapshot workflow:
```bash
python -m validation.research_pipeline --tickers 20 --years 2 --folds 3 --months 12
```

Latest comparable-history and signal-day-liquidity research sample:
- Breakout: +9.64% 2-year return, MDD -10.83%, PF 1.340.
- Pullback: -21.90%, MDD -24.31%, PF 0.655.
- Oversold: -15.69%, MDD -21.38%, PF 0.493.
- SPY: +27.28% over the sample.
- None of the 3 strategies beat SPY in any of the three 12-month windows.

These numbers replace earlier draft-run examples **only for this
specific recorded ticker snapshot**, not as an independent performance
estimate. Results change with sample composition and can still be
biased by active-universe selection and adjusted-data execution
assumptions. Do not activate any strategy from these figures.

Latest research result:
https://github.com/skih4741-png/us-stock-alert/actions/runs/42580210128
