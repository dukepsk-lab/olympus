"""Typed configuration loader.

Reads a YAML file into nested dataclasses so the rest of the system gets
static, autocompletable, validated config rather than untyped dicts.

Design decisions:
  * Dataclasses (not pydantic) to avoid an extra dependency; we validate by hand
    at load time and raise ``ConfigError`` on anything missing/invalid.
  * ``SymbolSpec.point_value`` is DERIVED (point * contract_size) so the $ value
    of a one-point move for one lot is never typed by hand in two places.
  * Regime buckets are an ordered list of ``(name, start, end)``; the bucket
    named ``"range"`` is special-cased nowhere -- all buckets are treated
    uniformly and the report just lists whichever the trades fell into.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when the config file is structurally invalid."""


# ----------------------------------------------------------------------------
#  Sub-configs
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class DataConfig:
    source: str = "synthetic"
    timeframe: str = "H4"
    d1_overlay: bool = True
    csv_dir: str = "data/ohlc"
    start: str | None = None
    end: str | None = None
    bars: int = 6000


@dataclass(frozen=True)
class SymbolSpec:
    name: str
    digits: int
    point: float
    contract_size: float
    base_spread_points: float
    commission_per_lot: float
    slippage_points: float

    @property
    def point_value(self) -> float:
        """$ value of a 1-point price move, for 1 lot.

        = point * contract_size. e.g. XAUUSD: 0.01 * 100 = 1.0 $/point/lot.
        """
        return self.point * self.contract_size


@dataclass(frozen=True)
class CostsConfig:
    news_spread_multiplier: float = 3.0
    session_spread_multiplier: dict[str, float] = field(
        default_factory=lambda: {"asian": 1.5, "london": 1.0, "overlap": 1.0, "ny": 1.2}
    )
    news_window_minutes: int = 30


@dataclass(frozen=True)
class TrendConfig:
    lookbacks: tuple[int, ...] = (20, 60, 120)
    d1_lookbacks: tuple[int, ...] = (20, 50)
    vol_target_annual: float = 0.15
    vol_halflife: int = 20


@dataclass(frozen=True)
class BreakoutConfig:
    opening_range_bars: int = 3
    min_range_atr_multiple: float = 0.5
    expansion_atr_multiple: float = 1.0
    news_no_trade_minutes: int = 30
    range_session: str = "asian"                # session that DEFINES the range
    breakout_sessions: tuple[str, ...] = ("london", "ny", "overlap")


@dataclass(frozen=True)
class ReversionConfig:
    enabled: bool = False
    zscore_window: int = 50
    zscore_entry: float = 2.0
    rsi_window: int = 14


@dataclass(frozen=True)
class RegimeConfig:
    hurst_window: int = 200
    hurst_max_lag: int = 20
    adx_period: int = 14
    vol_halflife: int = 50
    hurst_trend: float = 0.55
    hurst_range: float = 0.45
    adx_trend: float = 25.0
    adx_range: float = 20.0


@dataclass(frozen=True)
class FeatureConfig:
    trend: TrendConfig = field(default_factory=TrendConfig)
    breakout: BreakoutConfig = field(default_factory=BreakoutConfig)
    reversion: ReversionConfig = field(default_factory=ReversionConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)


@dataclass(frozen=True)
class LabelingConfig:
    pt_sl: tuple[float, float] = (2.0, 2.0)
    vol_halflife: int = 20
    max_holding_bars: int = 60


@dataclass(frozen=True)
class WithdrawalConfig:
    wd_share: float = 0.40
    cadence_trades: int = 17
    house_money_multiple: float = 2.0


@dataclass(frozen=True)
class MoneyConfig:
    risk_fraction: float = 0.01
    risk_fraction_band: tuple[float, float] = (0.0075, 0.015)
    ruin_level: float = 0.5
    withdrawal: WithdrawalConfig = field(default_factory=WithdrawalConfig)
    correlated_risk_cap_multiple: float = 3.0
    correlated_groups: tuple[tuple[str, ...], ...] = (("XAUUSD", "US30", "BTCUSD"),)
    f_sweep_values: tuple[float, ...] = (0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.04)


@dataclass(frozen=True)
class CPCVConfig:
    n_splits: int = 10
    n_test_groups: int = 2
    embargo_pct: float = 0.01


@dataclass(frozen=True)
class PBOConfig:
    n_partitions: int = 16


@dataclass(frozen=True)
class WalkforwardConfig:
    train_bars: int = 1500
    step_bars: int = 500


@dataclass(frozen=True)
class RegimeBucket:
    name: str
    start: str
    end: str


@dataclass(frozen=True)
class ValidationConfig:
    cpcv: CPCVConfig = field(default_factory=CPCVConfig)
    pbo: PBOConfig = field(default_factory=PBOConfig)
    walkforward: WalkforwardConfig = field(default_factory=WalkforwardConfig)
    regime_buckets: tuple[RegimeBucket, ...] = ()


@dataclass(frozen=True)
class GateConfig:
    dsr_min: float = 0.95
    pbo_max: float = 0.20
    pbo_hard_reject: float = 0.50
    cpcv_positive_frac_min: float = 0.70
    tstat_min: float = 3.0
    regime_profitable_min: int = 3
    min_net_trades: int = 300
    regime_exposure_min: int = 3
    median_calmar_min: float = 0.30


@dataclass(frozen=True)
class BacktestConfig:
    starting_equity: float = 10000.0
    annual_bars: int = 1460


@dataclass(frozen=True)
class Config:
    seed: int = 7
    data: DataConfig = field(default_factory=DataConfig)
    universe: tuple[str, ...] = ()
    symbols: dict[str, SymbolSpec] = field(default_factory=dict)
    sessions: dict[str, tuple[int, int]] = field(default_factory=dict)
    costs: CostsConfig = field(default_factory=CostsConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    labeling: LabelingConfig = field(default_factory=LabelingConfig)
    money: MoneyConfig = field(default_factory=MoneyConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    gate: GateConfig = field(default_factory=GateConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)


# ----------------------------------------------------------------------------
#  Loader
# ----------------------------------------------------------------------------
def _require(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise ConfigError(f"missing required key '{key}' in {ctx}")
    return d[key]


def _as_tuple(v: Any) -> tuple:
    return tuple(v)


def load_config(path: str | Path) -> Config:
    """Load and validate a YAML config into a :class:`Config`."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a mapping")

    seed = int(raw.get("seed", 7))

    d = raw.get("data", {})
    data_cfg = DataConfig(
        source=str(d.get("source", "synthetic")),
        timeframe=str(d.get("timeframe", "H4")),
        d1_overlay=bool(d.get("d1_overlay", True)),
        csv_dir=str(d.get("csv_dir", "data/ohlc")),
        start=d.get("start"),
        end=d.get("end"),
        bars=int(d.get("bars", 6000)),
    )

    universe = tuple(_require(raw, "universe", "root"))

    sym_raw = _require(raw, "symbols", "root")
    symbols: dict[str, SymbolSpec] = {}
    for name, s in sym_raw.items():
        symbols[str(name)] = SymbolSpec(
            name=str(name),
            digits=int(s["digits"]),
            point=float(s["point"]),
            contract_size=float(s["contract_size"]),
            base_spread_points=float(s["base_spread_points"]),
            commission_per_lot=float(s["commission_per_lot"]),
            slippage_points=float(s["slippage_points"]),
        )
    for u in universe:
        if u not in symbols:
            raise ConfigError(f"universe symbol '{u}' has no symbol spec")

    sess_raw = raw.get("sessions", {})
    sessions = {str(k): (int(v[0]), int(v[1])) for k, v in sess_raw.items()}

    c = raw.get("costs", {})
    costs = CostsConfig(
        news_spread_multiplier=float(c.get("news_spread_multiplier", 3.0)),
        session_spread_multiplier={
            str(k): float(v) for k, v in c.get("session_spread_multiplier", {}).items()
        },
        news_window_minutes=int(c.get("news_window_minutes", 30)),
    )

    f_raw = raw.get("features", {})
    ft = f_raw.get("trend", {})
    fb = f_raw.get("breakout", {})
    fr = f_raw.get("reversion", {})
    fg = f_raw.get("regime", {})
    features = FeatureConfig(
        trend=TrendConfig(
            lookbacks=_as_tuple(ft.get("lookbacks", (20, 60, 120))),
            d1_lookbacks=_as_tuple(ft.get("d1_lookbacks", (20, 50))),
            vol_target_annual=float(ft.get("vol_target_annual", 0.15)),
            vol_halflife=int(ft.get("vol_halflife", 20)),
        ),
        breakout=BreakoutConfig(
            opening_range_bars=int(fb.get("opening_range_bars", 3)),
            min_range_atr_multiple=float(fb.get("min_range_atr_multiple", 0.5)),
            expansion_atr_multiple=float(fb.get("expansion_atr_multiple", 1.0)),
            news_no_trade_minutes=int(fb.get("news_no_trade_minutes", 30)),
            range_session=str(fb.get("range_session", "asian")),
            breakout_sessions=_as_tuple(fb.get("breakout_sessions",
                                               ("london", "ny", "overlap"))),
        ),
        reversion=ReversionConfig(
            enabled=bool(fr.get("enabled", False)),
            zscore_window=int(fr.get("zscore_window", 50)),
            zscore_entry=float(fr.get("zscore_entry", 2.0)),
            rsi_window=int(fr.get("rsi_window", 14)),
        ),
        regime=RegimeConfig(
            hurst_window=int(fg.get("hurst_window", 200)),
            hurst_max_lag=int(fg.get("hurst_max_lag", 20)),
            adx_period=int(fg.get("adx_period", 14)),
            vol_halflife=int(fg.get("vol_halflife", 50)),
            hurst_trend=float(fg.get("hurst_trend", 0.55)),
            hurst_range=float(fg.get("hurst_range", 0.45)),
            adx_trend=float(fg.get("adx_trend", 25.0)),
            adx_range=float(fg.get("adx_range", 20.0)),
        ),
    )

    lab = raw.get("labeling", {})
    labeling = LabelingConfig(
        pt_sl=_as_tuple(lab.get("pt_sl", (2.0, 2.0))),
        vol_halflife=int(lab.get("vol_halflife", 20)),
        max_holding_bars=int(lab.get("max_holding_bars", 60)),
    )

    m = raw.get("money", {})
    w = m.get("withdrawal", {})
    money = MoneyConfig(
        risk_fraction=float(m.get("risk_fraction", 0.01)),
        risk_fraction_band=_as_tuple(m.get("risk_fraction_band", (0.0075, 0.015))),
        ruin_level=float(m.get("ruin_level", 0.5)),
        withdrawal=WithdrawalConfig(
            wd_share=float(w.get("wd_share", 0.40)),
            cadence_trades=int(w.get("cadence_trades", 17)),
            house_money_multiple=float(w.get("house_money_multiple", 2.0)),
        ),
        correlated_risk_cap_multiple=float(m.get("correlated_risk_cap_multiple", 3.0)),
        correlated_groups=tuple(tuple(g) for g in m.get("correlated_groups", [])),
        f_sweep_values=_as_tuple(m.get("f_sweep_values", ())),
    )

    v = raw.get("validation", {})
    vc = v.get("cpcv", {})
    vp = v.get("pbo", {})
    vw = v.get("walkforward", {})
    buckets = tuple(
        RegimeBucket(name=str(k), start=str(val[0]), end=str(val[1]))
        for k, val in v.get("regime_buckets", {}).items()
    )
    validation = ValidationConfig(
        cpcv=CPCVConfig(
            n_splits=int(vc.get("n_splits", 10)),
            n_test_groups=int(vc.get("n_test_groups", 2)),
            embargo_pct=float(vc.get("embargo_pct", 0.01)),
        ),
        pbo=PBOConfig(n_partitions=int(vp.get("n_partitions", 16))),
        walkforward=WalkforwardConfig(
            train_bars=int(vw.get("train_bars", 1500)),
            step_bars=int(vw.get("step_bars", 500)),
        ),
        regime_buckets=buckets,
    )

    g = raw.get("gate", {})
    gate = GateConfig(
        dsr_min=float(g.get("dsr_min", 0.95)),
        pbo_max=float(g.get("pbo_max", 0.20)),
        pbo_hard_reject=float(g.get("pbo_hard_reject", 0.50)),
        cpcv_positive_frac_min=float(g.get("cpcv_positive_frac_min", 0.70)),
        tstat_min=float(g.get("tstat_min", 3.0)),
        regime_profitable_min=int(g.get("regime_profitable_min", 3)),
        min_net_trades=int(g.get("min_net_trades", 300)),
        regime_exposure_min=int(g.get("regime_exposure_min", 3)),
        median_calmar_min=float(g.get("median_calmar_min", 0.30)),
    )

    b = raw.get("backtest", {})
    backtest = BacktestConfig(
        starting_equity=float(b.get("starting_equity", 10000.0)),
        annual_bars=int(b.get("annual_bars", 1460)),
    )

    return Config(
        seed=seed,
        data=data_cfg,
        universe=universe,
        symbols=symbols,
        sessions=sessions,
        costs=costs,
        features=features,
        labeling=labeling,
        money=money,
        validation=validation,
        gate=gate,
        backtest=backtest,
    )


__all__ = [
    "Config",
    "ConfigError",
    "DataConfig",
    "SymbolSpec",
    "CostsConfig",
    "TrendConfig",
    "BreakoutConfig",
    "ReversionConfig",
    "RegimeConfig",
    "FeatureConfig",
    "LabelingConfig",
    "WithdrawalConfig",
    "MoneyConfig",
    "CPCVConfig",
    "PBOConfig",
    "WalkforwardConfig",
    "RegimeBucket",
    "ValidationConfig",
    "GateConfig",
    "BacktestConfig",
    "load_config",
]
