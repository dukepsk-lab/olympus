"""High-impact news calendar -> news-window flags.

The contract: a news window is a +/- ``news_window_minutes`` band around a
high-impact event timestamp. Inside it the cost model WIDENS the spread and the
breakout signal enters a no-trade zone. News times are exogenous and known in
advance (scheduled releases), so using them is not look-ahead -- it is exactly
what a real execution layer does to avoid getting picked off.

No network access. A calendar is either supplied explicitly (your own economic
calendar) or synthesised deterministically from the common scheduled cadences
(NFP first Friday 12:30 GMT, FOMC ~8x/yr 18:00 GMT, CPI monthly 12:30 GMT).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class NewsCalendar:
    """Immutable set of event timestamps (tz-aware UTC)."""
    events: list[pd.Timestamp] = field(default_factory=list)
    window_minutes: int = 30

    def is_news_window(self, ts: pd.Timestamp) -> bool:
        if not self.events:
            return False
        ts = pd.Timestamp(ts)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        band = pd.Timedelta(minutes=self.window_minutes)
        return any((e - band) <= ts <= (e + band) for e in self.events)

    def news_mask(self, index: pd.DatetimeIndex) -> pd.Series:
        """Boolean series: True where the bar's OPEN timestamp lies in a news band.

        Vectorised over the sorted event array for speed.
        """
        if not self.events:
            return pd.Series(False, index=index, name="is_news")
        idx = index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        else:
            idx = idx.tz_convert("UTC")
        bar_ns = idx.asi8.astype(np.int64)              # int64 ns, ascending
        band = pd.Timedelta(minutes=self.window_minutes).value
        ev_ns = np.array([pd.Timestamp(e).value for e in self.events], dtype=np.int64)
        lo = ev_ns - band
        hi = ev_ns + band
        # for each bar, is it within [lo_j, hi_j] for any event j?
        # searchsorted boundaries -> count of bands covering the bar.
        left = np.searchsorted(hi, bar_ns, side="left")
        right = np.searchsorted(lo, bar_ns, side="right")
        covered = right > left  # at least one band covers this bar
        return pd.Series(covered, index=index, name="is_news")


def make_synthetic_calendar(start: str, end: str,
                            window_minutes: int = 30) -> NewsCalendar:
    """Deterministic scheduled-release calendar between start/end (UTC dates)."""
    s = pd.Timestamp(start, tz="UTC")
    e = pd.Timestamp(end, tz="UTC")
    events: list[pd.Timestamp] = []

    months = pd.date_range(s.normalize().replace(day=1), e, freq="MS")
    for m in months:
        first_day = m.normalize()
        first_fri = first_day + pd.Timedelta(days=((4 - first_day.weekday()) % 7))
        nfp = first_fri + pd.Timedelta(hours=12, minutes=30)
        if s <= nfp <= e:
            events.append(nfp)
        cpi = m + pd.Timedelta(days=13, hours=12, minutes=30)
        if s <= cpi <= e:
            events.append(cpi)
        if m.month in (1, 3, 5, 6, 7, 9, 11, 12):
            fomc = m + pd.Timedelta(days=20, hours=18)
            if s <= fomc <= e:
                events.append(fomc)

    events.sort()
    return NewsCalendar(events=events, window_minutes=window_minutes)


__all__ = ["NewsCalendar", "make_synthetic_calendar"]
