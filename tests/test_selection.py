import copy

import pandas as pd
import backtest
import config
import setups
import simtrade


def pick(**changes):
    p = dict(t='TEST', price=10., total=75., setup='눌림목', etf=False,
             edge=dict(ok=True, n=8, win=55, avg=.2, avg_r=.1),
             plan=dict(stop=9., target=12., zone_high=10., rr=2.), tags=[])
    p.update(changes)
    return p


def test_balanced_gate_keeps_positive_net_expectancy():
    p = pick()
    assert not setups.paper_gate(p)
    assert not setups.is_elite(p['edge'], 2.)  # Paper evidence does not imply the stricter elite gate.
    for key, value, reason in [('n', 7, '완료 표본 부족'), ('win', 54, '목표 도달률 미달'),
                               ('avg', 0, '비용 차감 기대값 음수')]:
        q = copy.deepcopy(p)
        q['edge'][key] = value
        assert not setups.is_elite(q['edge'], 2.)
        assert setups.paper_gate(q) == reason
    assert setups.paper_gate(pick(setup=None)) == '셋업 없음'
    assert setups.paper_gate(pick(etf=True)) == 'ETF·펀드 제외'
    strong = dict(p['edge'], avg_r=.2, robust=True)
    assert setups.is_elite(strong, 2.)
    assert not setups.is_elite(dict(strong, robust=False), 2.)
    assert not setups.is_elite(p['edge'], 1.49)


def test_long_history_provides_completed_samples(monkeypatch):
    monkeypatch.setattr(backtest, 'indicator_frame', lambda df: df)
    def result(df, i, *args):
        return dict(ret=.1, complete=i + 60 < len(df), target_hit=True, risk=.05, exit='목표')
    monkeypatch.setattr(backtest, 'simulate', result)
    def history(n):
        return pd.DataFrame({'dd':[0.] * n, 'volr':[2.] * n})
    short = setups.edge(history(280), 2., config.DEFAULTS, '돌파')
    long = setups.edge(history(1260), 2., config.DEFAULTS, '돌파')
    assert short['n'] < 8 and not short['ok']
    assert long['n'] >= 8 and setups.is_elite(long, 2.)


class Store:
    def __init__(self): self.data = {}
    def get_blob(self, key): return self.data.get(key)
    def put_blob(self, key, value): self.data[key] = value


def test_order_funnel_records_reasons_and_preserves_guards(monkeypatch):
    store = Store()
    st = simtrade.start(store, '2026-10-01', 1000)
    monkeypatch.setattr(simtrade.prices, 'download_history', lambda *a, **k: {})
    candidates = [pick(), pick(t='NOSETUP', setup=None), pick(t='ETF', etf=True),
                  pick(t='RISK', tags=['재무 주의']), pick(t='EXPENSIVE', price=2000.)]
    st = simtrade.step(store, candidates, '2026-10-02', {}, '2026-10-03')
    assert [p['t'] for p in st['pending']] == ['TEST']
    assert st['pending'][0]['qty'] == int(st['pending'][0]['qty'])
    assert st['selection']['total'] == 5 and st['selection']['planned'] == 1
    assert sum(st['selection']['excluded'].values()) == 4
    assert st['cfg']['day_loss'] == .03 and st['cfg']['day_trades'] == 3
    st = simtrade.step(store, candidates, '2026-10-02', {'regime':'bear'}, '2026-10-03')
    assert not st['pending'] and st['selection']['pause'] == '하락장'

