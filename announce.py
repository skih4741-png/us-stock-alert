"""앱 업데이트 알림: docs/changelog.json 맨 위 버전을 아직 안 알렸으면 푸시·슬랙·앱 알림으로 한 번 보내요.
깃허브에 changelog.json이 바뀌어 올라오면 announce.yml이 자동으로 돌려요."""
import json
import logging
from pathlib import Path

import appdata
import config
import notify
import push
from sheets import Store

logging.basicConfig(level=logging.INFO)
c = json.loads(Path("docs/changelog.json").read_text(encoding="utf-8"))[0]
store = Store()
done = store.get_blob("announced") or ""
if done == c["v"]:
    print("이미 알린 버전:", c["v"])
else:
    title = f"앱 업데이트 {c['v']} · {c['title']}"
    body = " / ".join(c["items"][:3])
    n = push.send(store, title, body[:170], "#/home", "system", tag="update")
    notify.send_slack(f":sparkles: *{title}*\n" + "\n".join("• " + x for x in c["items"]) + "\n앱을 껐다 켜면 새 버전으로 바뀌어요.")
    appdata.add_alert(store, "update", title, " / ".join(c["items"])[:200], config.now_kst().isoformat(timespec="minutes"), "info")
    store.put_blob("announced", c["v"])
    print("알림 보냄:", title, "· 푸시", n)
