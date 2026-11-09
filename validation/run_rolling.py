"""Run chronological fixed-rule folds; research diagnostics, no auto-promotion."""
import argparse
import json
from pathlib import Path

import config
import prices
import universe
from validation.data_quality import clean_history
from validation.historical_universe import read_membership_csv
from validation.walk_forward import rolling_evaluation


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers",type=int,default=20)
    p.add_argument("--folds",type=int,default=3)
    p.add_argument("--universe-csv", type=Path, default=None,
                   help="Historical membership ticker,start_date,end_date; requires separately verified price coverage")
    p.add_argument("--months",type=int,default=12)
    p.add_argument("--output",type=Path,default=Path("data/rolling_comparison.json"))
    args = p.parse_args()
    cfg,_ = config.merge_settings({})
    u,_ = universe.load_universe(cfg,include_etf=False)
    u = u.assign(dv=u["price"].fillna(0)*u["volume"].fillna(0))
    names = list(u.sort_values("dv",ascending=False).head(args.tickers)["yf_ticker"])
    membership = read_membership_csv(args.universe_csv) if args.universe_csv else None
    if membership is not None:
        names = membership.tickers
    hist = prices.download_history(["SPY"]+names,period="5y")
    hist, rejected = clean_history(hist, min_bars=260)
    spy = hist.pop("SPY",None)
    if spy is None or len(spy)<500:
        raise SystemExit("Insufficient SPY history")
    out = rolling_evaluation(hist,spy,cfg,fold_months=args.months,folds=args.folds, membership=membership)
    out["universe"]="CURRENT selected listed shares; survivorship bias"
    out["tickers_received"]=len(hist)
    out["data_rejected"]=rejected
    out["membership_csv_used"]=membership is not None
    out["historical_universe_verified"]=False
    out["missing_price_history"]=sorted(set(names)-set(hist))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(out["summary"],ensure_ascii=False,indent=2))
    print(json.dumps(out["promotion_gate"],ensure_ascii=False,indent=2))
    print("Saved",args.output)


if __name__ == "__main__":
    main()
