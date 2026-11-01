"""네트워크·예약 실행 없이 실제 성적 저장 함수의 알림 중복 방지 검증."""
import ast
import copy
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import appdata


def test_stop_alert_only_on_meaningful_change():
    class Store:
        def __init__(self): self.data={}
        def get_blob(self,k):return self.data.get(k)
        def put_blob(self,k,v):self.data[k]=v
    store=Store();messages=[];trades=[{'t':'A','below_stop':True}]
    tree=ast.parse((Path(__file__).parents[1]/'main.py').read_text(encoding='utf-8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='save_perf')
    env={'json':json,'appdata':appdata,'performance':SimpleNamespace(update=lambda s:{'signals':{},'paper':{'trades':copy.deepcopy(trades)}}),
         'simtrade':SimpleNamespace(load=lambda *a:None,REF_KEY='sim_ref'),
         'push':SimpleNamespace(send=lambda *a,**k:messages.append(a)),
         'log':SimpleNamespace(warning=lambda *a:None),'chk':lambda *a:None}
    exec(compile(ast.Module(body=[function],type_ignores=[]),'<save_perf>','exec'),env)
    save=env['save_perf'];now=datetime(2026,11,1,7)
    save(store,now,notify_stops=False);assert not messages
    save(store,now);save(store,now);assert len(messages)==1
    trades.clear();save(store,now,notify_stops=False)
    trades.append({'t':'A','below_stop':True});save(store,now)
    assert len(messages)==2
