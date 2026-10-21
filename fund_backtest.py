"""③ 실행 — NautilusTrader 백테스트 (github.com/nautechsystems/nautilus_trader, LGPL-3.0, pip 패키지로만 사용).

가이드 그대로: '비중표대로 매주 리밸런싱 · 수수료 0.1% · 거래 기록과 누적 수익'.
다만 오늘 만든 비중으로 과거를 돌리면 미래를 아는 셈(look-ahead)이라, 매주 그 시점까지의 자료로만
비중을 다시 계산하는 '걸어가며 검증(walk-forward)' 방식으로 돌려요. 실제 주문·증권사 연결은 없어요.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import pandas as pd

log = logging.getLogger(__name__)

START_CASH = 100_000   # 정수 주식만 살 수 있어서 넉넉한 가상 금액으로 돌리고 결과는 %로만 보여요
FEE = Decimal("0.001")  # 0.1%


def run(hist: dict[str, pd.DataFrame], weight_fn, start: str | None = None, fee: Decimal = FEE) -> dict | None:
    """hist: {티커: 일봉(Open High Low Close Volume)}. weight_fn(날짜, 그날까지의 hist) -> {티커: 비중(0~1)}.
    반환: {"curve": [[날짜, 평가액], ...], "trades": n, "fees": $, "rebalances": [...], "final": $}"""
    from nautilus_trader.backtest.engine import BacktestEngine, BacktestEngineConfig
    from nautilus_trader.config import LoggingConfig, StrategyConfig
    from nautilus_trader.model.currencies import USD
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.enums import AccountType, OmsType, OrderSide, TimeInForce
    from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
    from nautilus_trader.model.instruments import Equity
    from nautilus_trader.model.objects import Money, Price, Quantity
    from nautilus_trader.trading.strategy import Strategy

    tickers = [t for t, df in hist.items() if df is not None and len(df) > 60]
    if len(tickers) < 2:
        return None
    # 모든 종목이 같은 날짜를 갖도록 맞춰요 (빠진 날은 그 종목 거래 없음)
    idx = sorted(set().union(*[set(hist[t].index) for t in tickers]))
    start_ts = pd.Timestamp(start) if start else idx[min(len(idx) - 1, 252)]
    venue = Venue("SIM")
    engine = BacktestEngine(BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True)))
    engine.add_venue(venue=venue, oms_type=OmsType.NETTING, account_type=AccountType.CASH, base_currency=USD,
                     starting_balances=[Money(START_CASH, USD)])
    inst, btypes = {}, {}
    for t in tickers:
        i = Equity(instrument_id=InstrumentId(Symbol(t), venue), raw_symbol=Symbol(t), currency=USD, price_precision=2,
                   price_increment=Price.from_str("0.01"), lot_size=Quantity.from_int(1), ts_event=0, ts_init=0,
                   maker_fee=fee, taker_fee=fee)
        engine.add_instrument(i)
        bt = BarType.from_str(f"{t}.SIM-1-DAY-LAST-EXTERNAL")
        df = hist[t].loc[hist[t].index >= start_ts, ["Open", "High", "Low", "Close", "Volume"]].copy()
        df.columns = ["open", "high", "low", "close", "volume"]
        df = df.dropna()
        if df.empty:
            continue
        df.index = pd.to_datetime(df.index).tz_localize(None).tz_localize("UTC") + pd.Timedelta(hours=21)  # 미국 장 마감 시각
        engine.add_data(_bars(bt, i, df))
        inst[t], btypes[t] = i, bt
    if len(inst) < 2:
        return None

    class Cfg(StrategyConfig, frozen=True):
        pass

    class Rebalance(Strategy):
        def __init__(self):
            super().__init__(Cfg())
            self.last: dict[str, float] = {}
            self.week = None
            self.curve: list[list] = []
            self.rebal: list[dict] = []

        def on_start(self):
            for bt in btypes.values():
                self.subscribe_bars(bt)

        def _value(self):
            acct = self.portfolio.account(venue)
            cash = float(acct.balance_total(USD).as_double()) if acct else 0.0
            pos = 0.0
            for t, i in inst.items():
                q = float(self.portfolio.net_position(i.id))
                if q and t in self.last:
                    pos += q * self.last[t]
            return cash + pos

        def on_bar(self, bar: Bar):
            t = bar.bar_type.instrument_id.symbol.value
            self.last[t] = float(bar.close)
            day = pd.Timestamp(bar.ts_event, unit="ns", tz="UTC").tz_convert(None).normalize()
            if len(self.last) < len(inst):
                return
            wk = day.isocalendar()[:2]
            if self.curve and self.curve[-1][0] == str(day.date()):
                self.curve[-1][1] = round(self._value(), 2)
            else:
                self.curve.append([str(day.date()), round(self._value(), 2)])
            if wk == self.week or t != list(inst)[-1]:
                return                      # 한 주에 한 번, 그날 마지막 종목 봉이 들어온 뒤에
            self.week = wk
            past = {k: v.loc[v.index <= day.tz_localize(None)] for k, v in hist.items() if k in inst}
            try:
                w = weight_fn(day, past) or {}
            except Exception as e:
                log.info("비중 계산 실패 %s: %s", day.date(), e)
                return
            value = self._value()
            self.rebal.append({"date": str(day.date()), "w": {k: round(float(v), 4) for k, v in w.items() if v > 0.001}})
            orders = []
            for k, i in inst.items():
                px = self.last.get(k)
                if not px:
                    continue
                target = int(value * 0.995 * float(w.get(k, 0)) / px)   # 수수료 몫 0.5% 남김
                cur = int(float(self.portfolio.net_position(i.id)))
                d = target - cur
                if d:
                    orders.append((d, i))
            for d, i in sorted(orders, key=lambda x: x[0]):          # 파는 주문 먼저 (현금 마련)
                o = self.order_factory.market(instrument_id=i.id, order_side=OrderSide.BUY if d > 0 else OrderSide.SELL,
                                              quantity=Quantity.from_int(abs(d)), time_in_force=TimeInForce.GTC)
                self.submit_order(o)

    strat = Rebalance()
    engine.add_strategy(strat)
    engine.run()
    try:
        fills = engine.trader.generate_order_fills_report()
        n = int(len(fills))
    except Exception:
        n = 0
    acct = engine.portfolio.account(venue)
    fees = 0.0
    try:
        fees = abs(float(sum(float(c.as_double()) for c in acct.commissions().values())))
    except Exception:
        pass
    out = {"curve": strat.curve, "trades": n, "fees": round(fees, 2), "rebalances": strat.rebal[-12:],
           "final": strat.curve[-1][1] if strat.curve else START_CASH, "start_cash": START_CASH, "fee_rate": float(fee)}
    engine.dispose()
    return out


def _bars(bt, inst, df: pd.DataFrame) -> list:
    """일봉 표 → Nautilus Bar 목록. (pandas 3의 읽기 전용 배열 때문에 BarDataWrangler 대신 직접 만들어요)"""
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.objects import Price, Quantity
    out = []
    for ts, o, h, l, c, v in zip(df.index, df["open"], df["high"], df["low"], df["close"], df["volume"]):
        hi, lo = max(h, o, c), min(l, o, c)
        ns = int(pd.Timestamp(ts).value)
        out.append(Bar(bt, Price(round(float(o), 2), 2), Price(round(float(hi), 2), 2), Price(round(float(lo), 2), 2),
                       Price(round(float(c), 2), 2), Quantity(max(float(v or 0), 1.0), 0), ns, ns))
    return out


def stats(curve: list[list]) -> dict:
    """누적 수익·연 변동성·샤프·최대 낙폭 (일 단위 평가액으로)."""
    if not curve or len(curve) < 5:
        return {}
    s = pd.Series([c[1] for c in curve], index=pd.to_datetime([c[0] for c in curve]))
    r = s.pct_change().dropna()
    ann = 252
    vol = float(r.std() * ann ** 0.5)
    ret = float(s.iloc[-1] / s.iloc[0] - 1)
    yrs = max((s.index[-1] - s.index[0]).days / 365.25, 1 / 365)
    cagr = (1 + ret) ** (1 / yrs) - 1 if ret > -1 else -1
    mdd = float((s / s.cummax() - 1).min())
    sharpe = float(r.mean() / r.std() * ann ** 0.5) if r.std() > 0 else None
    return {"ret": round(ret * 100, 2), "cagr": round(cagr * 100, 2), "vol": round(vol * 100, 2), "mdd": round(mdd * 100, 2),
            "sharpe": None if sharpe is None else round(sharpe, 2), "days": len(s)}
