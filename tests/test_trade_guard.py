import copy
from datetime import datetime, timezone

import appdata
import broker_state
import investment_team
import kis
import kisbridge
import simtrade
import trade_guard


class Store:
    def __init__(self): self.data = {}
    def get_blob(self, key): return self.data.get(key)
    def put_blob(self, key, value): self.data[key] = value
    def append(self, *args): pass


def order(t='A'):
    return dict(t=t, qty=1, limit=10., stop=9., target=12., skip_above=11., signal_date='2026-10-01',why='test')


def test_shared_guard_rejects_missing_cash_fractional_risk_and_limits():
    account=dict(verified=True, cash=100., equity=1000., held=[],positions=0,buys=0)
    cfg=dict(simtrade.DEFAULT)
    assert trade_guard.validate_buy(order(),account,cfg)['ok']
    for change, message in [(dict(cash=None),'잔고'),(dict(buys=3),'횟수'),(dict(held=['A']),'이미 보유'),
                            (dict(verified=False),'계좌'),(dict(blocked=True),'손실'),(dict(cash=10.),'비용 포함')]:
        r=trade_guard.validate_buy(order(),dict(account,**change),cfg)
        assert not r['ok'] and any(message in s for s in r['reasons'])
    assert not trade_guard.validate_buy(dict(order(),qty=1.5),account,cfg)['ok']
    assert not trade_guard.validate_buy(dict(order(),qty=40),dict(account,cash=1000.),cfg)['ok']
    assert not trade_guard.validate_buy(dict(order(),stop=float('nan')),account,cfg)['ok']


def test_reconcile_partial_target_moves_stop_only_after_confirmed_fill():
    st=dict(pos={'A':dict(entry=10.,stop=9.,half=False)},orders=[dict(date='2026-10-02',broker_date='20261002',
        t='A',side='매도',qty=5,price=12.,entry=10.,exit_kind='target',status='주문 접수',odno='1')])
    broker_state.reconcile(st,[], '2026-10-02')
    assert not st['pos']['A']['half']
    fills=[dict(order_date='20261002',odno='1',t='A',side='매도',qty=5,filled=2,price=12.)]
    broker_state.reconcile(st,fills,'2026-10-02')
    assert st['pos']['A']['half'] and st['pos']['A']['stop']==10.
    assert st['orders'][0]['status']=='부분체결'
    assert broker_state.outstanding(st['orders'][0])==3
    pnl=st['orders'][0]['realized']
    broker_state.reconcile(st,fills,'2026-10-02')
    assert st['orders'][0]['realized']==pnl  # 재조회에 손익을 더하지 않음


def test_broker_loss_latches_and_unknown_external_sales_block_buys():
    cfg=dict(simtrade.DEFAULT)
    st=dict(orders=[dict(date='2026-10-02',side='매도',t='A',qty=1,price=8,status='체결 완료',realized=-31.)],
            reconcile=dict(ok=True),equity={'2026-10-01':1000.})
    a=broker_state.account(st,{'holdings':[]},1000.,'2026-10-02',cfg)
    assert a['blocked'] and a['loss_limit']==30.
    st['orders'][0]['realized']=5.
    assert broker_state.account(st,{'holdings':[]},1000.,'2026-10-02',cfg)['blocked']
    broker_state.reconcile(st,[dict(t='OUTSIDE',side='매도',filled=1,odno='x',order_date='20261002')],'2026-10-02')
    assert not broker_state.account(st,{'holdings':[]},1000.,'2026-10-02',cfg)['verified']


def harness(monkeypatch, fail=False, holdings=None):
    store=Store()
    st=simtrade.start(store,'2026-10-01',1000,max_pos=5)
    st['pending']=[order()]
    simtrade.save(store,st)
    class Client:
        calls=[]
        def __init__(self,*a): pass
        def balance(self): return dict(holdings=holdings or [],complete=True)
        def fills(self,*a): return []
        def buying_power(self,*a): return 1000.
        def order(self,*args):
            self.calls.append(args)
            # API 호출 전에 선기록이 저장되어 있어야 함
            assert '전송 중' in store.get_blob('kis')
            if fail: raise TimeoutError()
            return 'broker-id'
    monkeypatch.setattr(kisbridge.kis,'configured',lambda:(True,''))
    monkeypatch.setattr(kisbridge.kis,'Client',Client)
    monkeypatch.setattr(kisbridge.kis,'exchange',lambda *a:'NASD')
    monkeypatch.setattr(kisbridge.prices,'last_price_intraday',lambda ts:{t:{'price':10.} for t in ts})
    monkeypatch.setattr(kisbridge.notify,'send_slack',lambda *a,**k:None)
    return store,Client


def test_broker_submission_is_not_fill_and_replay_does_not_resubmit(monkeypatch):
    store,C=harness(monkeypatch)
    now=datetime(2026,10,2,14,tzinfo=timezone.utc)
    result=kisbridge.run(store,now)
    assert len(C.calls)==1 and result['orders'][0]['status']=='주문 접수'
    assert result['orders'][0]['filled']==0
    kisbridge.run(store,now)
    assert len(C.calls)==1


def test_timeout_blocks_duplicate_submission_and_new_buys(monkeypatch):
    store,C=harness(monkeypatch,fail=True)
    now=datetime(2026,10,2,14,tzinfo=timezone.utc)
    result=kisbridge.run(store,now)
    assert result['orders'][0]['status']=='확인 필요'
    state=simtrade.load(store);state['pending'].append(order('B'));simtrade.save(store,state)
    kisbridge.run(store,now)
    assert len(C.calls)==1


def test_broker_caps_submissions_at_three_even_before_fills(monkeypatch):
    store,C=harness(monkeypatch)
    state=simtrade.load(store);state['pending']=[order(t) for t in ['A','B','C','D']];simtrade.save(store,state)
    result=kisbridge.run(store,datetime(2026,10,2,14,tzinfo=timezone.utc))
    assert len(C.calls)==3
    assert '횟수 한도' in result['orders'][-1]['status']


def test_protective_sell_works_during_buy_block_and_reserves_pending_qty(monkeypatch):
    store,C=harness(monkeypatch,holdings=[dict(t='OLD',qty=4,avg=11.,now=10.,excg='NASD')])
    import json
    store.put_blob('kis',json.dumps(dict(pos={'OLD':dict(entry=11.,stop=10.5,target=14.,half=False)},
                                       orders=[dict(t='OTHER',date='2026-10-02',side='매수',qty=1,price=10.,status='확인 필요')])) )
    now=datetime(2026,10,2,14,tzinfo=timezone.utc)
    kisbridge.run(store,now);kisbridge.run(store,now)
    assert len(C.calls)==1 and C.calls[0][:3]==('sell','OLD',4)


def test_team_sources_and_shadow_comparison_are_not_votes():
    facts={'재무':{'매출':100}}
    result=investment_team.normalize({'views':[dict(name='가치',stance='긍정',reason='ok',evidence_keys=['허구'])]},facts,'2026-10-01')
    assert len(result['views'])==4 and result['views'][0]['stance']=='자료 부족'
    store=Store();st=simtrade.start(store,'2026-10-01',1000)
    st['closed']=[dict(t='A',date='2026-10-01',exit_date='2026-10-02',qty=1,entry=10.,exit=9.,pnl=-1.,
                      trade_id='A1',risk_per_share=1.,entry_context={'date':'2026-10-01','team':dict(date='2026-10-01',views=[{}]),'shadow_avoid':True})]
    c=simtrade.review(st)['team_comparison']
    assert c['actual_pnl']==-1. and c['kept_pnl']==0. and c['avoided_losses']==1.
    st['closed'][0]['entry_context']['team']['date']='2026-09-30'
    assert simtrade.review(st)['team_comparison']['n']==0


def test_alerts_merge_only_same_day_and_same_content():
    import json
    store=Store()
    for at in ('2026-10-01T01:00','2026-10-01T02:00','2026-10-02T01:00'):
        appdata.add_alert(store,'guard','risk','same',at)
    items=json.loads(store.get_blob('alerts'))
    assert len(items)==2 and items[1]['repeats']==2
