"""Read existing artifacts and optionally probe AI with synthetic data only.

Never sends notifications, creates orders, refreshes broker tokens or stores AI output.
Logs contain status/counts only, not holdings, balances, key values or generated prose.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import requests
import ai
import config


def check(store, *, probe_ai=False, probe_server=False) -> dict:
    checks = []
    def add(name, ok, detail):
        checks.append({"name": name, "ok": ok, "detail": detail})
    cfg, warnings = config.merge_settings(store.settings())
    add("설정 읽기", not warnings, f"설정 경고 {len(warnings)}개")
    blobs = {}
    for key in ("daily", "health", "ai", "sim", "kis"):
        try:
            raw = store.get_blob(key)
            blobs[key] = json.loads(raw) if raw else None
            add(key + " 저장 자료", isinstance(blobs[key], dict), "JSON 객체 확인" if isinstance(blobs[key], dict) else "저장 자료 없음")
        except (ValueError, TypeError):
            add(key + " 저장 자료", False, "JSON 형식 오류")
    daily = blobs.get("daily") or {}
    add("아침 데이터 형식", bool(daily.get("date") and isinstance(daily.get("summary"), dict)), "날짜·요약 존재 여부")
    saved_health = blobs.get("health") or {}
    add("마지막 운영 점검", saved_health.get("state") == "ok", str(saved_health.get("state") or "미확인"))
    kis = blobs.get("kis") or {}
    add("증권사 저장 상태", None if not kis else bool(kis.get("on") and not kis.get("err")),
        "저장 상태만 조회 · 실제 연결/주문 미검증")
    if probe_ai:
        # Do not persist usage/diagnostic blobs and never pass account data to providers.
        ai.init(store, cfg)
        result = ai.chat_json("연결 점검", 'Return only {"ok":true}.', {"synthetic_test": True}, "small", 2000, 25)
        add("모델 실제 응답", bool(result and result.get("ok") is True),
            "가상 시험 자료만 전송 · 저장 안 함")
        for name, error in ai.status().get("errors", {}).items():
            add("공급자 " + name, False, "HTTP/진단 상태 " + str(error.get("status")))
    if probe_server:
        js = (Path(__file__).parent / "docs/config.js").read_text(encoding="utf-8")
        url = re.search(r'API_URL:\s*"([^"]+)"', js).group(1)
        expected = re.search(r'SERVER_VERSION:\s*"([^"]+)"', js).group(1)
        try:
            r = requests.get(url, timeout=25)
            payload = r.json() if r.ok else {}
            add("웹앱 서버 응답", payload.get("ok") is True, "공개 상태 조회 · 로그인 기능 미검증")
            version = payload.get("serverVersion")
            add("웹앱 서버 배포 버전", version == expected,
                "일치" if version == expected else "버전 불일치 또는 구버전(버전 정보 없음)")
        except (requests.RequestException, ValueError):
            add("웹앱 서버 응답", False, "응답 없음 또는 JSON 형식 아님")
    return {"checks": checks, "failed": sum(c["ok"] is False for c in checks),
            "note": "읽기 및 가상 연결 점검. 주문·메일·슬랙·푸시 발송 없음. 로그인 후 화면은 별도 검증 필요."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-ai", action="store_true")
    parser.add_argument("--probe-server", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON") or not os.environ.get("SHEET_ID"):
        raise SystemExit("운영 저장소 연결 설정이 없어 점검하지 못했습니다.")
    from sheets import Store
    # Bypass bootstrap mutations: diagnostics must not create/delete worksheets.
    from unittest.mock import patch
    with patch.object(Store, "ensure_tabs", lambda self: None):
        store = Store()
    report = check(store, probe_ai=args.probe_ai, probe_server=args.probe_server)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(2 if report["failed"] else 0)
