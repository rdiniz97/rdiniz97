"""Sanity tests for the engine on synthetic prices (not market results)."""
import numpy as np
import pandas as pd

from backtest import Config, Fees, run, signals


def make(prices):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="h", tz="UTC")
    p = np.asarray(prices, float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p}, index=idx)


def test_one_round_trip_pnl_and_fees():
    p = np.r_[np.full(250, 100.0), np.linspace(100, 200, 300), np.linspace(200, 50, 400)]
    df = make(p)
    cfg = Config(fast=5, slow=20, initial_capital=10_000, multiplier=10, contracts=2,
                 fees=Fees(commission_per_contract=1.0, slippage_ticks=1, tick_size=0.1))
    res = run(df, cfg)
    tr = res["trades"]
    assert len(tr) == 1
    t = tr.iloc[0]
    assert t.fees == t.contracts * 2 * (1.0 + 1.0)
    assert np.isclose(t.net_pnl, t.contracts * (t.exit - t.entry) * 10 - t.fees)
    assert np.isclose(res["equity"].iloc[-1], 10_000 + t.net_pnl)


def test_fill_is_next_bar_open():
    p = np.r_[np.full(30, 100.0), np.arange(101, 140)]
    df = make(p)
    df["open"] = df["close"] - 0.5
    sig = signals(df["close"], 5, 20)
    cross_bar = sig.index[sig.cross_up][0]
    res = run(df, Config(fast=5, slow=20, multiplier=1))
    entry = res["open_trade"]
    nxt = df.index[df.index.get_loc(cross_bar) + 1]
    assert entry["entry_time"] == str(nxt) and entry["entry"] == df.loc[nxt, "open"]


def test_no_trade_without_cross():
    res = run(make(np.linspace(100, 200, 500)), Config(fast=5, slow=20))
    assert len(res["trades"]) == 0 and res["open_trade"] is None


def test_equity_sizing_is_unleveraged():
    p = np.r_[np.full(250, 100.0), np.linspace(100, 200, 300), np.linspace(200, 50, 400)]
    res = run(make(p), Config(fast=5, slow=20, sizing="equity", multiplier=10,
                              fees=Fees(commission_per_contract=0, slippage_ticks=0)))
    t = res["trades"].iloc[0]
    assert np.isclose(t.contracts * t.entry * 10, 10_000)
