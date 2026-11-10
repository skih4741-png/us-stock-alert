"""Publish release notifications and retain per-channel outcomes for safe retries."""
import json
import logging
from pathlib import Path

import appdata
import config
import notify
import push
from sheets import Store


def announce(store, release):
    version = release['v']
    raw = store.get_blob('announce_status') or '{}'
    status = json.loads(raw)
    if status.get('version') != version:
        status = dict(version=version, slack=False, app=False, push=0)
    # Preserve compatibility with releases already completed by the old runner.
    if store.get_blob('announced') == version and not status.get('at'):
        return dict(version=version, legacy_complete=True)
    title = f"앱 업데이트 {version} · {release['title']}"
    items = release['items']
    status['at'] = config.now_kst().isoformat(timespec='minutes')
    def persist():
        store.put_blob('announce_status', json.dumps(status, ensure_ascii=False))
    if not status.get('app'):
        appdata.add_alert(store, 'update', title, ' / '.join(items)[:200], status['at'], 'info')
        status['app'] = True
        persist()
    if not status.get('slack'):
        status['slack'] = bool(notify.send_slack(
            f":sparkles: *{title}*\n" + '\n'.join('• ' + x for x in items)
            + '\n앱을 다시 열면 새 버전으로 바뀌어요.'))
        persist()
    if not status.get('push'):
        status['push'] = push.send(store, title, ' / '.join(items[:3])[:170], '#/home', 'system', tag='update')
        persist()
    if status.get('app') and status.get('slack'):
        store.put_blob('announced', version)
    print('업데이트 알림 결과:', json.dumps(status, ensure_ascii=False))
    if not status.get('app') or not status.get('slack'):
        raise RuntimeError('업데이트 알림 미완료 · 채널별 결과 확인 필요')
    if not status.get('push'):
        logging.warning('기기 푸시 접수 0개 · 구독·키·발송 로그 확인 필요, 기기 도착 미검증')
    return status


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    release = json.loads(Path('docs/changelog.json').read_text(encoding='utf-8'))[0]
    announce(Store(), release)
