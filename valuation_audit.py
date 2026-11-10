"""Read-only reconstruction from recorded exits; never a mark-to-market backtest."""
from collections import defaultdict
from decimal import Decimal


def drawdown(values):
    peak = None
    worst = Decimal(0)
    for value in values:
        value = Decimal(str(value))
        peak = value if peak is None else max(peak, value)
        if peak > 0:
            worst = min(worst, value / peak - 1)
    return float(worst * 100)


def realized_curve(state, excluded=()):
    """Exclude exact (ticker, entry date) identities, keeping other recorded trades."""
    budget = Decimal(str(state['cfg']['budget']))
    changes = defaultdict(Decimal)
    count = 0
    for trade in state.get('closed', []):
        if (trade['t'], trade['date']) in excluded:
            continue
        changes[trade['exit_date']] += Decimal(str(trade['pnl']))
        count += 1
    capital = budget
    curve = [[state['start'], float(capital)]]
    for day, change in sorted(changes.items()):
        if day < state['start']:
            raise ValueError('Exit predates ledger start; opening capital cannot be established')
        capital += change
        if curve[-1][0] == day:
            curve[-1][1] = float(capital)
        else:
            curve.append([day, float(capital)])
    # The budget anchor participates even if a same-day exit replaces its row.
    return dict(kind='realized_only', trades=count, curve=curve, pnl=float(capital-budget),
                ret=float((capital/budget-1)*100),
                mdd=drawdown([budget]+[v for _,v in curve]),
                limitations=['No unrealized gains, entry fees before exit, or intraday extremes',
                             'Excluded trades do not cause replacement trades or re-sizing'])
