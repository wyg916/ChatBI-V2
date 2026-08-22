from __future__ import annotations

from decimal import Decimal

from .contracts import (
    DatabaseEvidence,
    ImageDatabaseComparison,
    VisualEvidence,
)


def compare_image_with_database(
    evidence: VisualEvidence,
    database: DatabaseEvidence,
    *,
    screenshot_value: Decimal,
    metric: str,
) -> ImageDatabaseComparison:
    if database.oracle_status != "PASSED":
        raise ValueError("DATABASE_EVIDENCE_NOT_ORACLE_VERIFIED")
    if metric != database.metric:
        raise ValueError("IMAGE_DATABASE_METRIC_MISMATCH")
    difference = screenshot_value - database.value
    difference_rate = difference / database.value if database.value else None
    return ImageDatabaseComparison(
        metric=metric,
        screenshot_value=screenshot_value,
        database_value=database.value,
        difference=difference,
        difference_rate=difference_rate,
        time_range=database.time_range,
        dimension=database.dimension,
        business_definition=database.business_definition,
        oracle_status=database.oracle_status,
        visual_evidence_signature=evidence.signature(),
        database_result_signature=database.result_signature,
    )
