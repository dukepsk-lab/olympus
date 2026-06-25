"""TrialLedger deduplication: the DSR deflation count must reflect the number of
DISTINCT configs searched, not the raw append count. Re-running an identical
config must NOT inflate ``deflation_n_trials`` / ``trial_sharpes`` -- otherwise
the DSR drifts every run and reproducibility (and the selection-bias hurdle) is
silently broken.
"""
from __future__ import annotations

from xau.validation.ledger import TrialLedger


def _record(ledger, sig_params, sharpe, notes):
    ledger.record(
        params=sig_params, symbol="XAUUSD", timeframe="H4", filters={},
        metrics={"sharpe": sharpe, "n_trades": 100, "net_return": 0.1},
        gate_passed=False, failed_checks=[], notes=notes,
    )


def test_rerunning_same_config_does_not_inflate_deflation_count(tmp_path):
    led = TrialLedger(tmp_path / "ledger.jsonl")
    # Same config (identical params/symbol/tf/filters) evaluated three times.
    _record(led, {"lookbacks": [20, 60]}, 0.01, "trend")
    _record(led, {"lookbacks": [20, 60]}, 0.01, "trend")
    _record(led, {"lookbacks": [20, 60]}, 0.01, "trend")

    assert led.n_trials == 3                 # raw audit count keeps every row
    assert led.n_unique_signatures() == 1    # but only one distinct trial
    assert led.deflation_n_trials() == 1     # ...which is what DSR must use
    assert led.trial_sharpes() == [0.01]     # one sharpe, not three


def test_distinct_configs_still_accumulate(tmp_path):
    led = TrialLedger(tmp_path / "ledger.jsonl")
    _record(led, {"lookbacks": [20, 60]}, 0.01, "trend")
    _record(led, {"zscore_entry": 2.0}, -0.05, "reversion")
    _record(led, {"range_session": "asian"}, -0.13, "breakout")

    assert led.deflation_n_trials() == 3
    assert sorted(led.trial_sharpes()) == [-0.13, -0.05, 0.01]


def test_latest_write_wins_for_a_signature(tmp_path):
    led = TrialLedger(tmp_path / "ledger.jsonl")
    _record(led, {"lookbacks": [20, 60]}, 0.01, "trend")
    _record(led, {"lookbacks": [20, 60]}, 0.42, "trend")  # re-measured, newer

    assert led.deflation_n_trials() == 1
    assert led.trial_sharpes() == [0.42]


def test_deflation_count_is_at_least_one_when_empty(tmp_path):
    led = TrialLedger(tmp_path / "ledger.jsonl")
    assert led.deflation_n_trials() == 1
    assert led.trial_sharpes() == []
