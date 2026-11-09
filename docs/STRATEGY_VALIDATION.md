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
