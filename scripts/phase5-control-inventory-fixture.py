from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.models import (
    AppUser,
    BusinessTerm,
    Dashboard,
    Dimension,
    Metric,
    SemanticEntity,
    SemanticModel,
    SemanticRelation,
    VerifiedAnswer,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.performance.run_v13_phase5_api_load import BootstrapReceipt, MetadataBootstrap


TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")
PASSWORD_ENV = "CHATBI_CONTROL_FIXTURE_BASE_PASSWORD"
DATABASE_ENV = "CHATBI_PHASE5_DATABASE_URL"
FIXTURE_PREFIX = "Phase5 Control"


def _identity(token: str) -> tuple[str, str]:
    if not TOKEN_RE.fullmatch(token):
        raise ValueError("control fixture token must be exactly 12 lowercase hex characters")
    base_password = os.getenv(PASSWORD_ENV, "")
    if len(base_password) < 10:
        raise RuntimeError(f"{PASSWORD_ENV} is required and must contain at least 10 characters")
    return (
        f"phase5controls+{token}@load.chatbi.invalid",
        f"{base_password}-{token}-ControlInventory",
    )


def _engine(database_url: str, schema: str):
    return create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={schema}"},
    )


def _fixture_names(token: str) -> dict[str, str]:
    return {
        "semantic_model": f"{FIXTURE_PREFIX} Semantic {token}",
        "answer": f"{FIXTURE_PREFIX} Answer {token}",
        "dashboard": f"{FIXTURE_PREFIX} Dashboard {token}",
    }


def _unique(items, key):
    seen: set[object] = set()
    for item in items:
        identity = key(item)
        if identity in seen:
            continue
        seen.add(identity)
        yield item


def create_fixture(
    *, database_url: str, schema: str, workspace_id: str, datasource_id: str,
    semantic_model_id: str, token: str,
) -> dict:
    email, password = _identity(token)
    names = _fixture_names(token)
    engine = _engine(database_url, schema)
    try:
        with Session(engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(select(AppUser).where(AppUser.email == email))
            if existing is not None:
                raise RuntimeError("CONTROL_FIXTURE_COLLISION")
            collisions = int(session.scalar(
                select(func.count(SemanticModel.id)).where(SemanticModel.name == names["semantic_model"])
            ) or 0) + int(session.scalar(
                select(func.count(VerifiedAnswer.id)).where(VerifiedAnswer.question == names["answer"])
            ) or 0) + int(session.scalar(
                select(func.count(Dashboard.id)).where(Dashboard.name == names["dashboard"])
            ) or 0)
            if collisions:
                raise RuntimeError("CONTROL_RESOURCE_FIXTURE_COLLISION")
            source_model = session.get(SemanticModel, semantic_model_id)
            if (
                source_model is None
                or source_model.workspace_id != workspace_id
                or source_model.datasource_id != datasource_id
            ):
                raise RuntimeError("CONTROL_SOURCE_MODEL_SCOPE_INVALID")
            session.add(AppUser(
                workspace_id=workspace_id,
                email=email,
                display_name="Phase5 Control Inventory",
                role="ADMIN",
                status="ACTIVE",
                password_hash=hash_password(password),
            ))
            model = SemanticModel(
                workspace_id=workspace_id,
                datasource_id=datasource_id,
                name=names["semantic_model"],
                description="Run-scoped Phase5 control certification semantic model",
                status="DRAFT",
                version=1,
            )
            session.add(model)
            session.flush()
            session.add_all([
                SemanticEntity(
                    semantic_model_id=model.id,
                    name=item.name,
                    source_table=item.source_table,
                    primary_key=item.primary_key,
                    time_dimension=item.time_dimension,
                )
                for item in _unique(source_model.entities, lambda value: value.name)
            ])
            session.add_all([
                Metric(
                    semantic_model_id=model.id,
                    name=item.name,
                    label=item.label,
                    description=item.description,
                    expression=item.expression,
                    aggregation=item.aggregation,
                    filters=item.filters,
                )
                for item in _unique(source_model.metrics, lambda value: value.name)
            ])
            session.add_all([
                Dimension(
                    semantic_model_id=model.id,
                    name=item.name,
                    label=item.label,
                    source_column=item.source_column,
                    type=item.type,
                )
                for item in _unique(source_model.dimensions, lambda value: value.name)
            ])
            session.add_all([
                SemanticRelation(
                    semantic_model_id=model.id,
                    left_entity=item.left_entity,
                    right_entity=item.right_entity,
                    join_type=item.join_type,
                    join_keys=item.join_keys,
                    cardinality=item.cardinality,
                )
                for item in _unique(
                    source_model.relations,
                    lambda value: (value.left_entity, value.right_entity, value.join_type),
                )
            ])
            session.add_all([
                BusinessTerm(
                    semantic_model_id=model.id,
                    term=item.term,
                    synonyms=item.synonyms,
                    definition=item.definition,
                    mapped_object=item.mapped_object,
                )
                for item in _unique(source_model.business_terms, lambda value: value.term)
            ])
            answer = VerifiedAnswer(
                workspace_id=workspace_id,
                question=names["answer"],
                module="Phase5 Control Certification",
                sql_synced=False,
                model_name=names["semantic_model"],
                owner_name="Phase5 Control Certification",
                status="DRAFT",
                accuracy_percent=0,
            )
            dashboard = Dashboard(
                workspace_id=workspace_id,
                name=names["dashboard"],
                description="Run-scoped Phase5 control certification dashboard",
                card_count=0,
                is_shared=False,
            )
            session.add_all([answer, dashboard])
            session.flush()
    finally:
        engine.dispose()
    return {
        "schema_version": "chatbi.v13.phase5.control-inventory-fixture.v1",
        "status": "CREATED",
        "temporary_users": 1,
        "temporary_semantic_models": 1,
        "temporary_answers": 1,
        "temporary_dashboards": 1,
        "role": "ADMIN",
        "credential_persisted": False,
        "semantic_model_id": model.id,
        "semantic_model_name": names["semantic_model"],
        "answer_id": answer.id,
        "answer_question": names["answer"],
        "dashboard_id": dashboard.id,
        "dashboard_name": names["dashboard"],
    }


def cleanup_fixture(
    *,
    database_url: str,
    schema: str,
    workspace_id: str,
    datasource_id: str,
    semantic_model_id: str,
    token: str,
) -> dict:
    email, _password = _identity(token)
    engine = _engine(database_url, schema)
    try:
        with Session(engine) as session:
            users = list(session.scalars(select(AppUser).where(AppUser.email == email)))
    finally:
        engine.dispose()
    if len(users) != 1:
        raise RuntimeError("CONTROL_FIXTURE_SCOPE_NOT_EXACT")
    bootstrap = MetadataBootstrap(
        database_url,
        metadata_schema=schema,
        workspace_id=workspace_id,
        datasource_id=datasource_id,
        semantic_model_id=semantic_model_id,
        request_prefix=f"phase5api-{token}-",
    )
    try:
        cleanup = bootstrap.cleanup(BootstrapReceipt(
            metadata_schema=schema,
            user_ids=(str(users[0].id),),
            users_created=1,
            grants_created=0,
        ))
    finally:
        bootstrap.close()
    try:
        with Session(engine) as session, session.begin():
            resources_deleted = {
                "answers": int(session.execute(delete(VerifiedAnswer).where(
                    VerifiedAnswer.question.like(f"{FIXTURE_PREFIX}%{token}%")
                )).rowcount or 0),
                "dashboards": int(session.execute(delete(Dashboard).where(
                    Dashboard.name.like(f"{FIXTURE_PREFIX}%{token}%")
                )).rowcount or 0),
                "semantic_models": int(session.execute(delete(SemanticModel).where(
                    SemanticModel.name.like(f"{FIXTURE_PREFIX}%{token}%")
                )).rowcount or 0),
            }
        with Session(engine) as session:
            resource_remaining = {
                "answers": int(session.scalar(select(func.count(VerifiedAnswer.id)).where(
                    VerifiedAnswer.question.like(f"{FIXTURE_PREFIX}%{token}%")
                )) or 0),
                "dashboards": int(session.scalar(select(func.count(Dashboard.id)).where(
                    Dashboard.name.like(f"{FIXTURE_PREFIX}%{token}%")
                )) or 0),
                "semantic_models": int(session.scalar(select(func.count(SemanticModel.id)).where(
                    SemanticModel.name.like(f"{FIXTURE_PREFIX}%{token}%")
                )) or 0),
            }
    finally:
        engine.dispose()
    resources_absent = not any(resource_remaining.values())
    return {
        "schema_version": "chatbi.v13.phase5.control-inventory-fixture-cleanup.v1",
        "status": "PASS" if cleanup.get("metadata_absence_verified") and resources_absent else "FAIL",
        "temporary_users": 1,
        "paid_provider_calls": 0,
        "paid_cost_cny": 0.0,
        "credential_persisted": False,
        "cleanup": cleanup,
        "resources_deleted": resources_deleted,
        "resource_remaining": resource_remaining,
        "resource_absence_verified": resources_absent,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or clean a run-scoped Phase5 control inventory admin")
    parser.add_argument("mode", choices=("create", "cleanup"))
    parser.add_argument("--schema", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--datasource-id", required=True)
    parser.add_argument("--semantic-model-id", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    database_url = os.getenv(DATABASE_ENV, "")
    if not database_url:
        raise SystemExit(f"{DATABASE_ENV} is required")
    if args.mode == "create":
        result = create_fixture(
            database_url=database_url,
            schema=args.schema,
            workspace_id=args.workspace_id,
            datasource_id=args.datasource_id,
            semantic_model_id=args.semantic_model_id,
            token=args.token,
        )
    else:
        result = cleanup_fixture(
            database_url=database_url,
            schema=args.schema,
            workspace_id=args.workspace_id,
            datasource_id=args.datasource_id,
            semantic_model_id=args.semantic_model_id,
            token=args.token,
        )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps({key: result[key] for key in ("status", "temporary_users", "credential_persisted")}))
    return 0 if result["status"] in {"CREATED", "PASS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
