"""Synthetic regressions: temporal stop ordering and one-session orders."""
from datetime import datetime, timezone
import pandas as pd
import simtrade
import trading_sessions as sessions
from test_sim_limits import state, order


def position(**kw):
    return dict(dict(t='A', qty=2, entry=100., date='2026-10-01', stop=90., target=110., peak=100., half=False), **kw)


def daily(monkeypatch, rows):
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(['2026-10-02']))
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {'A': df, 'SPY': df})


def test_completed_intraday_does_not_reuse_earlier_daily_low(monkeypatch):
    store, st = state()
    p = position(qty=1, half=True, stop=100., seen_to='2026-10-02 15:55')
    st['positions'] = [p]
    simtrade.save(store, st)
    daily(monkeypatch, [dict(Open=105., High=112., Low=95., Close=111.)])
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert len(result['positions']) == 1 and not result['closed']
    assert not result['unresolved']


def test_daily_target_half_not_stopped_by_same_bar_earlier_low(monkeypatch):
    store, st = state()
    st['positions'] = [position()]
    simtrade.save(store, st)
    daily(monkeypatch, [dict(Open=105., High=112., Low=95., Close=111.)])
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert len(result['closed']) == 1 and result['positions'][0]['qty'] == 1
    again = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert len(again['closed']) == 1 and again['positions'][0]['qty'] == 1


def test_missing_tail_blocks_new_buys_then_recovers_actual_late_stop(monkeypatch):
    store, st = state()
    st['positions'] = [position(qty=1, half=True, stop=100., seen_to='2026-10-02 15:50')]
    simtrade.save(store, st)
    daily(monkeypatch, [dict(Open=105., High=112., Low=95., Close=99.)])
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={})
    assert result['unresolved'] and not result['closed'] and not result['pending']
    tail = pd.DataFrame([dict(Open=101., High=102., Low=99., Close=99.)],
                        index=pd.DatetimeIndex(['2026-10-02 15:55'], tz='America/New_York'))
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03', intraday_bars={'A': tail})
    assert not result['positions'] and len(result['closed']) == 1
    assert '15:55' in result['closed'][0]['why']


def test_expired_intraday_order_removed_without_prices():
    store, st = state()
    st['pending'] = [order('A')]
    simtrade.save(store, st)
    simtrade.intraday(store, datetime(2026, 10, 6, 15, tzinfo=timezone.utc), bars={})
    result = simtrade.load(store)
    assert not result['pending'] and not result['positions'] and result['cash'] == 1000.
    assert '유효기간 만료' in result['tickets'][0]['result']


def test_expired_daily_order_cannot_retroactively_fill(monkeypatch):
    store, st = state()
    st['pending'] = [order('A')]
    simtrade.save(store, st)
    df = pd.DataFrame([dict(Open=100., High=101., Low=99., Close=100.)], index=pd.DatetimeIndex(['2026-10-06']))
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {'A': df, 'SPY': df})
    result = simtrade.step(store, [], '2026-10-06', {}, '2026-10-07', intraday_bars={})
    assert not result['positions'] and result['cash'] == 1000.
    assert '유효기간 만료' in result['tickets'][0]['result']


def test_exchange_holidays_dst_and_early_close():
    assert sessions.next_session('2026-10-09') == '2026-10-12'
    assert sessions.next_session('2026-11-25') == '2026-11-27'
    assert sessions.next_session('2026-11-06') == '2026-11-09'
    assert sessions.close_time('2026-11-27').hour == 18
    assert sessions.completed_session('2026-11-27 12:55', '2026-11-27')
    assert not sessions.completed_session('2026-11-27 12:50', '2026-11-27')
    assert sessions.order_session(dict(signal_date='2026-11-09')) == '2026-11-10'
    assert sessions.order_session(dict(signal_date='bad')) is None
    assert sessions.order_session(dict(signal_date='2026-11-09', valid_session='2026-11-11')) is None


def test_unknown_previous_tail_cannot_be_overwritten_by_next_day_intraday():
    store, st = state()
    st['positions'] = [position(seen_to='2026-10-02 15:50', recovery_day='2026-10-02')]
    simtrade.save(store, st)
    bar = pd.DataFrame([dict(Open=105., High=106., Low=104., Close=105.)],
                       index=pd.DatetimeIndex(['2026-10-05 10:00'], tz='America/New_York'))
    simtrade.intraday(store, datetime(2026, 10, 5, 15, tzinfo=timezone.utc), bars={'A': bar})
    result = simtrade.load(store)
    assert result['positions'][0]['seen_to'] == '2026-10-02 15:50'
    assert result['unresolved']


def test_unknown_tail_does_not_receive_later_bear_stop(monkeypatch):
    store, st = state()
    st['positions'] = [position(seen_to='2026-10-02 15:50')]
    simtrade.save(store, st)
    daily(monkeypatch, [dict(Open=105., High=112., Low=95., Close=111.)])
    result = simtrade.step(store, [], '2026-10-02', {'regime': 'bear'}, '2026-10-03', intraday_bars={})
    assert result['positions'][0]['stop'] == 90.
