"""엣지 통계: 목표 도달과 양의 수익 구분, 미완료 표본 제외."""
import pandas as pd
import backtest
import config
import setups


def bars(n=65):
    return pd.DataFrame([dict(open=100., high=101., low=99., close=100., ma50=95., low20=95., ma20=90.) for _ in range(n)])


def test_profitable_expiry_is_not_target_hit():
    o = bars()
    o.loc[60, 'close'] = 101.
    r = backtest.simulate(o, 0, 2., config.DEFAULTS)
    assert r['ret'] > 0 and r['complete'] and not r['target_hit']


def test_recent_expiry_is_incomplete():
    assert not backtest.simulate(bars(5), 0, 2., config.DEFAULTS)['complete']


def test_same_bar_stop_and_target_uses_stop_first():
    o = bars()
    o.loc[1, ['low', 'high']] = [90., 120.]
    r = backtest.simulate(o, 0, 2., config.DEFAULTS)
    assert r['exit'] == '손절' and not r['target_hit'] and r['ret'] < 0


def test_edge_counts_targets_and_costs(monkeypatch):
    o = pd.DataFrame({'dd': [0.] * 300, 'volr': [2.] * 300})
    monkeypatch.setattr(backtest, 'indicator_frame', lambda df: o)
    monkeypatch.setattr(backtest, 'simulate', lambda *a: dict(ret=.001, complete=True, target_hit=False, risk=.05, exit='기간 만료'))
    r = setups.edge(o, 2., {}, '돌파')
    assert r['n'] >= 8 and r['win'] == 0 and r['avg'] < 0 and not r['ok']
    monkeypatch.setattr(backtest, 'simulate', lambda *a: dict(ret=.1, complete=False, target_hit=True, risk=.05))
    assert setups.edge(o, 2., {}, '돌파')['n'] == 0


def test_closed_trade_keeps_entry_edge():
    import simtrade
    state = dict(cash=0., closed=[], log=[], cfg=dict(simtrade.DEFAULT), equity=[])
    edge = dict(win=70, n=20, avg_r=.4)
    position = dict(t='TEST', qty=1, entry=10., date='2026-10-01', setup='돌파', signal_edge=edge)
    simtrade._close(state, position, '2026-10-02', 11., '목표')
    assert state['closed'][0]['signal_edge'] == edge
    assert state['closed'][0]['setup'] == '돌파'
