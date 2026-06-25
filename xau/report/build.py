"""Report builder -- per-strategy, net-of-cost, with mandatory DSR/PBO context.

Never present a result without its DSR/PBO context and a PROMOTED/REJECTED stamp.
The f-sweep makes the money-management tradeoff explicit (ruin rises steeply +
convexly with f; median terminal wealth rises sub-linearly).
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..backtest.engine import BacktestResult  # noqa: E402
from ..gate import GateResult  # noqa: E402
from ..metrics.perf import compute_performance  # noqa: E402
from ..config import Config  # noqa: E402


def _line(label: str, value, fmt: str = "{:>14,.4f}") -> str:
    return f"  {label:<34s} {fmt.format(value)}"


def build_text_report(symbol: str, strategy: str, result: BacktestResult,
                      gate_result: GateResult, config: Config,
                      f_sweep: dict | None = None,
                      regime_breakdown: dict | None = None) -> str:
    """Return a printable text report. All metrics are NET of cost."""
    ann = config.backtest.annual_bars
    perf = compute_performance(result.bar_returns.to_numpy(),
                               result.trade_pnl(), result.trade_r(), ann)
    ev = gate_result.evidence
    stamp = "=" * 78
    lines = [stamp,
             f"  {symbol}  |  strategy: {strategy}  |  timeframe: {config.data.timeframe}",
             f"  >>> VERDICT: {gate_result.verdict} <<<",
             ""]
    if gate_result.failed_checks:
        lines.append("  Failed checks (no auto-retune -- a fail is a fail):")
        for fc in gate_result.failed_checks:
            lines.append(f"    - {fc}")
        lines.append("")

    lines.append("  -- Net trade metrics (after spread + commission + slippage) --")
    lines.append(_line("net trades", perf.n_trades, "{:>14,d}"))
    lines.append(_line("net return (%)", perf.net_return * 100, "{:>14,.2f}"))
    lines.append(_line("Sharpe (ann.)", perf.sharpe))
    lines.append(_line("Sortino (ann.)", perf.sortino))
    lines.append(_line("Calmar", perf.calmar))
    lines.append(_line("max drawdown (%)", perf.max_drawdown * 100, "{:>14,.2f}"))
    lines.append(_line("profit factor", perf.profit_factor))
    lines.append(_line("win rate (%)", perf.win_rate * 100, "{:>14,.2f}"))
    lines.append(_line("expectancy (R)", perf.expectancy_r))
    lines.append(_line("recovery factor", perf.recovery_factor))
    lines.append(_line("t-stat (mean return)", perf.t_stat))
    lines.append("")

    lines.append("  -- Validation context (MANDATORY -- no result is meaningful without) --")
    lines.append(_line("DSR (skill prob, deflated)", ev.get("dsr", 0.0)))
    lines.append(_line("n_trials used for DSR", ev.get("n_trials", 0), "{:>14,d}"))
    lines.append(_line("PBO (overfit probability)", ev.get("pbo", 0.0)))
    lines.append(_line("per-obs Sharpe (sr_hat)", ev.get("sr_hat_perobs", 0.0)))
    ps = ev.get("cpcv_path_sharpe_median", 0.0)
    lines.append(_line("CPCV path Sharpe (median)", ps))
    lines.append(_line("CPCV paths positive (%)",
                       ev.get("cpcv_positive_frac", 0.0) * 100, "{:>14,.2f}"))
    lines.append(_line("CPCV n paths", ev.get("cpcv_n_paths", 0), "{:>14,d}"))
    lines.append(_line("median Calmar (paths)", ev.get("median_calmar_paths", 0.0)))
    lines.append("")

    if regime_breakdown:
        lines.append("  -- Regime buckets (edge must persist across regimes) --")
        lines.append(f"  {'bucket':<16s}{'trades':>8s}{'net_pnl':>12s}{'sharpe':>9s}{'profit':>9s}")
        for name, d in regime_breakdown.items():
            lines.append(f"  {name:<16s}{d['n_trades']:>8d}{d['net_pnl']:>12,.0f}"
                         f"{d['sharpe']:>9.2f}{'YES' if d['profitable'] else 'no':>9s}")
        lines.append("")

    if f_sweep:
        lines.append("  -- f-sweep: the ruin-vs-sizing tradeoff (no withdrawal) --")
        lines.append(f"  {'f%':>5s}{'P(ruin)':>10s}{'med maxDD':>11s}"
                     f"{'med terminal':>14s}{'mean terminal':>14s}")
        for f in sorted(f_sweep):
            d = f_sweep[f]
            lines.append(f"  {f*100:>4.2f}{d['p_ruin']*100:>9.1f}{d['median_max_dd']*100:>10.1f}"
                         f"{d['median_terminal']:>14,.0f}{d['mean_terminal']:>14,.0f}")
        lines.append("  (ruin rises convexly with f; median wealth rises sub-linearly)")
        lines.append("")

    lines.append(f"  starting equity: {result.starting_equity:,.0f}  "
                 f"final: {result.final_equity:,.0f}  "
                 f"banked (withdrawn): {result.withdrawn.iloc[-1]:,.0f}  "
                 f"ruin: {result.ruin}")
    lines.append("  NOTE: nothing here guarantees profit. Verdict vocabulary is "
                 "PROMOTED/REJECTED with evidence.")
    lines.append(stamp)
    return "\n".join(lines)


def save_equity_plot(result: BacktestResult, gate_result: GateResult,
                     out_path: str | Path, title: str = "") -> None:
    """Save the equity + withdrawn-cash curve with the verdict stamped."""
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(result.equity.index, result.equity, label="active equity", lw=1.1)
    ax.plot(result.total_wealth.index, result.total_wealth,
            label="total wealth (active + banked)", lw=1.0, alpha=0.8)
    ax.fill_between(result.withdrawn.index, result.equity, result.total_wealth,
                    color="grey", alpha=0.18, label="banked cash")
    ax.axhline(result.starting_equity, color="k", ls=":", lw=0.8)
    stamp = f"{gate_result.verdict}"
    ax.set_title(f"{title or result.symbol}  --  {stamp}", fontsize=12)
    ax.set_xlabel("time")
    ax.set_ylabel("wealth")
    ax.legend(fontsize=8.5, loc="upper left")
    ax.grid(alpha=0.25)
    plt.tight_layout()
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)


__all__ = ["build_text_report", "save_equity_plot"]
