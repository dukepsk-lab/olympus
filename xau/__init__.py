"""xau -- research & validation engine for the multi-symbol FX/metals/index/crypto system.

Skeptical by construction: the primary job is to REJECT overfit strategies.
All reported metrics are NET OF COST (spread + commission + slippage). There is
no gross mode, and there is no mid-price fill path anywhere in the codebase.
"""
from __future__ import annotations

import os
import random

import numpy as np

__version__ = "0.1.0"

_GLOBAL_SEED: int | None = None


def set_global_seed(seed: int) -> None:
    """Set the single global seed across python random, numpy.

    Call exactly once at the start of a run (config-driven). Every stochastic
    component must read the seed via :func:`get_global_seed` rather than
    hard-coding one, so runs are reproducible.
    """
    global _GLOBAL_SEED
    _GLOBAL_SEED = int(seed)
    os.environ["PYTHONHASHSEED"] = str(_GLOBAL_SEED)
    random.seed(_GLOBAL_SEED)
    np.random.seed(_GLOBAL_SEED)


def get_global_seed(default: int = 7) -> int:
    """Return the global seed if set, else ``default``."""
    return _GLOBAL_SEED if _GLOBAL_SEED is not None else int(default)


def make_rng(stream: int = 0) -> np.random.Generator:
    """Spawn a deterministic numpy Generator derived from the global seed.

    ``stream`` lets different sub-components draw independent (but reproducible)
    sequences without coupling to one another.
    """
    return np.random.default_rng(get_global_seed() + int(stream))


__all__ = ["set_global_seed", "get_global_seed", "make_rng", "__version__"]
