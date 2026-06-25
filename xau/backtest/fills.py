"""Fill execution -- the NO-MID contract.

Every fill lands on the CORRECT side of the book: a buy pays the ASK (+slippage),
a sell receives the BID (-slippage). The mid price is never a legal fill. This
file is the ONLY place fills are computed, and :mod:`xau.backtest.engine` is the
ONLY caller -- so a grep for the mid formula turns up nothing in any fill path.
"""
from __future__ import annotations


def fill_price(side: int,
               next_bar_open_bid: float,
               next_bar_open_ask: float,
               slippage_points: float,
               point: float) -> float:
    """Return the execution price for a market order at the next bar's open.

    Parameters
    ----------
    side : int
        +1 to BUY (go/extend long, or cover a short); -1 to SELL (go/extend
        short, or close a long). Zero is treated as no-trade and raises.
    next_bar_open_bid, next_bar_open_ask : float
        The bid/ask at the open of the bar on which the signal acts. The signal
        is decided at bar *t* close and acts at bar *t+1* open -- no look-ahead.
    slippage_points : float
        Adverse slippage in POINTS, applied to worsen the fill (added to ask for
        buys, subtracted from bid for sells).
    point : float
        Point size for the symbol (converts points -> price).

    Returns
    -------
    float
        The fill price. For a BUY this is ``ask + slippage``; for a SELL this is
        ``bid - slippage``. It can NEVER equal the mid ``0.5*(bid+ask)`` so long
        as ``ask > bid`` (guaranteed by a positive spread) -- see
        ``tests/test_costs_no_mid.py``.
    """
    if side == 0:
        raise ValueError("side must be +1 (buy) or -1 (sell), not 0")
    slip = slippage_points * point
    if side > 0:  # BUY -> pay the ask, slip further UP
        return next_bar_open_ask + slip
    # SELL -> receive the bid, slip further DOWN
    return next_bar_open_bid - slip


__all__ = ["fill_price"]
