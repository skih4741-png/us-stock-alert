"""Valuation must describe the ledger and exact market date it claims."""
import copy
import pandas as pd
import pytest
import simtrade
from test_sim_limits import state


def held():
    return dict(t='A', qty=4, entry=100., date='2026-10-01', stop=90., target=120., peak=100., half=False)


def frame(day='2026-10-02', close=105.):
    return pd.DataFrame([dict(Open=105., High=106., Low=104., Close=close)], index=pd.DatetimeIndex([day]))


@pytest.mark.parametrize('hist', [{}, {'A': frame('2026-10-01')}, {'A': frame(close=float('nan'))}])
def test_incomplete_position_prices_do_not_write_cash_only_equity_or_month_stop(monkeypatch, hist):
    store, st = state()
    st['cash'] = 599.
    st['positions'] = [held()]
    before = copy.deepcopy(st['equity'])
    simtrade.save(store, st)
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: hist)
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert result['equity'] == before
    assert result['month_stops'] == []
    assert result['checked'] == st.get('checked')
    assert result['unresolved'] and not result['pending']


def test_older_report_cannot_use_future_sale_cash(monkeypatch):
    store, st = state()
    st['cash'] = 950.
    st['closed'] = [dict(t='A', date='2026-10-01', exit_date='2026-10-06', qty=1, entry=100., exit=50., pnl=-50., ret=-50.)]
    before = copy.deepcopy(st['equity'])
    simtrade.save(store, st)
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {'SPY': frame()})
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-07', intraday_bars={})
    assert result['equity'] == before
    assert result['cash'] == 950. and len(result['closed']) == 1
    assert result['unresolved'] and not result['pending']


def test_good_exact_date_values_all_positions(monkeypatch):
    store, st = state()
    st['cash'] = 599.
    st['positions'] = [held()]
    simtrade.save(store, st)
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {'A': frame()})
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert result['equity'][-1][1] == 1019.


def test_exact_date_retry_recovers_without_false_month_latch(monkeypatch):
    store, st = state()
    st['cash'] = 599.
    st['positions'] = [held()]
    st['equity'] = [['2026-10-01', 1000., None]]
    simtrade.save(store, st)
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {})
    bad = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert not bad['valuation']['ok'] and not bad['month_stops']
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {'A': frame()})
    good = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert good['valuation']['ok'] and not good['unresolved']
    assert good['equity'][-1][1] == 1019.


def test_realized_reconstruction_groups_exit_days_and_excludes_exact_trade():
    from valuation_audit import realized_curve
    _, st = state()
    st['closed'] = [dict(t='A', date='2026-10-01', exit_date='2026-10-02', pnl=-20.),
                    dict(t='B', date='2026-10-01', exit_date='2026-10-02', pnl=10.),
                    dict(t='A', date='2026-10-03', exit_date='2026-10-05', pnl=-5.)]
    r = realized_curve(st)
    assert r['curve'] == [['2026-10-01',1000.],['2026-10-02',990.],['2026-10-05',985.]]
    assert r['mdd'] == pytest.approx(-1.5)
    r = realized_curve(st, excluded={('A','2026-10-01')})
    assert r['pnl'] == 5. and r['trades'] == 2


def test_current_gate_rejects_missing_evidence_but_not_all_weak_trends():
    import setups
    legacy = dict(t='SYNTH', total=96., trend5=[['trend',False]]*5, plan=dict(rr=2.))
    assert setups.paper_gate(legacy) == '셋업 없음'
    evidence = dict(legacy, setup='과매도 반등', edge=dict(n=100,win=60,avg=2.))
    assert setups.paper_gate(evidence) == ''  # trend score is currently a ranking input, not a hard gate
