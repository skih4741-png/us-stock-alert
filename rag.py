"""4단계 RAG(F-C1, F-C2): 자료를 잘라 임베딩해서 구글 시트 'RAG 자료' 탭에 모아 두고, 비슷한 조각을 찾아요.

- 자료: 회사 뉴스 제목·요약, 목표가·등급 변경, 실적 숫자, 모의 거래 기록과 회고, 규칙 설명.
- 벡터는 float16 → base64 글자로 한 칸에 저장 (공개 저장소에는 올리지 않아요).
- 찾을 때는 종목·날짜로 먼저 거르고(과거 날짜 질문엔 그날 이전 자료만), 코사인 유사도 상위 k개.
"""
from __future__ import annotations

import base64
import hashlib
import logging

import numpy as np
import pandas as pd

import ai

log = logging.getLogger(__name__)
TAB = "RAG 자료"
MAX_ROWS = 4000
CHUNK = 1200


def _vec_to_str(v) -> str:
    return base64.b64encode(np.asarray(v, dtype=np.float16).tobytes()).decode()


def _str_to_vec(s: str):
    try:
        return np.frombuffer(base64.b64decode(s), dtype=np.float16).astype(np.float32)
    except Exception:
        return None


def _chunks(text: str) -> list[str]:
    text = " ".join(str(text or "").split())
    return [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]


def add(store, docs: list[dict]) -> int:
    """docs: [{'종목','날짜','종류','제목','출처','내용'}]. 이미 있는 조각(같은 번호)은 건너뛰어요."""
    try:
        cur = store.read(TAB)
    except Exception:
        cur = pd.DataFrame(columns=["번호"])
    have = set(cur["번호"]) if len(cur) else set()
    rows = []
    for d in docs:
        for i, part in enumerate(_chunks(d.get("내용") or d.get("제목"))):
            key = hashlib.sha1(f"{d.get('종목')}|{d.get('날짜')}|{d.get('제목')}|{i}".encode()).hexdigest()[:16]
            if key in have:
                continue
            have.add(key)
            rows.append({"번호": key, "종목": d.get("종목", ""), "날짜": str(d.get("날짜", ""))[:10], "종류": d.get("종류", ""),
                         "제목": str(d.get("제목", ""))[:200], "출처": str(d.get("출처", ""))[:300], "내용": part})
    if not rows:
        return 0
    vecs = ai.embed([f"{r['종목']} {r['제목']} {r['내용']}" for r in rows], "RAG 임베딩")
    if not vecs:
        return 0
    for r, v in zip(rows, vecs):
        r["벡터"] = _vec_to_str(v)
    store.append(TAB, rows)
    if len(cur) + len(rows) > MAX_ROWS:  # 오래된 것부터 정리
        try:
            allr = store.read(TAB).sort_values("날짜")
            store.overwrite(TAB, allr.tail(MAX_ROWS))
        except Exception as e:
            log.warning("RAG 정리 실패: %s", e)
    return len(rows)


def search(store, query: str, tickers: list[str] | None = None, before: str | None = None, k: int = 6) -> list[dict]:
    try:
        df = store.read(TAB)
    except Exception:
        return []
    if not len(df):
        return []
    if tickers:
        df = df[df["종목"].isin(tickers + ["", "공통"])]
    if before:
        df = df[df["날짜"] <= before]
    if not len(df):
        return []
    q = ai.embed([query], "RAG 검색")
    if not q:
        return df.sort_values("날짜", ascending=False).head(k).drop(columns=["벡터"]).to_dict("records")
    qv = np.asarray(q[0], dtype=np.float32)
    scores = []
    for v in df["벡터"]:
        x = _str_to_vec(v)
        scores.append(float(x @ qv / (np.linalg.norm(x) * np.linalg.norm(qv) + 1e-9)) if x is not None and len(x) == len(qv) else -1)
    df = df.assign(점수=scores).sort_values("점수", ascending=False).drop_duplicates("제목").head(k)
    return df.drop(columns=["벡터"]).to_dict("records")
