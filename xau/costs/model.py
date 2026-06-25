"""Cost model -- spread (bid/ask), commission, slippage, news & session widening.

The single most important invariant lives here and in :mod:`xau.backtest.fills`:
there is NO mid-price fill path. Spreads are modelled explicitly and widened
inside news windows and thin sessions. Every reported metric downstream is NET
of these costs (there is no gross mode).

Double-counting guard (read this before editing):
  * In the event-driven engine, spread + slippage are captured by FILLING at the
    correct side of the book (ask for longs, bid for shorts) plus per-side slip
    via :func:`xau.backtest.fills.fill_price`. Commission is then added once per
    side. The engine therefore does NOT call :meth:`CostModel.round_trip_cost`
    on top -- that would count the spread twice.
  * :meth:`round_trip_cost` exists as an *accounting* helper (full round-trip
    friction in $) used for reporting / sanity checks / fast vectorised paths
    where fills are not simulated bar-by-bar. It equals the same total the
    engine captures via (fills + commission).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import Config, SymbolSpec
from ..data.sessions import session_of_hour


@dataclass
class CostModel:
    """Per-symbol spread/commission/slippage with news & session widening."""

    symbols: dict[str, SymbolSpec]
    news_spread_multiplier: float = 3.0
    session_spread_multiplier: dict[str, float] = field(
        default_factory=lambda: {"asian": 1.5, "london": 1.0, "overlap": 1.0, "ny": 1.2}
    )

    @classmethod
    def from_config(cls, config: Config) -> "CostModel":
        return cls(
            symbols=dict(config.symbols),
            news_spread_multiplier=config.costs.news_spread_multiplier,
            session_spread_multiplier=dict(config.costs.session_spread_multiplier),
        )

    def _spec(self, symbol: str) -> SymbolSpec:
        try:
            return self.symbols[symbol]
        except KeyError as exc:  # pragma: no cover
            raise KeyError(f"CostModel: unknown symbol '{symbol}'") from exc

    def effective_spread(self, symbol: str, ts: pd.Timestamp,
                         is_news_window: bool) -> float:
        """Spread in POINTS for ``symbol`` at ``ts``, widened by session & news."""
        spec = self._spec(symbol)
        spread = spec.base_spread_points
        hour = ts.hour if ts.tzinfo else ts.hour
        sess = session_of_hour(hour, _DummyCfg(self.session_spread_multiplier))
        spread *= self.session_spread_multiplier.get(sess, 1.0)
        if is_news_window:
            spread *= self.news_spread_multiplier
        return float(spread)

    def spread_in_price(self, symbol: str, ts: pd.Timestamp,
                        is_news_window: bool) -> float:
        """Spread expressed in PRICE units (= effective_spread_points * point)."""
        spec = self._spec(symbol)
        return self.effective_spread(symbol, ts, is_news_window) * spec.point

    def bid_ask(self, mid: float, symbol: str, ts: pd.Timestamp,
                is_news_window: bool) -> tuple[float, float]:
        """Split a mid price into (bid, ask) using the effective half-spread.

        bid < mid < ask always, with bid != ask whenever spread > 0 (the only
        way they coincide is a zero spread, which no real symbol has).
        """
        spec = self._spec(symbol)
        half = self.effective_spread(symbol, ts, is_news_window) * spec.point / 2.0
        return mid - half, mid + half

    def commission_dollars(self, symbol: str, lots: float, sides: int = 1) -> float:
        spec = self._spec(symbol)
        return sides * spec.commission_per_lot * lots

    def round_trip_cost(self, symbol: str, ts: pd.Timestamp, lots: float,
                        is_news_window: bool) -> float:
        """Full round-trip friction in $ = spread + commission(2) + slippage(2).

        Accounting helper; NOT applied again inside the engine (see module
        docstring). Spread paid once per round trip (half on entry, half on
        exit), slippage once per side, commission once per side.
        """
        spec = self._spec(symbol)
        spread_pts = self.effective_spread(symbol, ts, is_news_window)
        spread_cost = spread_pts * spec.point_value * lots       # $, once
        slip_cost = 2.0 * spec.slippage_points * spec.point_value * lots  # $, two sides
        comm = 2.0 * spec.commission_per_lot * lots              # $, two sides
        return float(spread_cost + slip_cost + comm)


@dataclass
class _DummyCfg:
    """Lightweight stand-in so :func:`session_of_hour` can run without a full
    Config (keeps :class:`CostModel` decoupled from the yaml)."""
    sessions: dict[str, tuple[int, int]]

    def __init__(self, mults: dict[str, float]):
        # reconstruct canonical hour ranges from the multiplier keys present
        canonical = {"asian": (0, 7), "london": (7, 12), "overlap": (12, 16), "ny": (16, 21)}
        self.sessions = {k: canonical.get(k, (0, 24)) for k in mults}
        for k, v in canonical.items():
            self.sessions.setdefault(k, v)


__all__ = ["CostModel"]
