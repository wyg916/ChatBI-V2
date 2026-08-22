from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.model_gateway.contracts import RequestContext
from app.models import (
    DataSource,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    SemanticModel,
    VerifiedAnswer,
    Workspace,
)
from app.query.contracts import LinkedObject, QueryContext, SecurityPolicy
from app.services.semantic import get_semantic_model


def _tokens(value: str) -> set[str]:
    ascii_words = re.findall(r"[a-z0-9_]+", value.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]{1,6}", value)
    grams: set[str] = set(ascii_words)
    for item in chinese:
        grams.add(item)
        grams.update(item[index:index + 2] for index in range(max(0, len(item) - 1)))
    return grams


def _score(question: str, names: list[str]) -> tuple[float, list[str]]:
    normalized = question.lower()
    question_tokens = _tokens(question)
    evidence: list[str] = []
    score = 0.0
    for name in names:
        candidate = (name or "").strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in normalized:
            score = max(score, 1.0 if len(candidate) > 1 else 0.82)
            evidence.append(f"exact:{candidate}")
            continue
        overlap = question_tokens & _tokens(candidate)
        if overlap:
            score = max(score, min(0.9, 0.42 + len(overlap) * 0.14))
            evidence.append("token:" + ",".join(sorted(overlap)))
    return score, sorted(set(evidence))


class ContextBuilder:
    """Build a bounded, traceable query context from ChatBI-owned metadata."""

    def __init__(self, token_budget: int | None = None):
        self.token_budget = token_budget or get_settings().context_token_budget

    def build(
        self,
        db: Session,
        *,
        question: str,
        workspace: Workspace,
        datasource: DataSource,
        semantic_model: SemanticModel,
        row_limit: int,
        cache_role: str = "SYSTEM",
        request_context: RequestContext | None = None,
    ) -> QueryContext:
        model = get_semantic_model(db, semantic_model.id)
        if model is None:
            raise LookupError("Semantic model not found")

        schema_rows = list(db.scalars(
            select(DataSourceSchema).where(DataSourceSchema.datasource_id == datasource.id).order_by(DataSourceSchema.name)
        ))
        schema_ids = [item.id for item in schema_rows]
        table_rows = list(db.scalars(
            select(DataSourceTable).where(DataSourceTable.schema_id.in_(schema_ids)).order_by(DataSourceTable.name)
        )) if schema_ids else []
        table_ids = [item.id for item in table_rows]
        column_rows = list(db.scalars(
            select(DataSourceColumn).where(DataSourceColumn.table_id.in_(table_ids)).order_by(DataSourceColumn.name)
        )) if table_ids else []
        tables_by_id = {item.id: item for item in table_rows}

        linked: list[LinkedObject] = []
        for metric in model.metrics:
            score, evidence = _score(question, [metric.name, metric.label, metric.description or ""])
            linked.append(LinkedObject(
                object_type="metric", object_id=metric.id, name=metric.name, label=metric.label,
                score=score, evidence=evidence,
            ))
        for dimension in model.dimensions:
            score, evidence = _score(question, [dimension.name, dimension.label, dimension.source_column])
            linked.append(LinkedObject(
                object_type="dimension", object_id=dimension.id, name=dimension.name, label=dimension.label,
                qualified_name=dimension.source_column, score=score, evidence=evidence,
            ))
        for entity in model.entities:
            score, evidence = _score(question, [entity.name, entity.source_table])
            linked.append(LinkedObject(
                object_type="entity", object_id=entity.id, name=entity.name, label=entity.name,
                qualified_name=entity.source_table, score=score, evidence=evidence,
            ))
        for term in model.business_terms:
            score, evidence = _score(question, [term.term, term.definition, *term.synonyms])
            linked.append(LinkedObject(
                object_type="business_term", object_id=term.id, name=term.term, label=term.term,
                qualified_name=term.mapped_object, score=score, evidence=evidence,
            ))
        for table in table_rows:
            score, evidence = _score(question, [table.name, table.comment or ""])
            linked.append(LinkedObject(
                object_type="table", object_id=table.id, name=table.name, label=table.comment or table.name,
                qualified_name=table.qualified_name, score=score, evidence=evidence,
            ))
        for column in column_rows:
            table = tables_by_id[column.table_id]
            score, evidence = _score(question, [column.name, column.comment or "", *[str(v) for v in column.sample_values[:5]]])
            linked.append(LinkedObject(
                object_type="column", object_id=column.id, name=column.name, label=column.comment or column.name,
                qualified_name=f"{table.name}.{column.name}", score=score, evidence=evidence,
            ))

        linked.sort(key=lambda item: (-item.score, item.object_type, item.qualified_name or item.name, item.object_id))
        trace = [item for item in linked if item.score > 0][:60]
        table_candidates = [item for item in linked if item.object_type == "table" and item.score > 0][:12]
        column_candidates = [item for item in linked if item.object_type == "column" and item.score > 0][:40]
        if not table_candidates:
            table_candidates = [item for item in linked if item.object_type == "table"][:12]
        if not column_candidates:
            column_candidates = [item for item in linked if item.object_type == "column"][:40]

        allowed_columns: dict[str, list[str]] = {}
        for column in column_rows:
            allowed_columns.setdefault(tables_by_id[column.table_id].name.lower(), []).append(column.name.lower())
        for values in allowed_columns.values():
            values.sort()

        examples = list(db.scalars(
            select(VerifiedAnswer)
            .where(VerifiedAnswer.workspace_id == workspace.id, VerifiedAnswer.sql_text.is_not(None))
            .order_by(VerifiedAnswer.accuracy_percent.desc(), VerifiedAnswer.updated_at.desc())
            .limit(8)
        ))
        verified_examples = [
            {"question": item.question, "sql": item.sql_text, "signature": item.result_signature}
            for item in examples
        ]
        entities = [
            {"id": item.id, "name": item.name, "source_table": item.source_table,
             "primary_key": item.primary_key, "time_dimension": item.time_dimension}
            for item in sorted(model.entities, key=lambda item: item.name)
        ]
        metrics = [
            {"id": item.id, "name": item.name, "label": item.label, "description": item.description,
             "expression": item.expression, "aggregation": item.aggregation, "filters": item.filters}
            for item in sorted(model.metrics, key=lambda item: item.name)
        ]
        dimensions = [
            {"id": item.id, "name": item.name, "label": item.label,
             "source_column": item.source_column, "type": item.type}
            for item in sorted(model.dimensions, key=lambda item: item.name)
        ]
        relationships = [
            {"id": item.id, "left_entity": item.left_entity, "right_entity": item.right_entity,
             "join_type": item.join_type, "join_keys": item.join_keys, "cardinality": item.cardinality}
            for item in sorted(model.relations, key=lambda item: (item.left_entity, item.right_entity))
        ]
        terms = [
            {"id": item.id, "term": item.term, "synonyms": item.synonyms,
             "definition": item.definition, "mapped_object": item.mapped_object}
            for item in sorted(model.business_terms, key=lambda item: item.term)
        ]
        knowledge_version = hashlib.sha256(json.dumps(
            {"terms": terms, "verified_sql": verified_examples},
            ensure_ascii=False, sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest()
        data_version = hashlib.sha256(json.dumps(
            {
                "datasource_id": datasource.id,
                "last_sync_at": datasource.last_sync_at,
                "schemas": [item.name for item in schema_rows],
                "tables": [item.qualified_name for item in table_rows],
                "columns": [item.qualified_name for item in column_rows],
            },
            ensure_ascii=False, sort_keys=True, default=str,
        ).encode("utf-8")).hexdigest()
        input_signature = hashlib.sha256(question.strip().lower().encode("utf-8")).hexdigest()

        estimated_tokens = (
            len(question) + sum(len(str(value)) for value in entities + metrics + dimensions + relationships + terms)
            + sum(len(str(item.model_dump())) for item in trace + table_candidates + column_candidates)
        ) // 3
        truncated = estimated_tokens > self.token_budget
        if truncated:
            trace = trace[:30]
            table_candidates = table_candidates[:8]
            column_candidates = column_candidates[:24]
            verified_examples = verified_examples[:3]
            estimated_tokens = min(estimated_tokens, self.token_budget)

        settings = get_settings()
        return QueryContext(
            request_id=request_context.request_id if request_context else "SYSTEM",
            trace_id=request_context.trace_id if request_context else "TRACE-SYSTEM",
            route=(request_context.route or "DATA_QUERY") if request_context else "DATA_QUERY",
            user_id=request_context.user_id if request_context else "SYSTEM",
            conversation_id=request_context.conversation_id if request_context else None,
            permission_hash=request_context.permission_hash if request_context else "system",
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            datasource_id=datasource.id,
            datasource_name=datasource.name,
            dialect=datasource.type,
            schema_name=datasource.schema,
            semantic_model_id=model.id,
            semantic_model_name=model.name,
            semantic_model_version=model.version,
            cache_role=cache_role,
            knowledge_version=knowledge_version,
            data_version=data_version,
            input_signature=input_signature,
            entities=entities,
            candidate_tables=table_candidates,
            candidate_columns=column_candidates,
            metrics=metrics,
            dimensions=dimensions,
            relationships=relationships,
            business_terms=terms,
            verified_sql_examples=verified_examples,
            linking_trace=trace,
            now=datetime.now(timezone.utc),
            row_limit=row_limit,
            token_budget=self.token_budget,
            estimated_tokens=estimated_tokens,
            truncated=truncated,
            security_policy=SecurityPolicy(
                row_limit=row_limit,
                timeout_ms=settings.query_timeout_ms,
                allowed_schemas=sorted({item.name.lower() for item in schema_rows}),
                allowed_tables=sorted(item.name.lower() for item in table_rows),
                allowed_columns=allowed_columns,
            ),
        )
