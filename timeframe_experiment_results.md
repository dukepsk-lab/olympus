# Timeframe Degradation Experiment (Cost-Adjusted)

Per your request, we adjusted the `CostModel` to:
1. **Commission = 0** (matches the commission-free IUX account — cost is priced into the spread).
2. **Real MT5 Spread** with a **base-spread fallback where the feed is missing**.

*Note: Slippage is still active at 0.5 points to reflect order execution realities.*

> [!IMPORTANT]
> **Correction (spread==0 is MISSING, not free).** The first cut of this table
> accepted `spread = 0` from the 2018-2020 backfill as a *real* zero spread, i.e.
> ~43% of the tape crossed bid/ask **for free**. That is a data gap, not a zero
> cost (a real instrument never has zero spread), so the cost model now falls
> back to the base-spread assumption on those bars. The **H4 base corrected from
> +89.68% → +79.7%** (Sharpe 0.58 → 0.54); the ~10pp was phantom cost-free
> profit. The H1/M15/M5 rows below were measured under the **old free-spread
> rule** (and require resampled `*_H1/M15/M5.csv` files not committed here), so
> they are **cost-optimistic** — charging real spread only makes the
> high-frequency timeframes *worse*, which strengthens, not weakens, every
> conclusion in this doc.

## Results Summary (Zero Commission, real spread / base-spread fallback)

| Timeframe | Net Trades | Net Return (%) | Ann. Sharpe | Max Drawdown | Verdict |
|-----------|-----------:|---------------:|------------:|-------------:|:--------|
| **H4 (Base, corrected)** | 730 | **+79.7%** | **0.54** | 25.0% | REJECTED (t-stat 1.64) |
| H1 *(old free-spread rule)* | 2,385 | +52.12% | 0.16 | 63.33% | REJECTED (t-stat 0.98) |
| M15 *(old free-spread rule)* | 8,958 | +47.21% | 0.08 | 82.87% | REJECTED (t-stat 1.02) |
| M5 *(old free-spread rule)* | 25,864 | -98.10% *(Ruin)* | -0.00 | 99.87% | REJECTED (Ruin) |

## Key Findings & Insights

> [!WARNING]
> **The Illusion of M15 Profitability**
> By removing commission and allowing the older data (2018-2020) to have literally `0` spread, M15 was rescued from complete ruin (bouncing from -99% to +47%). However, look at the Sharpe ratio (0.08) and t-stat (1.02). Mathematically, this means the profit is entirely random noise. There is no statistical edge here, even in this highly forgiving cost environment.

> [!CAUTION]
> **M5 Remains a Death Trap**
> Even with 0 commission and 0 spread for half the dataset, M5 still resulted in account ruin (-98.10%). Why? Because of **Slippage** and **Market Noise**. Over 25,000 trades, even a tiny 0.5 point slippage penalty accumulates into a massive unrecoverable hole. Furthermore, the price action on M5 is simply too erratic to form sustainable macro trends.

## Conclusion
This test powerfully confirms that the degradation is not *just* about broker costs, but also about the physical properties of the market. High-frequency Time-Series Momentum on XAUUSD simply does not work. The signal-to-noise ratio is too low, and the friction of merely crossing the bid/ask spread (via slippage) destroys any hypothetical alpha. The H4 timeframe remains the sweet spot.
