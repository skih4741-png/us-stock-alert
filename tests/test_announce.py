import json
import pytest
import announce


class Store:
    def __init__(self): self.blobs={}
    def get_blob(self,key): return self.blobs.get(key)
    def put_blob(self,key,value): self.blobs[key]=value


def test_failed_slack_is_not_marked_complete_and_retry_keeps_successful_channels(monkeypatch):
    store=Store();calls=[]
    monkeypatch.setattr(announce.appdata,'add_alert',lambda *a:calls.append('app'))
    monkeypatch.setattr(announce.push,'send',lambda *a,**k:calls.append('push') or 2)
    monkeypatch.setattr(announce.notify,'send_slack',lambda *a:False)
    release=dict(v='test',title='test',items=['change'])
    with pytest.raises(RuntimeError): announce.announce(store,release)
    assert store.get_blob('announced') is None
    assert json.loads(store.get_blob('announce_status'))['slack'] is False
    monkeypatch.setattr(announce.notify,'send_slack',lambda *a:True)
    announce.announce(store,release)
    assert store.get_blob('announced')=='test'
    announce.announce(store,release)
    assert calls==['app','push']


def test_release_manifest_matches_browser_version():
    import re
    from pathlib import Path
    root=Path(__file__).parents[1]
    version=re.search(r'\bVERSION:\s*"([^"]+)"',(root/'docs/config.js').read_text()).group(1)
    latest=json.loads((root/'docs/changelog.json').read_text())[0]
    assert latest['v']==version, 'Update docs/changelog.json when releasing a browser version'
