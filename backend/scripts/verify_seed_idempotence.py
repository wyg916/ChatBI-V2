from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import SessionLocal
from app.models import (
    BusinessTerm, Dashboard, DataSource, Dimension, Metric, SemanticEntity,
    SemanticModel, SemanticRelation, VerifiedAnswer,
)
from app.services.seed import seed_demo_semantic_model


def counts(db) -> dict[str, int]:
    models = [
        DataSource, SemanticModel, SemanticEntity, Metric, Dimension,
        SemanticRelation, BusinessTerm, VerifiedAnswer, Dashboard,
    ]
    return {model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0 for model in models}


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=root / "docs" / "evidence" / "day2" / "seed-idempotence.json")
    args = parser.parse_args()
    with SessionLocal() as db:
        seed_demo_semantic_model(db)
        first = counts(db)
        seed_demo_semantic_model(db)
        second = counts(db)
    evidence = {
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "first_run_counts": first,
        "second_run_counts": second,
        "idempotent": first == second,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["idempotent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
