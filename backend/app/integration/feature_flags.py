from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureDecision:
    execute: bool
    publish: bool
    shadow: bool


def decide(mode: str, trace_id: str, *, canary_percent: int = 10) -> FeatureDecision:
    if mode == "off":
        return FeatureDecision(False, False, False)
    if mode == "shadow":
        return FeatureDecision(True, False, True)
    if mode == "on":
        return FeatureDecision(True, True, False)
    if mode == "canary":
        bucket = int(hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:8], 16) % 100
        selected = bucket < canary_percent
        return FeatureDecision(selected, selected, False)
    raise ValueError(f"unsupported feature mode: {mode}")
