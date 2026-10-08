"""2단계: 앱 푸시 알림 (웹 푸시 · VAPID).

- 휴대폰 앱에서 '알림 받기'를 켜면 구독 정보가 구글 시트 '푸시 구독' 탭에 저장돼요(로그인 서버가 저장).
- 깃허브 Actions가 이 파일로 푸시를 보내요. 비밀 키는 깃허브 비밀 값 VAPID_PRIVATE_KEY에만 있어요.
- 만료된 구독(404·410)은 자동으로 지워요. 푸시가 실패해도 슬랙은 그대로 가요.
"""
from __future__ import annotations

import json
import logging
import os

import pandas as pd

log = logging.getLogger(__name__)
TAB = "푸시 구독"
CONTACT = "https://skih4741-png.github.io"  # VAPID 연락처(메일 대신 앱 주소)


def _subs(store) -> pd.DataFrame:
    try:
        return store.read(TAB)
    except Exception as e:
        log.info("푸시 구독 탭을 못 읽었어요: %s", e)
        return pd.DataFrame(columns=["등록 시각", "기기", "종류", "구독"])


def send(store, title: str, body: str, url: str = "#/home", kind: str = "daily", tag: str | None = None) -> int:
    """kind: daily(아침 리포트) · watch(장중 경고) · weekly(주간 요약) · system(실패 등, 항상 보냄)."""
    key = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if not key:
        log.info("VAPID_PRIVATE_KEY가 없어 푸시는 건너뛰어요")
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log.warning("pywebpush가 설치되지 않았어요")
        return 0
    df = _subs(store)
    if df.empty:
        return 0
    payload = json.dumps({"title": title, "body": body[:180], "url": url, "tag": tag or kind}, ensure_ascii=False)
    sent, dead = 0, []
    for i, row in df.iterrows():
        kinds = str(row.get("종류", "") or "daily,watch,weekly")
        if kind != "system" and kind not in kinds.split(","):
            continue
        try:
            sub = json.loads(row.get("구독") or "{}")
            webpush(subscription_info=sub, data=payload, vapid_private_key=key,
                    vapid_claims={"sub": CONTACT}, ttl=6 * 3600)
            sent += 1
        except WebPushException as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (404, 410):
                dead.append(i)
            log.warning("푸시 실패(%s): %s", code, str(e)[:120])
        except Exception as e:
            log.warning("푸시 실패: %s", str(e)[:120])
    if dead:
        try:
            store.overwrite(TAB, df.drop(index=dead))
            log.info("만료된 푸시 구독 %d개를 지웠어요", len(dead))
        except Exception:
            pass
    return sent
