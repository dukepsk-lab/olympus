"""End-to-end research pipeline.

    python scripts/run_research.py --config config/default.yaml --symbol XAUUSD

ingest -> features -> label-aware backtest -> CPCV/DSR/PBO validation ->
regime-bucketed walk-forward -> PromotionGate -> net-of-cost report with a
PROMOTED/REJECTED verdict.

All three strategy families (trend, breakout, gated reversion) run through the
SAME gate. Swapping ``data.source`` to csv/mt5 in the config requires no code
change here.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from xau import set_global_seed
from xau.config import Config, load_config
from xau.data.news import make_synthetic_calendar
from xau.data.source import make_source
from xau.features.breakout import opening_range_breakout
from xau.features.regime import RegimeClassifier
from xau.features.reversion import reversion_signal
from xau.features.trend import tsmom_signal
from xau.backtest.engine import run_backtest, BacktestResult
from xau.validation.ledger import TrialLedger
from xau.validation.walkforward import regime_bucket_breakdown
from xau.gate import PromotionGate
from xau.mm.money import f_sweep
from xau.mm.portfolio import compute_portfolio_weights
from xau.report.build import build_text_report, save_equity_plot
import numpy as np
import pandas as pd


def _signals_for(strategy: str, df, d1, regime, news_mask, config: Config):
    """Return (signal_frame, params_dict, filters_dict) for a strategy family."""
    if strategy == "trend":
        # Signature records the knobs that ACTUALLY move the trend backtest:
        # lookbacks and the D1 higher-TF filter. (pt_sl/vol_target_annual are
        # inert for trend -- the signal hardcodes its barrier mults -- so they
        # are deliberately excluded to keep the DSR trial count honest.)
        return (tsmom_signal(df, config.features.trend, config.labeling, d1),
                {"lookbacks": list(config.features.trend.lookbacks),
                 "d1_lookbacks": list(config.features.trend.d1_lookbacks)},
                {"d1_overlay": config.data.d1_overlay})
    if strategy == "breakout":
        return (opening_range_breakout(df, config.features.breakout, config.labeling,
                                       config, news_mask),
                {"range_session": config.features.breakout.range_session},
                {"expansion_atr": config.features.breakout.expansion_atr_multiple})
    if strategy == "reversion":
        return (reversion_signal(df, config.features.reversion, config.labeling, regime),
                {"zscore_entry": config.features.reversion.zscore_entry},
                {"regime_gated": config.features.reversion.enabled})
    raise ValueError(f"unknown strategy '{strategy}'")


def run_one(config: Config, source, symbol: str, strategy: str,
            ledger: TrialLedger, gate: PromotionGate,
            f_sweep_result: dict | None, start: str | None,
            end: str | None, starting_equity: float | None = None) -> tuple:
    df = source.load(symbol, config.data.timeframe, start, end)
    d1 = source.load_d1(symbol, start, end) if config.data.d1_overlay else None
    cal = make_synthetic_calendar(
        start or config.data.start or "2020-01-01",
        end or config.data.end or "2025-12-31",
        config.costs.news_window_minutes,
    )
    news_mask = cal.news_mask(df.index)
    regime = RegimeClassifier(config.features.regime).fit(df)

    signal, params, filters = _signals_for(strategy, df, d1, regime, news_mask, config)
    result = run_backtest(df, signal, config, symbol, news_mask=news_mask,
                          starting_equity=starting_equity)
    rb = regime_bucket_breakdown(result, config)
    sr_var = float(np.var(ledger.trial_sharpes(), ddof=1)) if len(ledger.trial_sharpes()) > 1 else 0.0
    gr = gate.evaluate(
        result.bar_returns, result.trade_pnl(), result.trade_r(),
        result.n_trades, ledger.deflation_n_trials(), regime_breakdown=rb,
        sr_variance_across_trials=sr_var,
    )
    ledger.record(params, symbol, config.data.timeframe, filters,
                  metrics={"sharpe": round(gr.evidence.get("sr_hat_perobs", 0), 4),
                           "n_trades": result.n_trades,
                           "net_return": round(result.final_equity / result.starting_equity - 1, 4)},
                  gate_passed=gr.passed, failed_checks=gr.failed_checks,
                  notes=f"{strategy}")
    report = build_text_report(symbol, strategy, result, gr, config,
                               f_sweep=f_sweep_result, regime_breakdown=rb)
    return result, gr, rb, report


def run_portfolio(config: Config, source, strategy: str, ledger: TrialLedger,
                  gate: PromotionGate, f_sweep_result: dict | None,
                  start: str | None, end: str | None) -> tuple:
    """DIVERSIFIED portfolio across the universe (research: diversification is the
    edge). Capital is allocated per symbol by ``money.portfolio_weighting``
    (``equal`` or causal ``inverse_vol`` risk-parity-lite); equity curves are
    summed into one portfolio equity curve and evaluated as a single strategy.

    Per-symbol results are printed; the portfolio verdict is the headline.
    Because sizing is fixed-fractional, each symbol's growth curve is invariant
    to its starting capital, so unequal allocation needs no engine change.
    """
    E0 = config.backtest.starting_equity
    scheme = config.money.portfolio_weighting
    weights = compute_portfolio_weights(
        scheme, config.universe,
        price_loader=lambda s: source.load(s, config.data.timeframe, start, end)["close"],
        window=config.money.weight_vol_window,
    )
    print(f"  weighting: {scheme}  ->  " +
          "  ".join(f"{s} {weights.get(s, 0)*100:.0f}%" for s in config.universe))
    alloc_by_sym = {s: E0 * weights.get(s, 0.0) for s in config.universe}

    per_eq = []
    trade_frames = []
    for sym in config.universe:
        alloc = alloc_by_sym[sym]
        try:
            res, gr, rb, rep = run_one(config, source, sym, strategy, ledger, gate,
                                       None, start, end, starting_equity=alloc)
            per_eq.append(res.equity.rename(sym))
            if not res.trades.empty:
                trade_frames.append(res.trades)
            print(f"  {sym}: {gr.verdict}  (alloc={weights.get(sym,0)*100:.0f}%, "
                  f"n={res.n_trades}, ret={res.final_equity/res.starting_equity-1:+.1%})")
        except Exception as e:  # pragma: no cover
            print(f"  {sym}: skipped ({e})")

    if not per_eq:
        raise RuntimeError("no symbol produced a result for the portfolio")
    # leading NaNs (pre-history) filled with each symbol's OWN allocation
    eq_df = pd.concat(per_eq, axis=1).ffill()
    eq_df = eq_df.fillna({s: alloc_by_sym[s] for s in eq_df.columns})
    port_eq = eq_df.sum(axis=1)
    port_ret = port_eq.pct_change().fillna(0.0)
    trades_df = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    pnl_arr = trades_df["pnl"].to_numpy(float) if len(trades_df) else np.array([])
    r_arr = trades_df["r"].to_numpy(float) if len(trades_df) else np.array([])
    n_trades = int(len(pnl_arr))

    port_result = BacktestResult(
        symbol="PORTFOLIO", trades=trades_df,
        equity=port_eq, withdrawn=pd.Series(0.0, index=port_eq.index),
        total_wealth=port_eq, bar_returns=port_ret,
        starting_equity=float(port_eq.iloc[0]), final_equity=float(port_eq.iloc[-1]),
        n_trades=n_trades,
    )
    rb = regime_bucket_breakdown(port_result, config)
    sr_var = float(np.var(ledger.trial_sharpes(), ddof=1)) if len(ledger.trial_sharpes()) > 1 else 0.0
    gr = gate.evaluate(port_ret, pnl_arr, r_arr, n_trades,
                       ledger.deflation_n_trials(), regime_breakdown=rb,
                       sr_variance_across_trials=sr_var)
    ledger.record({"strategy": strategy, "portfolio": True,
                   "weighting": config.money.portfolio_weighting}, "UNIVERSE",
                  config.data.timeframe, {"symbols": list(config.universe)},
                  metrics={"sharpe": round(gr.evidence.get("sr_hat_perobs", 0), 4),
                           "n_trades": n_trades},
                  gate_passed=gr.passed, failed_checks=gr.failed_checks,
                  notes=f"{strategy} diversified portfolio")
    report = build_text_report("UNIVERSE", f"{strategy} (diversified)",
                               port_result, gr, config,
                               f_sweep=f_sweep_result, regime_breakdown=rb)
    return port_result, gr, rb, report


def main() -> int:
    ap = argparse.ArgumentParser(description="XAU research end-to-end pipeline")
    ap.add_argument("--config", default="config/default.yaml")
    ap.add_argument("--symbol", default="XAUUSD",
                    help="focal symbol (or 'universe' to run trend across all)")
    ap.add_argument("--strategies", default="trend,breakout,reversion",
                    help="comma-separated subset of {trend,breakout,reversion}")
    ap.add_argument("--ledger", default="trial_ledger.jsonl")
    ap.add_argument("--report-dir", default="reports")
    ap.add_argument("--weighting", choices=("equal", "inverse_vol"), default=None,
                    help="override money.portfolio_weighting for the universe basket")
    args = ap.parse_args()

    config = load_config(args.config)
    if args.weighting is not None:
        import dataclasses
        config = dataclasses.replace(
            config, money=dataclasses.replace(config.money,
                                              portfolio_weighting=args.weighting))
    set_global_seed(config.seed)
    source = make_source(config)
    ledger = TrialLedger(args.ledger)
    gate = PromotionGate(config)
    start, end = config.data.start, config.data.end
    out_dir = Path(args.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # f-sweep once (isolates the sizing lever; research section 4b)
    sweep = f_sweep(
        principal=config.backtest.starting_equity,
        f_values=config.money.f_sweep_values,
        n_paths=4000, ruin_level=config.money.ruin_level, seed=config.seed,
    )

    print(f"\n=== XAU Research System  |  source={config.data.source}  "
          f"tf={config.data.timeframe}  seed={config.seed} ===")
    print(f"TrialLedger: {args.ledger}  (n_trials now drives DSR)\n")

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    if args.symbol.lower() == "universe":
        # DIVERSIFIED portfolio -- where the research says the edge actually lives.
        print("--- Universe diversified trend (research: diversification is the edge) ---")
        pres, pgr, prb, prep = run_portfolio(config, source, "trend", ledger, gate,
                                             sweep, start, end)
        print(prep)
        save_equity_plot(pres, pgr, out_dir / "PORTFOLIO_trend.png",
                         title="UNIVERSE trend (diversified)")
    else:
        for strat in strategies:
            res, gr, rb, rep = run_one(config, source, args.symbol, strat,
                                       ledger, gate, sweep, start, end)
            print(rep)
            save_equity_plot(res, gr, out_dir / f"{args.symbol}_{strat}.png",
                             title=f"{args.symbol} {strat}")
            print()

    print(f"Done. Reports/plots in {out_dir}/ . Distinct trials: "
          f"{ledger.n_unique_signatures()} (rows logged: {ledger.n_trials}).")
    print("Reminder: nothing here guarantees profit. PROMOTED/REJECTED only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
