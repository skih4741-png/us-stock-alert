"""① 예측 — Kronos (github.com/shiyu-coder/Kronos, MIT) 로 다음 5거래일 종가 예측 → data/fund_forecast.json

이 스크립트는 비밀 키가 하나도 없는 GitHub Actions 단계에서만 돌아요 (fund.yml 'kronos' 작업).
Kronos 코드는 저장소에 복사하지 않고, 실행할 때 고정된 버전(KRONOS_COMMIT)을 받아 KRONOS_DIR에 둬요.
가중치: Hugging Face NeoQuasar/Kronos-small + NeoQuasar/Kronos-Tokenizer-base (CPU로 돌려요).

사용: KRONOS_DIR=/tmp/Kronos python fund_kronos.py AAPL MSFT SPY ...
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "data" / "fund_forecast.json"
MODEL, TOKENIZER = "NeoQuasar/Kronos-small", "NeoQuasar/Kronos-Tokenizer-base"
LOOKBACK, PRED_LEN, SAMPLES = 400, 5, 5


def _history(tickers: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    raw = yf.download(tickers, period="2y", interval="1d", auto_adjust=True, group_by="ticker", threads=True, progress=False)
    out = {}
    for t in tickers:
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if len(df) >= LOOKBACK:
                out[t] = df
        except KeyError:
            pass
    return out


def main(tickers: list[str]) -> dict:
    sys.path.insert(0, os.environ.get("KRONOS_DIR", "/tmp/Kronos"))
    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer   # Kronos 저장소의 model/ 폴더

    torch.manual_seed(42)
    np.random.seed(42)
    hist = _history(tickers)
    if not hist:
        raise SystemExit("시세를 받지 못했어요")
    tok = KronosTokenizer.from_pretrained(TOKENIZER)
    mdl = Kronos.from_pretrained(MODEL)
    pred = KronosPredictor(mdl, tok, device="cpu", max_context=512)
    names, dfs, xs, ys = [], [], [], []
    for t, df in hist.items():
        d = df.tail(LOOKBACK)
        x = pd.DataFrame({"open": d["Open"].values, "high": d["High"].values, "low": d["Low"].values,
                          "close": d["Close"].values, "volume": d["Volume"].values})
        x["amount"] = x["close"] * x["volume"]
        xt = pd.Series(pd.to_datetime(d.index).tz_localize(None))
        yt = pd.Series(pd.bdate_range(xt.iloc[-1] + pd.Timedelta(days=1), periods=PRED_LEN))
        names.append(t); dfs.append(x); xs.append(xt); ys.append(yt)
    res = pred.predict_batch(df_list=dfs, x_timestamp_list=xs, y_timestamp_list=ys, pred_len=PRED_LEN,
                             T=1.0, top_p=0.9, sample_count=SAMPLES, verbose=False)
    items = {}
    for t, x, p in zip(names, dfs, res):
        last = float(x["close"].iloc[-1])
        closes = [round(float(v), 2) for v in p["close"].values]
        items[t] = {"last": round(last, 2), "pred": closes, "exp_ret": round(closes[-1] / last - 1, 5)}
    last_day = max(str(pd.Timestamp(xs[i].iloc[-1]).date()) for i in range(len(xs)))
    return {"at": datetime.now(timezone.utc).isoformat(timespec="minutes"), "date": last_day, "model": MODEL,
            "horizon": PRED_LEN, "samples": SAMPLES, "lookback": LOOKBACK, "items": items}


if __name__ == "__main__":
    tick = [t.strip().upper() for t in sys.argv[1:] if t.strip()]
    out = main(tick)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for t, v in out["items"].items():
        print(f"{t:6s} 지금 {v['last']:>9.2f} → 5일 뒤 {v['pred'][-1]:>9.2f} ({v['exp_ret'] * 100:+.2f}%)")
