from datetime import datetime, timezone

import pandas as pd
import simtrade


class Store:
    def __init__(self): self.data = {}
    def get_blob(self, k): return self.data.get(k)
    def put_blob(self, k, v): self.data[k] = v


def state():
    store = Store()
    st = simtrade.start(store, '2026-10-01', 1000)
    return store, st


def order(t):
    return dict(t=t, signal_date='2026-10-01', qty=1, limit=100., skip_above=110., stop=50., target=120., why='시험', setup='돌파')


def candle(low=99.):
    return pd.DataFrame([dict(Open=100., High=101., Low=low, Close=100.)],
                        index=pd.DatetimeIndex(['2026-10-02 10:00'], tz='America/New_York'))


def test_daily_loss_latches_and_resets_next_day():
    _, st = state()
    st['closed'] = [dict(exit_date='2026-10-02', pnl=-30.)]
    assert simtrade.day_risk(st, '2026-10-02')['blocked']
    st['closed'].append(dict(exit_date='2026-10-02', pnl=40.))
    assert simtrade.day_risk(st, '2026-10-02')['blocked']
    assert not simtrade.day_risk(st, '2026-10-05')['blocked']


def test_daily_trade_limit_migrates_old_ledger():
    _, st = state()
    st['cfg'].pop('day_trades')
    st['tickets'] = [dict(day='2026-10-02', result='체결') for _ in range(3)]
    assert simtrade.day_risk(st, '2026-10-02')['blocked']
    assert not simtrade.day_risk(st, '2026-10-05')['blocked']


def test_intraday_loss_blocks_next_entry_and_replay_is_idempotent():
    store, st = state()
    st['cfg']['risk'] = .06  # 일일 3% 차단을 따로 검증하기 위한 진입 위험 설정
    st['pending'] = [order('A'), order('B')]
    simtrade.save(store, st)
    now = datetime(2026, 10, 2, 15, tzinfo=timezone.utc)
    bars = {'A': candle(40), 'B': candle()}
    simtrade.intraday(store, now, bars=bars)
    result = simtrade.load(store)
    assert len(result['closed']) == 1
    assert not result['positions'] and not result['pending']
    assert simtrade.day_risk(result, '2026-10-02')['fills'] == 1
    assert '하루 확정손실' in result['tickets'][1]['result']
    simtrade.intraday(store, now, bars=bars)
    assert simtrade.load(store) == result


def test_intraday_count_limit_still_allows_protective_sale():
    store, st = state()
    st['tickets'] = [dict(t=str(i), signal='2026-10-01', side='매수', day='2026-10-02', result='체결') for i in range(3)]
    st['positions'] = [dict(t='OLD', qty=1, entry=100., date='2026-10-01', stop=95., target=120., peak=100., half=False)]
    st['pending'] = [order('NEW')]
    simtrade.save(store, st)
    simtrade.intraday(store, datetime(2026, 10, 2, 15, tzinfo=timezone.utc), bars={'OLD': candle(90), 'NEW': candle()})
    result = simtrade.load(store)
    assert len(result['closed']) == 1 and not result['positions']
    assert '횟수 한도' in result['tickets'][-1]['result']


def test_review_partial_exits_count_as_one_and_legacy_r_is_unknown():
    _, st = state()
    common = dict(t='A', date='2026-10-01', exit_date='2026-10-02', trade_id='A1', risk_per_share=5., signal_edge={'ok': True})
    st['closed'] = [dict(common, qty=1, pnl=10.), dict(common, qty=1, pnl=-2.)]
    r = simtrade.review(st)
    assert r['n'] == 1 and r['avg_r'] == .8
    st['positions'] = [dict(trade_id='A1')]
    assert simtrade.review(st)['n'] == 0
    st['positions'] = []
    for c in st['closed']: c.pop('risk_per_share')
    assert simtrade.review(st)['avg_r'] is None


def test_daily_fallback_honors_count_limit(monkeypatch):
    store, st = state()
    st['pending'] = [order('A')]
    st['tickets'] = [dict(t=str(i), signal='2026-10-01', side='매수', day='2026-10-02', result='체결') for i in range(3)]
    simtrade.save(store, st)
    df = candle(); df.index = pd.DatetimeIndex(['2026-10-02'])
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **kw: {'A': df, 'SPY': df})
    result = simtrade.step(store, [], '2026-10-02', {}, '2026-10-03T07:00')
    assert not result['positions'] and result['cash'] == 1000.
    assert '횟수 한도' in result['tickets'][-1]['result']


def test_intraday_does_not_fill_unfinished_bar():
    store, st = state()
    st['pending'] = [order('A')]
    simtrade.save(store, st)
    simtrade.intraday(store, datetime(2026, 10, 2, 14, 2, tzinfo=timezone.utc), bars={'A': candle()})
    result = simtrade.load(store)
    assert not result['positions'] and len(result['pending']) == 1


def test_buy_candle_high_is_not_assumed_to_follow_entry():
    store, st = state()
    st['cfg']['risk'] = .06  # 목표의 시간 순서를 검증하는 고정 주문
    st['pending'] = [order('A')]
    simtrade.save(store, st)
    df = candle(); df['High'] = 150.
    simtrade.intraday(store, datetime(2026, 10, 2, 15, tzinfo=timezone.utc), bars={'A': df})
    result = simtrade.load(store)
    assert len(result['positions']) == 1 and not result['closed']
