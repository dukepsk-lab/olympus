"""Session tagging (Asian / London / NY / overlap), GMT-aware.

The session of a bar is decided SOLELY from its UTC hour, so it is causal and
deterministic. Session identity drives the spread multiplier in the cost model
and the opening-range logic in the breakout signal.
"""
from __future__ import annotations

import pandas as pd

from ..config import Config

SESSION_ORDER = ("asian", "london", "overlap", "ny")


def _ranges(cfg: Config) -> list[tuple[str, int, int]]:
    out = []
    for name, (lo, hi) in cfg.sessions.items():
        out.append((name, int(lo), int(hi)))
    # ensure a deterministic default if config omits a session
    names = {n for n, _, _ in out}
    if "asian" not in names:
        out.append(("asian", 0, 7))
    if "london" not in names:
        out.append(("london", 7, 12))
    if "overlap" not in names:
        out.append(("overlap", 12, 16))
    if "ny" not in names:
        out.append(("ny", 16, 21))
    # sort by start hour for determinism
    return sorted(out, key=lambda r: r[1])


def session_of_hour(hour: int, cfg: Config) -> str:
    """Return the session name for a GMT hour (0-23).

    Hours not covered by any configured session fall to the nearest low-liquidity
    bucket ('asian' by convention) -- there is no 'off' session because the FX
    week is 24/5; we simply widen spread in the thin hours.
    """
    hour = int(hour) % 24
    for name, lo, hi in _ranges(cfg):
        if lo <= hour < hi:
            return name
    return "asian"


def tag_sessions(index: pd.DatetimeIndex, cfg: Config) -> pd.Series:
    """Return a string series of session labels aligned to ``index``."""
    hours = index.tz_convert("UTC").hour if index.tz is not None else index.hour
    ranges = _ranges(cfg)
    arr = ["asian"] * len(index)
    for i, h in enumerate(hours):
        for name, lo, hi in ranges:
            if lo <= h < hi:
                arr[i] = name
                break
    return pd.Series(arr, index=index, name="session")


__all__ = ["session_of_hour", "tag_sessions", "SESSION_ORDER"]
