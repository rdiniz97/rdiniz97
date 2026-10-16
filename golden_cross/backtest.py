"""Golden cross (SMA 50/200), long only, on gold futures 1h bars.

Rules
  * Enter long when SMA(50) crosses above SMA(200) (evaluated on bar close).
  * Exit when SMA(50) crosses back below SMA(200).
  * No stop loss, no take profit.
  * Fills happen at the OPEN of the bar after the signal (no look-ahead).

Sizing
  * "fixed" (default): a fixed number of contracts, 1 micro gold (MGC, 10 oz)
    on the GC price series. A $10k account cannot hold even one MGC unleveraged
    (~$19k notional in Oct 2023), so this is a leveraged futures position, as a
    real $10k futures account would trade it.
  * "equity": fractional contracts worth 100% of current equity (unleveraged,
    a theoretical benchmark; fees are charged pro rata).

Usage
  python backtest.py data.csv [--start 2023-10-01 --end 2026-10-01]
CSV needs a datetime column (time/datetime/date/timestamp, unix seconds or ISO)
and open/high/low/close columns, e.g. a TradingView export of COMEX:GC1! 1h.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass
class Fees:
    # Placeholder per-side costs; replace with the CoinQuant fee schedule.
    commission_per_contract: float = 1.00   # USD per side (micro gold retail all-in)
    slippage_ticks: float = 1.0             # ticks per side
    tick_size: float = 0.10                 # GC/MGC tick in USD/oz


@dataclass
class Config:
    fast: int = 50
    slow: int = 200
    initial_capital: float = 10_000.0
    multiplier: float = 10.0                # 10 = MGC, 100 = GC
    sizing: str = "fixed"                   # "fixed" or "equity"
    contracts: float = 1
    fees: Fees = field(default_factory=Fees)


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(c for c in ("time", "datetime", "date", "timestamp") if c in df.columns)
    t = df[tcol]
    if np.issubdtype(t.dtype, np.number):
        unit = "ms" if t.abs().max() > 1e11 else "s"
        idx = pd.to_datetime(t, unit=unit, utc=True)
    else:
        idx = pd.to_datetime(t, utc=True)
    out = df[["open", "high", "low", "close"]].astype(float)
    out.index = idx
    out = out[~out.index.duplicated()].sort_index()
    return out.dropna()


def signals(close: pd.Series, fast: int, slow: int) -> pd.DataFrame:
    f = close.rolling(fast).mean()
    s = close.rolling(slow).mean()
    above = f > s
    prev = above.shift(1, fill_value=False)
    valid = s.notna() & s.shift(1).notna()
    return pd.DataFrame({
        "sma_fast": f,
        "sma_slow": s,
        "cross_up": valid & above & ~prev,
        "cross_dn": valid & ~above & prev,
    })


def run(df: pd.DataFrame, cfg: Config, start=None, end=None) -> dict:
    sig = signals(df["close"], cfg.fast, cfg.slow)  # SMAs warm up on pre-start data
    if start is not None:
        mask = df.index >= pd.Timestamp(start, tz="UTC")
        df, sig = df[mask], sig[mask]
    if end is not None:
        mask = df.index < pd.Timestamp(end, tz="UTC")
        df, sig = df[mask], sig[mask]
    if len(df) < 2:
        raise ValueError("not enough bars in the selected window")

    fe = cfg.fees
    cost_per_side = fe.commission_per_contract + fe.slippage_ticks * fe.tick_size * cfg.multiplier

    opens, closes = df["open"].to_numpy(), df["close"].to_numpy()
    up, dn = sig["cross_up"].to_numpy(), sig["cross_dn"].to_numpy()
    idx = df.index

    cash = cfg.initial_capital
    qty, entry_px, entry_t, entry_cost = 0.0, 0.0, None, 0.0
    pending = None  # "buy" / "sell", filled at next bar's open
    trades, equity = [], np.empty(len(df))

    for i in range(len(df)):
        if pending == "buy" and qty == 0:
            if cfg.sizing == "fixed":
                n = cfg.contracts
            else:
                n = cash / (opens[i] * cfg.multiplier + cost_per_side)
            if n > 0 and cash > 0:
                qty, entry_px, entry_t = n, opens[i], idx[i]
                entry_cost = n * cost_per_side
                cash -= entry_cost
        elif pending == "sell" and qty > 0:
            exit_cost = qty * cost_per_side
            gross = qty * (opens[i] - entry_px) * cfg.multiplier
            cash += gross - exit_cost
            trades.append({
                "entry_time": str(entry_t), "exit_time": str(idx[i]),
                "contracts": qty, "entry": entry_px, "exit": opens[i],
                "gross_pnl": gross, "fees": entry_cost + exit_cost,
                "net_pnl": gross - entry_cost - exit_cost,
                "bars_held": int(idx.get_loc(idx[i]) - idx.get_loc(entry_t)),
            })
            qty = 0
        pending = None
        if up[i] and qty == 0:
            pending = "buy"
        elif dn[i] and qty > 0:
            pending = "sell"
        equity[i] = cash + qty * (closes[i] - entry_px) * cfg.multiplier

    open_trade = None
    if qty > 0:  # mark-to-market, closing fee included in final equity
        exit_cost = qty * cost_per_side
        gross = qty * (closes[-1] - entry_px) * cfg.multiplier
        equity[-1] -= exit_cost
        open_trade = {"entry_time": str(entry_t), "contracts": qty, "entry": entry_px,
                      "mark": closes[-1], "unrealized_net": gross - entry_cost - exit_cost}

    eq = pd.Series(equity, index=idx)
    return {"equity": eq, "trades": pd.DataFrame(trades), "open_trade": open_trade,
            "stats": stats(eq, pd.DataFrame(trades), df, cfg), "signals": sig}


def stats(eq: pd.Series, tr: pd.DataFrame, df: pd.DataFrame, cfg: Config) -> dict:
    init = cfg.initial_capital
    years = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    dd = eq / eq.cummax() - 1
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    bh = df["close"].iloc[-1] / df["open"].iloc[0] - 1
    s = {
        "start": str(eq.index[0]), "end": str(eq.index[-1]), "bars": len(eq),
        "initial_capital": init, "final_equity": round(float(eq.iloc[-1]), 2),
        "net_profit": round(float(eq.iloc[-1] - init), 2),
        "total_return_pct": round(float(eq.iloc[-1] / init - 1) * 100, 2),
        "cagr_pct": round(((eq.iloc[-1] / init) ** (1 / years) - 1) * 100, 2) if years > 0 and eq.iloc[-1] > 0 else None,
        "max_drawdown_pct": round(float(dd.min()) * 100, 2),
        "sharpe_daily_ann": round(float(daily.mean() / daily.std() * np.sqrt(252)), 2) if daily.std() > 0 else None,
        "buy_and_hold_return_pct": round(bh * 100, 2),
        "closed_trades": len(tr),
    }
    if len(tr):
        wins, losses = tr[tr.net_pnl > 0], tr[tr.net_pnl <= 0]
        s.update({
            "win_rate_pct": round(len(wins) / len(tr) * 100, 2),
            "profit_factor": round(wins.net_pnl.sum() / -losses.net_pnl.sum(), 2) if losses.net_pnl.sum() < 0 else None,
            "avg_trade": round(float(tr.net_pnl.mean()), 2),
            "best_trade": round(float(tr.net_pnl.max()), 2),
            "worst_trade": round(float(tr.net_pnl.min()), 2),
            "total_fees": round(float(tr.fees.sum()), 2),
            "avg_bars_held": round(float(tr.bars_held.mean()), 1),
        })
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--start", default="2023-10-01")
    ap.add_argument("--end", default="2026-10-01")
    ap.add_argument("--capital", type=float, default=10_000)
    ap.add_argument("--multiplier", type=float, default=10, help="10=MGC, 100=GC")
    ap.add_argument("--sizing", choices=["fixed", "equity"], default="fixed")
    ap.add_argument("--contracts", type=float, default=1, help="contracts for fixed sizing")
    ap.add_argument("--commission", type=float, default=1.00, help="USD per contract per side")
    ap.add_argument("--slippage-ticks", type=float, default=1.0)
    ap.add_argument("--out", default="results")
    a = ap.parse_args()

    cfg = Config(initial_capital=a.capital, multiplier=a.multiplier,
                 sizing=a.sizing, contracts=a.contracts,
                 fees=Fees(commission_per_contract=a.commission, slippage_ticks=a.slippage_ticks))
    res = run(load_csv(a.csv), cfg, a.start, a.end)

    out = Path(a.out); out.mkdir(exist_ok=True)
    res["trades"].to_csv(out / "trades.csv", index=False)
    res["equity"].rename("equity").to_csv(out / "equity.csv")
    summary = {"config": asdict(cfg), "stats": res["stats"], "open_trade": res["open_trade"]}
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 4))
        res["equity"].plot(ax=ax, lw=1.2)
        ax.set_title("Golden cross 50/200 — gold 1h — equity (USD)"); ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(out / "equity.png", dpi=120)
    except ImportError:
        pass
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
