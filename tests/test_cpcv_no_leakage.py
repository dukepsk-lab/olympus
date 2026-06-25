"""CRITICAL: CPCV purge + embargo leakage test.

An off-by-one here silently reintroduces look-ahead into training. We construct
labels with KNOWN forward spans and assert:
  1. No training observation has a label span [t0, t1] overlapping any test block.
  2. The embargo band immediately after each test block is excluded from train.
  3. The exact-boundary case (t1 lands on the FIRST test bar) IS purged.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from xau.validation.cpcv import CombinatorialPurgedKFold


def _make_data(n: int = 100, span: int = 3, freq: str = "4h"):
    idx = pd.date_range("2023-01-01", periods=n, freq=freq, tz="UTC")
    X = pd.DataFrame(np.arange(n), index=idx, columns=["x"])
    t1 = pd.Series(
        [idx[min(i + span, n - 1)] for i in range(n)], index=idx, name="t1"
    )
    # positions of each label endpoint
    end_pos = np.minimum(np.arange(n) + span, n - 1)
    return X, t1, end_pos


@pytest.mark.parametrize("n_splits,n_test", [(10, 2), (6, 2), (8, 3)])
def test_no_train_span_overlaps_test_block(n_splits, n_test):
    X, t1, end_pos = _make_data(n=120, span=4)
    cpcv = CombinatorialPurgedKFold(n_splits=n_splits, n_test_groups=n_test,
                                    embargo_pct=0.05)
    n = len(X)
    for train_pos, test_pos in cpcv.split(X, t1):
        test_set = set(int(p) for p in test_pos)
        train_set = set(int(p) for p in train_pos)
        # basic disjointness
        assert not (train_set & test_set)
        # contiguity of test positions into blocks
        tp = sorted(test_set)
        blocks = []
        s = prev = tp[0]
        for p in tp[1:]:
            if p == prev + 1:
                prev = p
            else:
                blocks.append((s, prev)); s = prev = p
        blocks.append((s, prev))

        for i in train_set:
            lo, hi = i, int(end_pos[i])
            # train label span [i, hi] must contain NO test position
            for (a, b) in blocks:
                # overlap iff i <= b and hi >= a
                leak = (i <= b) and (hi >= a)
                assert not leak, (
                    f"LEAK: train obs {i} span [{lo},{hi}] overlaps test "
                    f"block [{a},{b}]"
                )


@pytest.mark.parametrize("embargo_pct", [0.01, 0.05, 0.10])
def test_embargo_excludes_post_block_band(embargo_pct):
    n = 200
    X, t1, _ = _make_data(n=n, span=1)  # short span so purge is minimal
    cpcv = CombinatorialPurgedKFold(n_splits=10, n_test_groups=2,
                                    embargo_pct=embargo_pct)
    embargo_n = int(np.ceil(embargo_pct * n))
    for train_pos, test_pos in cpcv.split(X, t1):
        tp = sorted(int(p) for p in test_pos)
        blocks = []
        s = prev = tp[0]
        for p in tp[1:]:
            if p == prev + 1:
                prev = p
            else:
                blocks.append((s, prev)); s = prev = p
        blocks.append((s, prev))
        train_set = set(int(p) for p in train_pos)
        for (a, b) in blocks:
            for e in range(b + 1, min(b + embargo_n, n - 1) + 1):
                assert e not in train_set, (
                    f"EMBARGO BREACH: position {e} in embargo band after "
                    f"test block [{a},{b}] is still in train"
                )


def test_exact_boundary_t1_on_first_test_bar_is_purged():
    # Construct a case where a train label's t1 lands EXACTLY on the first bar
    # of a test block. It MUST be purged (this is the classic off-by-one leak).
    n = 60
    idx = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
    X = pd.DataFrame(np.arange(n), index=idx, columns=["x"])
    # span = 1 bar for all; n_splits=6 -> 10 bars/group
    t1 = pd.Series([idx[min(i + 1, n - 1)] for i in range(n)], index=idx)
    cpcv = CombinatorialPurgedKFold(n_splits=6, n_test_groups=1, embargo_pct=0.0)
    for train_pos, test_pos in cpcv.split(X, t1):
        test_min = int(min(test_pos))
        test_set = set(int(p) for p in test_pos)
        # the bar immediately before the test block has t1 == first test bar
        i_before = test_min - 1
        if i_before >= 0:
            assert i_before not in set(int(p) for p in train_pos), (
                f"off-by-one leak: obs {i_before} (t1 on first test bar "
                f"{test_min}) was not purged from train"
            )


def test_combination_and_path_counts():
    cpcv = CombinatorialPurgedKFold(n_splits=10, n_test_groups=2)
    assert cpcv.n_combinations == 45
    assert cpcv.n_backtest_paths == 45
    X, t1, _ = _make_data(n=100, span=2)
    splits = list(cpcv.split(X, t1))
    assert len(splits) == 45
    # every observation must appear in at least one test fold (full coverage)
    all_test = set()
    for _, test in splits:
        all_test.update(int(p) for p in test)
    assert all_test == set(range(100))


def test_embargo_monotonic_with_pct():
    # larger embargo_pct => fewer (or equal) training observations on average
    X, t1, _ = _make_data(n=200, span=1)
    sizes_small = [len(tr) for tr, _ in
                   CombinatorialPurgedKFold(10, 2, embargo_pct=0.01).split(X, t1)]
    sizes_large = [len(tr) for tr, _ in
                   CombinatorialPurgedKFold(10, 2, embargo_pct=0.20).split(X, t1)]
    assert np.mean(sizes_large) <= np.mean(sizes_small)
