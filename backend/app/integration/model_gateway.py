"""Compatibility import for the canonical V1.3 model control plane.

New code must import from :mod:`app.model_gateway`. This module intentionally
contains no provider HTTP logic.
"""

from app.model_gateway import (
    ModelBudgetExceeded,
    ModelGateway,
    ModelReply,
    ModelUnavailable,
    VisionModelUnavailable,
)

__all__ = [
    "ModelBudgetExceeded",
    "ModelGateway",
    "ModelReply",
    "ModelUnavailable",
    "VisionModelUnavailable",
]
