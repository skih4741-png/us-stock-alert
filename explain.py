"""F-08 쉬운 설명 · F-21 위험 경고·주의 한 줄 (GPT, ai.py를 거쳐요).

AI는 종목을 고르지 않아요. 규칙이 고른 후보와 내 보유 종목에 대해,
계산된 숫자와 뉴스 제목만 보고 설명·경고를 써요. 판정에는 섞지 않아요.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

SYSTEM = """너는 미국 주식 알림 메일에 붙는 짧은 해설을 쓰는 도우미야.
규칙:
1. 주어진 숫자와 뉴스 제목만 사용해. 주어지지 않은 숫자·사실을 만들지 마.
2. "사라", "팔아라", "추천" 같은 지시·권유 표현을 쓰지 마.
3. 초보자도 알 수 있는 쉬운 한국어, 영어 약자 금지(PER, RSI, MACD 등 대신 한국어).
4. 각 종목마다 JSON으로만 답해:
   "설명": 2~3문장, 왜 규칙에 걸렸는지 숫자를 근거로.
   "주의": 이 신호가 틀릴 수 있는 가장 큰 이유 1문장.
   "경고": 뉴스 제목 중 유상증자·전환사채·소송·조사·경영진 사임·상장폐지·실적 경고 같은 위험이 있으면 "출처, 날짜: 한 줄", 없으면 반드시 빈 문자열 ""(「없음」이라고 쓰지 마).
   "급등원인": 급등 종목만, 뉴스 제목에서 원인을 찾으면 한 줄, 못 찾으면 "원인 불명 급등".
출력은 {"종목코드": {...}, ...} 형태의 JSON 하나만."""


def explain(items: list[dict], cfg: dict) -> dict[str, dict]:
    """ai.init()이 먼저 불려 있어야 해요. 실패하면 빈 dict, 설명 없이 표만 보내요."""
    import ai
    if not items:
        return {}
    out: dict[str, dict] = {}
    try:
        for i in range(0, len(items), 12):  # 12개씩 나눠서
            r = ai.chat_json("아침 설명", SYSTEM, items[i:i + 12], "small", 4000)
            if isinstance(r, dict):
                out.update(r)
        return _guard(out, items)
    except Exception as e:
        log.warning("AI 설명 실패: %s", e)
        return {}


def _guard(out: dict, items: list[dict]) -> dict:
    """설명에 주어지지 않은 큰 숫자가 나오면 그 설명은 버려요(지어낸 숫자 방지)."""
    allowed = {it["종목코드"]: json.dumps(it, ensure_ascii=False) for it in items}
    clean = {}
    for t, v in out.items():
        if t not in allowed or not isinstance(v, dict):
            continue
        desc = str(v.get("설명", ""))
        nums = re.findall(r"\d+(?:\.\d+)?", desc)
        bad = [n for n in nums if len(n.replace(".", "")) >= 2 and n not in allowed[t]]
        if bad:
            v["설명"] = ""
        clean[t] = {k: str(v.get(k, "") or "") for k in ("설명", "주의", "경고", "급등원인")}
        w = clean[t]["경고"].strip()
        if not w or re.search(r"없음|해당\s*없|없습니다|^-$|^N/?A$", w):   # "출처, 날짜: 없음" 같은 빈 경고는 버려요
            clean[t]["경고"] = ""
    return clean
