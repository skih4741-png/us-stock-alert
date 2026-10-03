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
    "신호 기록": ["날짜", "시장 국면", "종목", "판정", "순위", "가격대", "그날 주가", "총점", "손절", "1차 목표", "5일 뒤 수익률", "20일 뒤 수익률"],
    "실행 기록": ["날짜", "시각", "종류", "성공/실패", "분석한 종목 수", "걸린 시간(초)", "막힌 단계", "메모"],
}


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
            self.gs = gspread.authorize(creds).open_by_key(sid)
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
            ws.clear()
            ws.update([TABS[tab]] + df.astype(str).values.tolist(), "A1")
        else:
            df.to_csv(LOCAL / f"{tab}.csv", index=False, encoding="utf-8-sig")

    def append(self, tab: str, rows: list[dict]):
        if not rows:
            return
        df = pd.DataFrame(rows).reindex(columns=TABS[tab]).fillna("")
        if self.gs:
            self.gs.worksheet(tab).append_rows(df.astype(str).values.tolist(), value_input_option="USER_ENTERED")
        else:
            p = LOCAL / f"{tab}.csv"
            old = self.read(tab)
            pd.concat([old, df.astype(str)], ignore_index=True).to_csv(p, index=False, encoding="utf-8-sig")

    # ----- 의미 단위 -----
    def holdings(self) -> list[dict]:
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
