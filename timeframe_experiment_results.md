# Timeframe Degradation Experiment (Cost-Adjusted)

Per your request, we adjusted the `CostModel` to:
1. **Commission = 0**
2. **Strict MT5 Spread** (Accepting `spread=0` from older data instead of using synthetic fallbacks).

*Note: Slippage is still active at 0.5 points to reflect order execution realities.*

## Results Summary (Zero Commission + Raw MT5 Spread)

| Timeframe | Net Trades | Net Return (%) | Ann. Sharpe | Max Drawdown | Verdict |
|-----------|-----------:|---------------:|------------:|-------------:|:--------|
| **H4 (Base)** | 729 | **+89.68%** *(was 72%)*| **0.58** | 21.91% | REJECTED (t-stat 1.77) |
| **H1** | 2,385 | +52.12% *(was 26%)* | 0.16 | 63.33% | REJECTED (t-stat 0.98) |
| **M15** | 8,958 | +47.21% *(was Ruin)*| 0.08 | 82.87% | REJECTED (t-stat 1.02) |
| **M5** | 25,864 | -98.10% *(Ruin)* | -0.00 | 99.87% | REJECTED (Ruin) |

## Key Findings & Insights

> [!WARNING]
> **The Illusion of M15 Profitability**
> By removing commission and allowing the older data (2018-2020) to have literally `0` spread, M15 was rescued from complete ruin (bouncing from -99% to +47%). However, look at the Sharpe ratio (0.08) and t-stat (1.02). Mathematically, this means the profit is entirely random noise. There is no statistical edge here, even in this highly forgiving cost environment.

> [!CAUTION]
> **M5 Remains a Death Trap**
> Even with 0 commission and 0 spread for half the dataset, M5 still resulted in account ruin (-98.10%). Why? Because of **Slippage** and **Market Noise**. Over 25,000 trades, even a tiny 0.5 point slippage penalty accumulates into a massive unrecoverable hole. Furthermore, the price action on M5 is simply too erratic to form sustainable macro trends.

## Conclusion
This test powerfully confirms that the degradation is not *just* about broker costs, but also about the physical properties of the market. High-frequency Time-Series Momentum on XAUUSD simply does not work. The signal-to-noise ratio is too low, and the friction of merely crossing the bid/ask spread (via slippage) destroys any hypothetical alpha. The H4 timeframe remains the sweet spot.
