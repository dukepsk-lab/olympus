"""Event-driven backtest engine over bid/ask bars.

Timing contract (NO LOOK-AHEAD):
  * The signal at bar *t* (decided from data <= bar *t* close) is acted on at the
    OPEN of bar *t+1* via :func:`xau.backtest.fills.fill_price` on the correct
    side of the book. Signals never fill within their own bar.
  * A position is held under triple barriers (profit-take, stop, vertical) and
    exits at the FIRST touch. Exit fills ALSO pay the spread + slippage on the
    correct side (a stop-hit sells at the bid, not mid). Commission is charged on
    both entry and exit.
  * One position at a time per symbol (no pyramiding); a new signal while in a
    trade is ignored until the trade exits at a barrier. This matches the
    triple-barrier labelling philosophy.

All PnL is NET of cost by construction (fills carry spread+slip; commission is
added). Mark-to-market equity (realized + unrealized) drives drawdown/Sharpe so
open-trade excursion is reflected. The correlated-risk cap is applied at the
portfolio layer (see :func:`xau.mm.money.correlated_risk_cap`); this engine runs
one symbol at a time.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Config
from ..costs.model import CostModel
from .fills import fill_price


@dataclass
class BacktestResult:
    symbol: str
    trades: pd.DataFrame
    equity: pd.Series          # active-account mark-to-market equity (per bar)
    withdrawn: pd.Series       # cash banked to the safe bucket (per bar)
    total_wealth: pd.Series    # equity + withdrawn (per bar)
    bar_returns: pd.Series     # per-bar returns of total active equity
    starting_equity: float
    final_equity: float
    ruin: bool = False
    n_trades: int = 0

    def trade_pnl(self) -> np.ndarray:
        return self.trades["pnl"].to_numpy() if len(self.trades) else np.array([])

    def trade_r(self) -> np.ndarray:
        return self.trades["r"].to_numpy() if len(self.trades) else np.array([])


def run_backtest(df: pd.DataFrame, signal: pd.DataFrame, config: Config,
                 symbol: str, news_mask: pd.Series | None = None,
                 cost_model: CostModel | None = None,
                 starting_equity: float | None = None) -> BacktestResult:
    """Run a single-symbol net-of-cost backtest over a signal frame."""
    cm = cost_model or CostModel.from_config(config)
    spec = config.symbols[symbol]
    point = spec.point
    # contract_size = $ value of a 1.0 price-unit move, per lot. This is the
    # correct price->dollar multiplier for PnL and risk (NOT point_value, which
    # is $/POINT and is used only by the cost model for spread). A 100x error
    # here would make commission swamp a real edge -- hence the explicit comment.
    cs = spec.contract_size
    slip = spec.slippage_points
    risk_fraction = config.money.risk_fraction
    ruin_level = config.money.ruin_level
    pt_mult, sl_mult = config.labeling.pt_sl
    max_hold = config.labeling.max_holding_bars
    from ..mm.money import position_size, WithdrawalPolicy
    wpolicy = WithdrawalPolicy.from_config(config.money)
    # signal-level profit-take override (trend lets winners run; see features/trend).
    # The stop side needs no override here: stop_distance already encodes sl_mult
    # (= sl_mult * vol * price), and the engine stops off stop_distance directly.
    sig_pt = signal["pt_mult"].to_numpy(float) if "pt_mult" in signal else None

    start_eq = float(starting_equity if starting_equity is not None
                     else config.backtest.starting_equity)
    principal = start_eq

    idx = df.index
    op = df["open"].to_numpy(float)
    hi = df["high"].to_numpy(float)
    lo = df["low"].to_numpy(float)
    cl = df["close"].to_numpy(float)
    side_sig = signal["side"].to_numpy(int)
    conv = signal["conviction"].to_numpy(float)
    sig_vol = signal["vol"].to_numpy(float)
    news = (news_mask.reindex(idx).fillna(False).to_numpy(bool)
            if news_mask is not None else np.zeros(len(idx), dtype=bool))
    # Real per-bar spread (POINTS) if the feed carries it; else None -> the cost
    # model falls back to base_spread * session/news multipliers.
    real_spread = df["spread"].to_numpy(float) if "spread" in df.columns else None
    n = len(idx)

    # per-bar accounting
    realized = start_eq
    withdrawn_total = 0.0
    eq_curve = np.full(n, np.nan)
    wd_curve = np.full(n, np.nan)
    ruin = False
    trade_rows: list[dict] = []
    trade_count = 0

    # open position state
    in_pos = False
    p_side = 0
    p_entry = 0.0
    p_lots = 0.0
    p_stop = 0.0
    p_target = 0.0
    p_vert_i = -1
    p_entry_i = -1
    p_entry_comm = 0.0
    p_risk_dollars = 0.0
    pending_side = 0          # entry scheduled for the NEXT bar's open

    for t in range(n):
        ts = idx[t]
        sp_t = real_spread[t] if real_spread is not None else None

        # (1) fill a pending entry at bar t OPEN (signal was decided at t-1 close)
        if not in_pos and pending_side != 0 and realized > 0:
            bid, ask = cm.bid_ask(op[t], symbol, ts, bool(news[t]), sp_t)
            entry_fill = fill_price(pending_side, bid, ask, slip, point)
            sd = signal["stop_distance"].iloc[t - 1] if t > 0 else np.nan
            vol_e = sig_vol[t - 1] if t > 0 else np.nan
            if not np.isfinite(sd) or sd <= 0:
                pending_side = 0
            else:
                eff_risk = risk_fraction * float(conv[t - 1]) if t > 0 else risk_fraction
                eff_risk = max(eff_risk, 1e-9)
                lots = position_size(realized, sd, cs, eff_risk)
                entry_comm = cm.commission_dollars(symbol, lots, sides=1)
                realized -= entry_comm
                p_side = pending_side
                p_entry = entry_fill
                p_lots = lots
                p_stop = entry_fill - p_side * sd
                ptm = (sig_pt[t - 1] if (sig_pt is not None and t > 0 and np.isfinite(sig_pt[t - 1]))
                       else pt_mult)
                p_target = entry_fill + p_side * (ptm * vol_e * op[t - 1]) \
                    if (t > 0 and np.isfinite(vol_e)) else entry_fill + p_side * sd
                p_vert_i = t + max_hold
                p_entry_i = t
                p_entry_comm = entry_comm
                p_risk_dollars = sd * lots * cs
                in_pos = True
                pending_side = 0

        # (2) manage open position against bar t (touches)
        if in_pos:
            touched = False
            exit_fill = np.nan
            reason = ""
            # stop first (pessimistic) then target then vertical
            if p_side > 0:  # long
                if lo[t] <= p_stop:
                    bid, ask = cm.bid_ask(p_stop, symbol, ts, bool(news[t]), sp_t)
                    exit_fill = fill_price(-1, bid, ask, slip, point)
                    touched, reason = True, "stop"
                elif hi[t] >= p_target:
                    bid, ask = cm.bid_ask(p_target, symbol, ts, bool(news[t]), sp_t)
                    exit_fill = fill_price(-1, bid, ask, slip, point)
                    touched, reason = True, "target"
            else:  # short
                if hi[t] >= p_stop:
                    bid, ask = cm.bid_ask(p_stop, symbol, ts, bool(news[t]), sp_t)
                    exit_fill = fill_price(+1, bid, ask, slip, point)
                    touched, reason = True, "stop"
                elif lo[t] <= p_target:
                    bid, ask = cm.bid_ask(p_target, symbol, ts, bool(news[t]), sp_t)
                    exit_fill = fill_price(+1, bid, ask, slip, point)
                    touched, reason = True, "target"
            if not touched and t >= p_vert_i:
                bid, ask = cm.bid_ask(cl[t], symbol, ts, bool(news[t]), sp_t)
                exit_fill = fill_price(-p_side, bid, ask, slip, point)
                touched, reason = True, "vertical"
            if touched:
                exit_comm = cm.commission_dollars(symbol, p_lots, sides=1)
                pnl_gross = p_side * (exit_fill - p_entry) * p_lots * cs
                pnl = pnl_gross - exit_comm
                realized += pnl
                r_mult = (p_side * (exit_fill - p_entry) * p_lots * cs) / p_risk_dollars \
                    if p_risk_dollars > 0 else 0.0
                trade_count += 1
                trade_rows.append({
                    "entry_time": idx[p_entry_i], "exit_time": ts,
                    "side": p_side, "entry": p_entry, "exit": exit_fill,
                    "lots": p_lots, "pnl": pnl, "r": r_mult,
                    "reason": reason, "entry_comm": p_entry_comm,
                    "exit_comm": exit_comm, "news_exit": bool(news[t]),
                })
                # withdrawal overlay (cash-locking; does not change risk_fraction)
                realized, _, withdrawn_total = wpolicy.step(
                    realized, realized, withdrawn_total, principal, trade_count
                )
                in_pos = False
                if realized <= ruin_level * start_eq:
                    ruin = True

        # (3) decide a NEW pending entry from signal[t] (fills at t+1 open)
        if not in_pos and side_sig[t] != 0 and np.isfinite(sig_vol[t]) and realized > 0:
            pending_side = int(side_sig[t])

        # mark-to-market equity for the curve
        unrealized = (p_side * (cl[t] - p_entry) * p_lots * cs) if in_pos else 0.0
        eq_curve[t] = realized + unrealized
        wd_curve[t] = withdrawn_total

    eq_s = pd.Series(eq_curve, index=idx, name="equity").ffill().fillna(start_eq)
    wd_s = pd.Series(wd_curve, index=idx, name="withdrawn").ffill().fillna(0.0)
    total_s = (eq_s + wd_s).rename("total_wealth")
    bar_returns = eq_s.pct_change().fillna(0.0)
    trades = pd.DataFrame(trade_rows)
    return BacktestResult(
        symbol=symbol,
        trades=trades,
        equity=eq_s,
        withdrawn=wd_s,
        total_wealth=total_s,
        bar_returns=bar_returns,
        starting_equity=start_eq,
        final_equity=float(eq_s.iloc[-1]),
        ruin=ruin,
        n_trades=len(trades),
    )


__all__ = ["BacktestResult", "run_backtest"]
