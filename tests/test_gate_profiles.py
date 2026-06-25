"""Gate profiles must be principled, not tuned-to-pass:

  * `strict` is the identity (default unchanged),
  * `single_hypothesis` relaxes ONLY the t-stat bar (3.0 -> 2.0) and NOTHING else,
  * the shared `failed_checks_from_evidence` agrees with the live gate, and a
    config that fails on regime/DSR/PBO still fails under the looser profile
    (loosening t-stat cannot manufacture a pass).
"""
from __future__ import annotations

import dataclasses

import pytest

from xau.config import load_config
from xau.gate import (
    GATE_PROFILES,
    failed_checks_from_evidence,
    gate_config_for_profile,
)


def _gate():
    return load_config("config/default.yaml").gate


def test_strict_is_identity():
    g = _gate()
    assert gate_config_for_profile(g, "strict") is g


def test_single_hypothesis_changes_only_tstat():
    g = _gate()
    sh = gate_config_for_profile(g, "single_hypothesis")
    assert sh.tstat_min == 2.0
    # every OTHER field is identical
    for f in dataclasses.fields(g):
        if f.name == "tstat_min":
            continue
        assert getattr(sh, f.name) == getattr(g, f.name), f.name


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        gate_config_for_profile(_gate(), "loosey_goosey")
    assert set(GATE_PROFILES) == {"strict", "single_hypothesis"}


def test_loosening_tstat_does_not_rescue_a_multi_fail_config():
    # evidence that fails on regime breadth, DSR, PBO, CPCV AND t-stat
    ev = {
        "dsr": 0.92, "pbo": 0.26, "cpcv_positive_frac": 0.62, "t_stat": 1.43,
        "n_trades": 319, "median_calmar_paths": 0.30,
        "regime_profitable_count": 2, "regime_exposure_count": 3,
        "n_regime_buckets": 4,
    }
    g = _gate()
    strict_fail = failed_checks_from_evidence(ev, gate_config_for_profile(g, "strict"))
    sh_fail = failed_checks_from_evidence(ev, gate_config_for_profile(g, "single_hypothesis"))
    assert strict_fail, "strict should reject this evidence"
    assert sh_fail, "single_hypothesis must STILL reject (independent checks fail)"
    # t-stat 1.43 fails even the relaxed 2.0 bar, and regime/DSR/PBO/CPCV remain
    assert any("regime" in f for f in sh_fail)
    assert any("DSR" in f for f in sh_fail)


def test_t_stat_between_2_and_3_flips_only_that_check():
    # a config strong everywhere EXCEPT t-stat in (2.0, 3.0) passes single_hyp
    ev = {
        "dsr": 0.97, "pbo": 0.10, "cpcv_positive_frac": 0.80, "t_stat": 2.5,
        "n_trades": 400, "median_calmar_paths": 0.50,
        "regime_profitable_count": 4, "regime_exposure_count": 4,
        "n_regime_buckets": 4,
    }
    g = _gate()
    assert failed_checks_from_evidence(ev, gate_config_for_profile(g, "strict")) == [
        "t-stat 2.50 < 3.0"]
    assert failed_checks_from_evidence(ev, gate_config_for_profile(g, "single_hypothesis")) == []
