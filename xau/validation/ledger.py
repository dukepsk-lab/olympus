"""TrialLedger -- persistent record of EVERY configuration evaluated.

The Deflated Sharpe Ratio's ``n_trials`` MUST come from this ledger, never a
guess. Under-counting trials is the classic way a DSR is faked into passing, so
the ledger is append-only and counts every (params x symbol x timeframe x filter
combo) attempted, promoted or rejected.

Storage: newline-delimited JSON (JSONL), append-only, human-greppable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def config_signature(params: dict[str, Any], symbol: str, timeframe: str,
                     filters: dict[str, Any]) -> str:
    """Stable hash of a trial identity (params x symbol x TF x filters)."""
    payload = json.dumps(
        {"params": params, "symbol": symbol, "timeframe": timeframe,
         "filters": filters},
        sort_keys=True, default=str,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class TrialRecord:
    timestamp: str
    signature: str
    params: dict[str, Any]
    symbol: str
    timeframe: str
    filters: dict[str, Any]
    metrics: dict[str, Any] = field(default_factory=dict)
    gate_passed: bool = False
    failed_checks: list[str] = field(default_factory=list)
    notes: str = ""


class TrialLedger:
    def __init__(self, path: str | Path = "trial_ledger.jsonl"):
        self.path = Path(path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def record(self, params: dict[str, Any], symbol: str, timeframe: str,
               filters: dict[str, Any], metrics: dict[str, Any] | None = None,
               gate_passed: bool = False, failed_checks: list[str] | None = None,
               notes: str = "") -> TrialRecord:
        sig = config_signature(params, symbol, timeframe, filters)
        rec = TrialRecord(
            timestamp=self._now(),
            signature=sig,
            params=dict(params),
            symbol=symbol,
            timeframe=timeframe,
            filters=dict(filters),
            metrics=dict(metrics or {}),
            gate_passed=bool(gate_passed),
            failed_checks=list(failed_checks or []),
            notes=notes,
        )
        self._append(rec)
        return rec

    def _append(self, rec: TrialRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec), default=str) + "\n")

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    @property
    def n_trials(self) -> int:
        """Total number of trials recorded (used as DSR n_trials)."""
        return len(self.load())

    def n_unique_signatures(self) -> int:
        return len({r["signature"] for r in self.load()})

    def deflation_n_trials(self) -> int:
        """Trial count fed to DSR. Defaults to total trials; expose so callers
        can substitute an effective count only if explicitly justified."""
        return max(self.n_trials, 1)

    def trial_sharpes(self) -> list[float]:
        """Sharpe of every recorded trial -- the selection-bias distribution the
        DSR deflates against (variance across trials)."""
        out = []
        for r in self.load():
            try:
                out.append(float(r.get("metrics", {}).get("sharpe", 0.0)))
            except (TypeError, ValueError):
                continue
        return out

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


__all__ = ["TrialLedger", "TrialRecord", "config_signature"]
