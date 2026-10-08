"""F-10 보유 종목 읽기 · F-11 결과 기록 · F-12 설정 읽기.

구글 시트 키(GOOGLE_SERVICE_ACCOUNT_JSON)와 시트 주소(SHEET_ID)가 있으면 구글 시트를,
없으면 data/local_sheet 폴더의 CSV 파일을 써요(PC 시험용).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
LOCAL = Path(__file__).parent / "data" / "local_sheet"

TABS = {
    "보유 종목": ["종목코드", "수량", "평균 단가", "손절선", "매수일", "산 이유", "메모"],
    "설정": ["항목", "값", "설명"],
    "오늘 리스트": ["날짜", "시장 국면", "가격대", "판정", "순위", "종목", "회사명", "주가", "총점", "추세", "가치", "성장", "안전",
                "이유", "매수 구간", "손절", "1차 목표", "유효 기한", "연속 일수", "어제 대비", "표시", "쉬운 설명", "주의 한 줄", "위험 경고"],
    "신호 기록": ["날짜", "시장 국면", "종목", "판정", "순위", "가격대", "그날 주가", "총점", "손절", "1차 목표", "5일 뒤 수익률", "20일 뒤 수익률",
              "SPY 5일", "SPY 20일", "결과"],
    "실행 기록": ["날짜", "시각", "종류", "성공/실패", "분석한 종목 수", "걸린 시간(초)", "막힌 단계", "메모"],
    "앱 데이터": ["키", "순번", "내용"],
    "푸시 구독": ["등록 시각", "기기", "종류", "구독"],
    "AI 사용": ["월", "앱 질문 사용액"],
    "증권사 모의 체결": ["날짜", "시각", "종목", "구분", "주문 수량", "체결 수량", "체결가", "상태"],
    "RAG 자료": ["번호", "종목", "날짜", "종류", "제목", "출처", "내용", "벡터"],
    "성향": ["항목", "답"],
    "모의 거래": ["번호", "담은 날", "종목", "수량", "담은 가격", "손절", "1차 목표", "판 날", "판 가격", "판 이유", "회고"],
}
CHUNK = 40000  # 구글 시트 한 칸은 5만 자까지라 나눠서 저장


class Store:
    def __init__(self):
        self.gs = None
        key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        sid = os.environ.get("SHEET_ID")
        if key and sid:
            import gspread
            from google.oauth2.service_account import Credentials

            creds = Credentials.from_service_account_info(
                json.loads(key), scopes=["https://www.googleapis.com/auth/spreadsheets"])
            self.gc = gspread.authorize(creds)
            self.gs = self.gc.open_by_key(sid)
        else:
            LOCAL.mkdir(parents=True, exist_ok=True)
        self.ensure_tabs()

    # ----- 공통 -----
    def ensure_tabs(self):
        if self.gs:
            names = [w.title for w in self.gs.worksheets()]
            for tab, cols in TABS.items():
                if tab not in names:
                    ws = self.gs.add_worksheet(title=tab, rows=200, cols=max(10, len(cols)))
                    ws.update([cols], "A1")
                    if tab == "설정":
                        from config import DEFAULTS
                        ws.update([[k, str(v), ""] for k, v in DEFAULTS.items()], "A2")
            for default in ("Sheet1", "시트1"):
                if default in names:
                    try:
                        ws = self.gs.worksheet(default)
                        if not any(any(c for c in row) for row in ws.get_all_values()):
                            self.gs.del_worksheet(ws)
                    except Exception:
                        pass
        else:
            for tab, cols in TABS.items():
                p = LOCAL / f"{tab}.csv"
                if not p.exists():
                    pd.DataFrame(columns=cols).to_csv(p, index=False, encoding="utf-8-sig")

    def read(self, tab: str) -> pd.DataFrame:
        if self.gs:
            rows = self.gs.worksheet(tab).get_all_values()
            if not rows:
                return pd.DataFrame(columns=TABS[tab])
            return pd.DataFrame(rows[1:], columns=rows[0])
        p = LOCAL / f"{tab}.csv"
        return pd.read_csv(p, dtype=str, encoding="utf-8-sig").fillna("") if p.exists() else pd.DataFrame(columns=TABS[tab])

    def overwrite(self, tab: str, df: pd.DataFrame):
        df = df.reindex(columns=TABS[tab]).fillna("")
        if self.gs:
            ws = self.gs.worksheet(tab)
            need_r, need_c = len(df) + 1, len(TABS[tab])
            if ws.row_count < need_r or ws.col_count < need_c:
                ws.resize(rows=max(ws.row_count, need_r + 50), cols=max(ws.col_count, need_c))
            ws.clear()
            ws.update([TABS[tab]] + df.astype(str).values.tolist(), "A1")
        else:
            df.to_csv(LOCAL / f"{tab}.csv", index=False, encoding="utf-8-sig")

    def append(self, tab: str, rows: list[dict]):
        if not rows:
            return
        df = pd.DataFrame(rows).reindex(columns=TABS[tab]).fillna("")
        if self.gs:
            ws = self.gs.worksheet(tab)
            if ws.col_count < len(TABS[tab]):
                ws.resize(cols=len(TABS[tab]))
            ws.append_rows(df.astype(str).values.tolist(), value_input_option="USER_ENTERED")
        else:
            p = LOCAL / f"{tab}.csv"
            old = self.read(tab)
            pd.concat([old, df.astype(str)], ignore_index=True).to_csv(p, index=False, encoding="utf-8-sig")

    def put_blob(self, key: str, text: str):
        """'앱 데이터' 탭에 key 이름으로 긴 글(JSON)을 나눠 저장해요. 같은 key의 예전 내용은 지워요."""
        df = self.read("앱 데이터")
        keep = df[df["키"] != key] if len(df) else df
        parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
        new = pd.DataFrame([{"키": key, "순번": str(i), "내용": p} for i, p in enumerate(parts)])
        out = pd.concat([keep, new], ignore_index=True)
        if self.gs:
            ws = self.gs.worksheet("앱 데이터")
            ws.clear()
            ws.update([TABS["앱 데이터"]] + out.reindex(columns=TABS["앱 데이터"]).fillna("").astype(str).values.tolist(),
                      "A1", value_input_option="RAW")
        else:
            out.to_csv(LOCAL / "앱 데이터.csv", index=False, encoding="utf-8-sig")

    def get_blob(self, key: str) -> str:
        df = self.read("앱 데이터")
        if not len(df):
            return ""
        part = df[df["키"] == key].copy()
        part["n"] = pd.to_numeric(part["순번"], errors="coerce")
        return "".join(part.sort_values("n")["내용"].tolist())

    # ----- 의미 단위 -----
    def holdings(self) -> list[dict]:
        own = self._own_holdings()
        ext = self._external_holdings()
        if not ext:
            return own
        by = {h["ticker"]: h for h in ext}
        for h in own:  # 이 시트 '보유 종목' 탭에 적은 손절선·매수일·산 이유가 있으면 그걸 우선
            if h["ticker"] in by:
                e = by[h["ticker"]]
                e["stop"] = h["stop"] or e["stop"]
                e["buy_date"] = h["buy_date"] or e["buy_date"]
                e["why"] = h["why"] or e["why"]
            else:
                by[h["ticker"]] = h
        return list(by.values())

    @staticmethod
    def _num(x) -> float | None:
        try:
            return float(str(x).replace(",", "").replace("$", "").replace("원", "").strip())
        except ValueError:
            return None

    def _external_holdings(self) -> list[dict]:
        """설정 '보유 종목 시트 주소'에 적은 다른 구글 시트(예: 배당투자 대시보드 '내 종목' 탭)에서 보유 종목을 읽어요."""
        if not self.gs:
            return []
        cfg = self.settings()
        ref = str(cfg.get("보유 종목 시트 주소", "")).strip()
        if not ref:
            return []
        tab = str(cfg.get("보유 종목 탭", "") or "내 종목").strip()
        try:
            import re
            m = re.search(r"/d/([A-Za-z0-9_-]+)", ref)
            book = self.gc.open_by_key(m.group(1) if m else ref)
            rows = self._find_ws(book, tab).get_all_values()
        except Exception as e:
            log.warning("보유 종목 시트를 못 읽었어요: %s", e)
            return []
        short = lambda r, w: any(w in c and len(c) <= 12 for c in r)  # 설명 문장이 아닌 머리글 칸만
        hdr_i = next((i for i, r in enumerate(rows) if short(r, "수량") and short(r, "평단")), None)
        if hdr_i is None:
            log.warning("보유 종목 시트에서 '수량'·'평단' 머리글을 못 찾았어요")
            return []
        hdr = [c.replace("\n", " ") for c in rows[hdr_i]]
        def col(*words):
            return next((j for j, c in enumerate(hdr) if len(c) <= 12 and all(w in c for w in words)), None)
        ct, cq, ca = col("종목") if col("종목") is not None else col("티커"), col("수량"), col("평단")
        first_buy = self._first_buy_dates(book)
        out = []
        for r in rows[hdr_i + 1:]:
            if ct is None or ct >= len(r):
                continue
            t = r[ct].strip().upper()
            if not t or not t.replace("-", "").replace(".", "").isalnum() or len(t) > 6:
                continue
            qty = self._num(r[cq]) if cq is not None and cq < len(r) else None
            avg = self._num(r[ca]) if ca is not None and ca < len(r) else None
            if not qty or qty <= 0 or not avg:
                continue
            out.append({"ticker": t, "qty": qty, "avg": avg, "stop": None,
                        "buy_date": first_buy.get(t), "why": "", "source": "external"})
        return out

    @staticmethod
    def _find_ws(book, name: str):
        """탭 이름 앞에 이모지가 붙어 있어도 찾아요 (예: '📋 내 종목')."""
        for ws in book.worksheets():
            if ws.title == name:
                return ws
        for ws in book.worksheets():
            if ws.title.strip().endswith(name) and "원본" not in ws.title:
                return ws
        raise KeyError(name)

    def _first_buy_dates(self, book) -> dict:
        """'매매기록' 탭이 있으면 종목별 첫 매수일을 찾아요(추적 매도·제자리 규칙용)."""
        try:
            rows = self._find_ws(book, "매매기록").get_all_values()
        except Exception:
            return {}
        hdr_i = next((i for i, r in enumerate(rows) if any(c.strip() == "거래일자" for c in r)), None)
        if hdr_i is None:
            return {}
        hdr = rows[hdr_i]
        cd = next((j for j, c in enumerate(hdr) if c.strip() == "거래일자"), None)
        ct = next((j for j, c in enumerate(hdr) if len(c) <= 12 and ("종목" in c or "티커" in c)), None)
        ck = next((j for j, c in enumerate(hdr) if len(c) <= 12 and "구분" in c), None)
        out = {}
        for r in rows[hdr_i + 1:]:
            try:
                d, t = r[cd].strip(), r[ct].strip().upper()
                if not d or not t or (ck is not None and "매수" not in r[ck]):
                    continue
                if t not in out or d < out[t]:
                    out[t] = d
            except (IndexError, TypeError):
                continue
        return out

    def _own_holdings(self) -> list[dict]:
        df = self.read("보유 종목")
        out = []
        for _, r in df.iterrows():
            t = str(r.get("종목코드", "")).strip().upper()
            if not t:
                continue
            try:
                avg = float(str(r.get("평균 단가", "")).replace(",", "").replace("$", ""))
            except ValueError:
                continue
            stop_raw = str(r.get("손절선", "")).strip()
            stop = None
            if stop_raw.endswith("%"):
                try:
                    stop = avg * (1 - abs(float(stop_raw[:-1])) / 100)
                except ValueError:
                    pass
            elif stop_raw:
                try:
                    stop = float(stop_raw.replace(",", "").replace("$", ""))
                except ValueError:
                    pass
            try:
                qty = float(str(r.get("수량", "0")).replace(",", "") or 0)
            except ValueError:
                qty = 0
            out.append({"ticker": t, "qty": qty, "avg": avg, "stop": stop,
                        "buy_date": str(r.get("매수일", "")).strip() or None, "why": r.get("산 이유", "")})
        return out

    def settings(self) -> dict:
        df = self.read("설정")
        return {str(r["항목"]).strip(): r["값"] for _, r in df.iterrows() if str(r.get("항목", "")).strip()}
