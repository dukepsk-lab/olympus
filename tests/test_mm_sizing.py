"""Money-management unit tests: anti-Martingale sizing, withdrawal bookkeeping,
correlated-risk cap, and the f-sweep qualitative shape.
"""
from __future__ import annotations

import numpy as np
import pytest

from xau.mm.money import (
    WithdrawalPolicy,
    correlated_risk_cap,
    f_sweep,
    position_size,
)


def test_position_size_matches_risk_equation():
    # risk_fraction*equity == stop_distance_price * lots * point_value
    equity, stop, pv, f = 10000.0, 5.0, 1.0, 0.01
    lots = position_size(equity, stop, pv, f)
    assert lots == pytest.approx(20.0)
    assert stop * lots * pv == pytest.approx(f * equity)


def test_position_size_anti_martingale_scales_with_equity():
    # after a 20% loss, size shrinks proportionally (never grows)
    lots_full = position_size(10000.0, 5.0, 1.0, 0.01)
    lots_after_loss = position_size(8000.0, 5.0, 1.0, 0.01)
    assert lots_after_loss < lots_full
    assert lots_after_loss == pytest.approx(lots_full * 0.8)


def test_position_size_zero_on_degenerate_inputs():
    assert position_size(0.0, 5.0, 1.0, 0.01) == 0.0
    assert position_size(10000.0, 0.0, 1.0, 0.01) == 0.0
    assert position_size(10000.0, 5.0, 0.0, 0.01) == 0.0
    assert position_size(10000.0, 5.0, 1.0, 0.0) == 0.0


def test_withdrawal_banks_cash_and_tracks_hwm():
    wp = WithdrawalPolicy(wd_share=0.4, cadence_trades=2, house_money_multiple=2.0)
    eq, hwm, wd = 10000.0, 10000.0, 0.0
    principal = 10000.0
    # trade 1: no cadence, no house money yet
    eq, hwm, wd = wp.step(eq, hwm, wd, principal, trade_count=1)
    # trade 2: cadence hit, equity above hwm -> withdraw 40% of gain
    eq2, hwm2, wd2 = wp.step(12000.0, 10000.0, 0.0, principal, trade_count=2)
    assert wd2 == pytest.approx(0.4 * 2000.0)
    assert eq2 == pytest.approx(12000.0 - wd2)
    assert hwm2 == pytest.approx(eq2)


def test_house_money_banks_principal_at_2x():
    wp = WithdrawalPolicy(wd_share=0.4, cadence_trades=999, house_money_multiple=2.0)
    principal = 10000.0
    # total wealth = 21000 >= 2x, withdrawn=0 -> bank the principal (10000)
    eq, hwm, wd = wp.step(21000.0, 10000.0, 0.0, principal, trade_count=1)
    assert wd == pytest.approx(10000.0)
    assert eq == pytest.approx(11000.0)


def test_withdrawal_never_exceeds_equity():
    wp = WithdrawalPolicy(wd_share=0.4, cadence_trades=1, house_money_multiple=2.0)
    eq, hwm, wd = wp.step(1000.0, 500.0, 0.0, 10000.0, trade_count=1)
    assert eq >= 0.0
    assert wd <= 1000.0


def test_correlated_risk_cap():
    # two correlated symbols each at 1 unit risk -> cap at 3x single
    single_risk = 0.01 * 10000.0  # 100
    cap_mult = 3.0
    open_risk = {"XAUUSD": 100.0, "US30": 100.0, "BTCUSD": 100.0, "EURUSD": 100.0}
    groups = [("XAUUSD", "US30", "BTCUSD")]
    factors = correlated_risk_cap(open_risk, 10000.0, 0.01, cap_mult, groups)
    # group total 300 == cap 300 -> no scaling
    assert factors["XAUUSD"] == pytest.approx(1.0)
    # add a 4th correlated -> total 400 > 300 -> scale to 0.75
    open_risk["BTCUSD"] = 200.0  # group total now 100+100+200=400
    factors = correlated_risk_cap(open_risk, 10000.0, 0.01, cap_mult, groups)
    assert factors["XAUUSD"] == pytest.approx(0.75)
    assert factors["EURUSD"] == pytest.approx(1.0)  # not in group


def test_f_sweep_qualitative_shape():
    sweep = f_sweep(principal=10000.0, years=2, trades_per_year=200,
                    f_values=(0.005, 0.01, 0.02, 0.04), n_paths=800, seed=7)
    fs = sorted(sweep.keys())
    ruins = [sweep[f]["p_ruin"] for f in fs]
    mdds = [sweep[f]["median_max_dd"] for f in fs]
    meds = [sweep[f]["median_terminal"] for f in fs]
    # ruin rises with f
    assert ruins[-1] > ruins[0]
    # median max DD rises with f
    assert mdds[-1] > mdds[0]
    # median terminal wealth rises sub-linearly (gain from doubling f shrinks)
    gains = [meds[i + 1] / meds[i] for i in range(len(meds) - 1)]
    assert gains[-1] <= gains[0] * 1.5  # later doubling yields smaller multiple
