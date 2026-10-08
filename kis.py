"""11장: 한국투자증권 오픈API — **모의투자 전용** 연결 (실전은 막혀 있어요).

비밀 값(깃허브 Secrets): KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO(앞 8자리), KIS_ACCOUNT_PROD(뒤 2자리), KIS_MODE(paper|real)
- KIS_MODE가 paper가 아니면 아무 주문도 내지 않아요. 실전 전환은 본인이 요청해야 따로 열어요.
- 접근 토큰은 하루 한 번만 받아 비공개 구글 시트에 23시간 보관해요(자주 받으면 증권사가 막거나 알림을 보내요).
- 로그·알림에는 계좌번호·키·토큰을 남기지 않아요.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)
BASE = "https://openapivts.koreainvestment.com:29443"   # 모의투자 서버
TR = {"buy": "VTTT1002U", "sell": "VTTT1001U", "balance": "VTTS3012R", "ccnl": "VTTS3035R"}  # 모의 TR (매도는 1001U)
EXCG_MAP = {"NMS": "NASD", "NGM": "NASD", "NCM": "NASD", "NAS": "NASD", "NASDAQ": "NASD",
            "NYQ": "NYSE", "NYS": "NYSE", "NYSE": "NYSE",
            "ASE": "AMEX", "AMX": "AMEX", "PCX": "AMEX", "ARCA": "AMEX", "BTS": "AMEX", "BATS": "AMEX"}


class KisError(Exception):
    pass


def configured() -> tuple[bool, str]:
    need = ["KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO", "KIS_ACCOUNT_PROD"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        return False, "비밀 값 없음: " + ", ".join(miss)
    if os.environ.get("KIS_MODE", "").strip().lower() != "paper":
        return False, "KIS_MODE가 paper가 아니라서 주문하지 않아요 (실전은 아직 열지 않았어요)"
    return True, ""


class Client:
    def __init__(self, store=None):
        ok, why = configured()
        if not ok:
            raise KisError(why)
        self.store = store
        self.key, self.secret = os.environ["KIS_APP_KEY"], os.environ["KIS_APP_SECRET"]
        self.cano, self.prod = os.environ["KIS_ACCOUNT_NO"].strip()[:8], os.environ["KIS_ACCOUNT_PROD"].strip()[:2]
        self._token = None
        self._last = 0.0

    # ---- 토큰 (하루 한 번) ----
    def token(self) -> str:
        if self._token:
            return self._token
        now = datetime.now(timezone.utc)
        if self.store:
            try:
                c = json.loads(self.store.get_blob("kis_token") or "{}")
                if c.get("exp", "") > now.isoformat():
                    self._token = c["t"]
                    return self._token
            except Exception:
                pass
        r = requests.post(BASE + "/oauth2/tokenP", timeout=20,
                          json={"grant_type": "client_credentials", "appkey": self.key, "appsecret": self.secret})
        j = r.json() if r.content else {}
        if r.status_code != 200 or "access_token" not in j:
            raise KisError(f"토큰 발급 실패 ({r.status_code}) {str(j.get('error_description') or j.get('msg1') or '')[:80]}")
        self._token = j["access_token"]
        if self.store:
            try:
                self.store.put_blob("kis_token", json.dumps({"t": self._token, "exp": (now + timedelta(hours=23)).isoformat()}))
            except Exception:
                pass
        return self._token

    def _h(self, tr: str) -> dict:
        return {"content-type": "application/json; charset=utf-8", "authorization": "Bearer " + self.token(),
                "appkey": self.key, "appsecret": self.secret, "tr_id": tr, "custtype": "P"}

    def _wait(self):  # 모의투자는 초당 호출 수가 적어요
        d = time.time() - self._last
        if d < 0.6:
            time.sleep(0.6 - d)
        self._last = time.time()

    def _get(self, path, tr, params):
        self._wait()
        r = requests.get(BASE + path, headers=self._h(tr), params=params, timeout=20)
        j = r.json() if r.content else {}
        if r.status_code != 200 or str(j.get("rt_cd")) != "0":
            raise KisError(f"{tr} 실패 ({r.status_code}) {j.get('msg_cd', '')} {str(j.get('msg1', ''))[:80]}")
        return j

    def _post(self, path, tr, body):
        self._wait()
        r = requests.post(BASE + path, headers=self._h(tr), json=body, timeout=20)
        j = r.json() if r.content else {}
        if r.status_code != 200 or str(j.get("rt_cd")) != "0":
            raise KisError(f"{tr} 실패 ({r.status_code}) {j.get('msg_cd', '')} {str(j.get('msg1', ''))[:80]}")
        return j

    # ---- 조회 ----
    def balance(self) -> dict:
        out1, out2 = [], {}
        for ex in ("NASD", "NYSE", "AMEX"):
            j = self._get("/uapi/overseas-stock/v1/trading/inquire-balance", TR["balance"],
                          {"CANO": self.cano, "ACNT_PRDT_CD": self.prod, "OVRS_EXCG_CD": ex, "TR_CRCY_CD": "USD",
                           "CTX_AREA_FK200": "", "CTX_AREA_NK200": ""})
            for x in j.get("output1") or []:
                if float(x.get("ovrs_cblc_qty") or 0) > 0 and x.get("ovrs_pdno") not in [y["t"] for y in out1]:
                    out1.append({"t": x.get("ovrs_pdno"), "qty": int(float(x.get("ovrs_cblc_qty") or 0)),
                                 "avg": float(x.get("pchs_avg_pric") or 0), "now": float(x.get("now_pric2") or 0),
                                 "pnl": float(x.get("frcr_evlu_pfls_amt") or 0), "excg": x.get("ovrs_excg_cd") or ex})
            o2 = j.get("output2") or {}
            if isinstance(o2, list):
                o2 = o2[0] if o2 else {}
            out2 = out2 or o2
        return {"holdings": out1, "summary": {"buy_amt": _f(out2.get("frcr_pchs_amt1")), "pnl": _f(out2.get("ovrs_tot_pfls")),
                                              "ret": _f(out2.get("tot_pftrt"))}}

    def fills(self, day: str) -> list[dict]:
        """day: YYYYMMDD (한국 날짜 기준)."""
        j = self._get("/uapi/overseas-stock/v1/trading/inquire-ccnl", TR["ccnl"],
                      {"CANO": self.cano, "ACNT_PRDT_CD": self.prod, "PDNO": "%", "ORD_STRT_DT": day, "ORD_END_DT": day,
                       "SLL_BUY_DVSN": "00", "CCLD_NCCS_DVSN": "00", "OVRS_EXCG_CD": "%", "SORT_SQN": "DS",
                       "ORD_DT": "", "ORD_GNO_BRNO": "", "ODNO": "", "CTX_AREA_NK200": "", "CTX_AREA_FK200": ""})
        out = []
        for x in j.get("output") or []:
            out.append({"odno": x.get("odno"), "t": x.get("pdno"), "side": "매도" if x.get("sll_buy_dvsn_cd") == "01" else "매수",
                        "qty": _f(x.get("ft_ord_qty")), "filled": _f(x.get("ft_ccld_qty")), "price": _f(x.get("ft_ccld_unpr3")),
                        "ord_price": _f(x.get("ft_ord_unpr3")), "status": x.get("prcs_stat_name") or "", "time": x.get("ord_tmd") or ""})
        return out

    # ---- 주문 (지정가만, 모의투자) ----
    def order(self, side: str, t: str, qty: int, price: float, excg: str) -> str:
        if qty < 1:
            raise KisError("수량 0")
        j = self._post("/uapi/overseas-stock/v1/trading/order", TR["buy" if side == "buy" else "sell"],
                       {"CANO": self.cano, "ACNT_PRDT_CD": self.prod, "OVRS_EXCG_CD": excg, "PDNO": t.replace("-", "."),
                        "ORD_QTY": str(int(qty)), "OVRS_ORD_UNPR": f"{price:.2f}", "ORD_SVR_DVSN_CD": "0", "ORD_DVSN": "00"})
        return str((j.get("output") or {}).get("ODNO") or "")


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def exchange(t: str, cache: dict) -> str:
    if t in cache:
        return cache[t]
    try:
        import yfinance as yf
        ex = (yf.Ticker(t.replace(".", "-")).fast_info or {}).get("exchange") or (yf.Ticker(t.replace(".", "-")).info or {}).get("exchange")
    except Exception:
        ex = None
    cache[t] = EXCG_MAP.get(str(ex or "").upper(), "NASD")
    return cache[t]


if __name__ == "__main__":  # python kis.py check — 연결 점검 (주문은 안 내요, 계좌번호·키는 출력 안 함)
    import sys
    logging.basicConfig(level=logging.INFO)
    ok, why = configured()
    print("설정:", "OK" if ok else why)
    if not ok:
        sys.exit(0)
    from sheets import Store
    c = Client(Store())
    try:
        c.token()
        print("토큰: 받음")
        b = c.balance()
        print("잔고 조회: 성공 · 보유", len(b["holdings"]), "종목 · 요약", json.dumps(b["summary"], ensure_ascii=False))
        kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")
        print("오늘 주문·체결:", len(c.fills(kst)), "건")
    except KisError as e:
        print("실패:", e)
    sys.exit(0)
