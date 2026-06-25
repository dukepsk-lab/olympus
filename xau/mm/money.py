"""Money management -- TWO SEPARATE roles (research section 4):

  1. position_size() = the RUIN lever. Anti-Martingale fixed-fractional sizing:
     lots scale ONLY with current equity, so size shrinks in drawdowns and never
     chases losses. The per-trade risk fraction ``f`` is what controls risk of
     ruin (steep + convex in f); withdrawal does NOT.
  2. WithdrawalPolicy   = the CASH-LOCKING / wealth-variance lever. It banks
     irreversible cash and lifts the downside floor of TOTAL wealth, but under
     fixed-fractional sizing it does NOT reduce the active account's % drawdown
     (which is scale-free). wd_share is deliberately decoupled from f.

Also: a correlated-risk cap (XAUUSD/US30/BTCUSD cluster in risk-off), and an
``f_sweep`` Monte Carlo reproducing the ruin-vs-f tradeoff from the research.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .. import make_rng
from ..config import MoneyConfig


def position_size(equity: float, stop_distance_price: float, point_value: float,
                  risk_fraction: float) -> float:
    """Vol-targeted fixed-fractional sizing.

    Lots such that ``stop_distance_price * lots * point_value == risk_fraction * equity``.

    ``point_value`` here is the **$ value of a 1.0 price-unit move per lot** ==
    ``SymbolSpec.contract_size`` (e.g. 100 for XAUUSD: a $1 gold move = $100/lot).
    Do NOT confuse with ``SymbolSpec.point_value`` ($/POINT), which the cost model
    uses for spread. Passing the wrong multiplier silently breaks the risk
    equation by ~contract_size/point (e.g. 100x for gold).

    Anti-Martingale: scales with ``equity`` only, so exposure falls in drawdowns
    and NEVER increases after a loss beyond what the equity change implies.
    """
    if equity <= 0.0 or stop_distance_price <= 0.0 or point_value <= 0.0:
        return 0.0
    f = float(risk_fraction)
    if f <= 0.0:
        return 0.0
    lots = (f * equity) / (stop_distance_price * point_value)
    return float(max(lots, 0.0))


@dataclass
class WithdrawalPolicy:
    wd_share: float = 0.40
    cadence_trades: int = 17
    house_money_multiple: float = 2.0

    @classmethod
    def from_config(cls, m: MoneyConfig) -> "WithdrawalPolicy":
        return cls(wd_share=m.withdrawal.wd_share,
                   cadence_trades=m.withdrawal.cadence_trades,
                   house_money_multiple=m.withdrawal.house_money_multiple)

    def step(self, equity: float, hwm: float, withdrawn: float, principal: float,
             trade_count: int) -> tuple[float, float, float]:
        """Apply withdrawal for one step. Returns (new_equity, new_hwm, new_withdrawn).

        Moves cash to a SAFE bucket; does NOT alter risk_fraction. House-money:
        once total wealth >= ``house_money_multiple`` * principal, top up the
        banked amount to the original principal.
        """
        take = 0.0
        total = equity + withdrawn
        # 1) house-money: bank the original principal once total is large enough
        if principal > 0 and total >= self.house_money_multiple * principal and withdrawn < principal:
            take += (principal - withdrawn)
        # 2) HWM ratchet on cadence: withdraw wd_share of gains above the peak
        if self.cadence_trades > 0 and trade_count > 0 and \
                trade_count % self.cadence_trades == 0:
            gain = max(0.0, equity - hwm)
            take += self.wd_share * gain
        take = min(take, max(equity, 0.0))  # never withdraw more than active equity
        new_equity = equity - take
        new_withdrawn = withdrawn + take
        new_hwm = max(hwm, new_equity)
        return new_equity, new_hwm, new_withdrawn


def correlated_risk_cap(open_risk: dict[str, float], equity: float,
                       risk_fraction: float, cap_multiple: float,
                       groups: Iterable[Iterable[str]]) -> dict[str, float]:
    """Cap total simultaneous risk across positively-correlated groups.

    ``open_risk`` maps symbol -> risk in $ currently committed. The cap is
    ``cap_multiple * single_risk`` per group, where single_risk = f * equity.
    Returns a dict of scaling factors (<=1) per symbol so the group total risk
    fits the cap. Symbols not in any group are untouched (factor 1.0).
    """
    single = risk_fraction * equity if equity > 0 else 0.0
    cap = cap_multiple * single if single > 0 else 0.0
    factors = {sym: 1.0 for sym in open_risk}
    if cap <= 0:
        return factors
    for group in groups:
        members = [s for s in group if s in open_risk and open_risk[s] > 0]
        if len(members) < 2:
            continue
        total_risk = sum(open_risk[s] for s in members)
        if total_risk > cap:
            scale = cap / total_risk
            for s in members:
                factors[s] = min(factors[s], scale)
    return factors


# ---------------------------------------------------------------------------
#  f-sweep Monte Carlo (reproduces the research section-4b ruin-vs-f tradeoff)
# ---------------------------------------------------------------------------
# Regime R-multiples mirror the research MM model (mm_full.py): trend/range/
# crisis weights with low win rate + high payoff (the convexity IS the edge).
_SWEEP_REGIMES = {
    "trend":  dict(p_win=0.40, win_R=2.05, slip_mean=1.03, weight=0.45),
    "range":  dict(p_win=0.35, win_R=1.75, slip_mean=1.05, weight=0.40),
    "crisis": dict(p_win=0.42, win_R=2.60, slip_mean=1.20, weight=0.15),
}


def _draw_R(rng: np.random.Generator, n: int) -> np.ndarray:
    names = list(_SWEEP_REGIMES)
    weights = np.array([_SWEEP_REGIMES[r]["weight"] for r in names], float)
    weights /= weights.sum()
    R = np.empty(n)
    # vectorised per-regime draw
    regime_idx = rng.choice(len(names), size=n, p=weights)
    for ri, rname in enumerate(names):
        rdef = _SWEEP_REGIMES[rname]
        m = regime_idx == ri
        if not m.any():
            continue
        wins = rng.random(int(m.sum())) < rdef["p_win"]
        R_r = np.empty(int(m.sum()))
        sigma = 0.55
        mu = np.log(rdef["win_R"]) - 0.5 * sigma**2
        R_r[wins] = rng.lognormal(mu, sigma, int(wins.sum()))
        n_loss = int((~wins).sum())
        R_r[~wins] = -(1.0 + rng.exponential(rdef["slip_mean"] - 1.0, n_loss))
        R[m] = R_r
    return R


def f_sweep(principal: float = 10_000.0, years: int = 3, trades_per_year: int = 200,
            f_values: Iterable[float] = (0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.04),
            n_paths: int = 5000, ruin_level: float = 0.5,
            seed: int | None = None) -> dict[float, dict]:
    """Monte Carlo ruin-vs-f sweep (no withdrawal; isolates the sizing lever).

    Returns ``{f: {'p_ruin','median_max_dd','median_terminal','mean_terminal'}}``.
    Reproduces the qualitative shape: ruin rises steeply+convexly with f, median
    terminal wealth rises sub-linearly while the mean is dragged up by lottery
    paths -- the over-betting trap.
    """
    rng = make_rng(99) if seed is None else np.random.default_rng(seed)
    n_trades = years * trades_per_year
    out: dict[float, dict] = {}
    for f in f_values:
        eq = np.full(n_paths, float(principal))
        peak = eq.copy()
        mdd = np.zeros(n_paths)
        ruin = np.zeros(n_paths, dtype=bool)
        for _ in range(n_trades):
            R = _draw_R(rng, n_paths)
            eq *= (1.0 + f * R)
            peak = np.maximum(peak, eq)
            mdd = np.maximum(mdd, 1.0 - eq / peak)
            ruin |= eq <= ruin_level * principal
        out[float(f)] = {
            "p_ruin": float(ruin.mean()),
            "median_max_dd": float(np.median(mdd)),
            "median_terminal": float(np.median(eq)),
            "mean_terminal": float(eq.mean()),
        }
    return out


__all__ = [
    "position_size", "WithdrawalPolicy", "correlated_risk_cap", "f_sweep",
]
