from abc import ABC, abstractmethod

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    BusinessTerm,
    DataSourceColumn,
    DataSourceSchema,
    DataSourceTable,
    Dimension,
    Metric,
    SemanticEntity,
    SemanticModel,
    SemanticRelation,
    SemanticVersion,
)


class SemanticEngine(ABC):
    """Stable boundary for semantic model validation and publication."""

    @abstractmethod
    def capabilities(self) -> dict:
        pass

    @abstractmethod
    def validate(self, model: SemanticModel, db: Session | None = None) -> list[str]:
        pass

    @abstractmethod
    def publish(self, db: Session, model: SemanticModel) -> SemanticVersion:
        pass

    @abstractmethod
    def compile(self, model: SemanticModel) -> dict:
        """Compile a ChatBI semantic model into an engine-neutral manifest."""
        pass


class LocalSemanticEngine(SemanticEngine):
    def capabilities(self) -> dict:
        return {"engine": "local", "runtime_available": True, "validation": True, "manifest_compile": True}

    def validate(self, model: SemanticModel, db: Session | None = None) -> list[str]:
        errors: list[str] = []
        entity_by_name = {entity.name: entity for entity in model.entities}
        if len(entity_by_name) != len(model.entities):
            errors.append("Entity names must be unique")
        if not entity_by_name:
            errors.append("At least one entity is required")
        metric_by_name = {metric.name: metric for metric in model.metrics}
        dimension_by_name = {dimension.name: dimension for dimension in model.dimensions}
        if len(metric_by_name) != len(model.metrics):
            errors.append("Metric names must be unique")
        if len(dimension_by_name) != len(model.dimensions):
            errors.append("Dimension names must be unique")
        if not metric_by_name:
            errors.append("At least one metric is required")
        for relation in model.relations:
            if relation.left_entity not in entity_by_name:
                errors.append(f"Unknown left entity: {relation.left_entity}")
            if relation.right_entity not in entity_by_name:
                errors.append(f"Unknown right entity: {relation.right_entity}")
            if relation.left_entity == relation.right_entity:
                errors.append(f"Relationship cannot self-reference entity: {relation.left_entity}")

        valid_targets = {
            *{f"entity.{name}" for name in entity_by_name},
            *{f"metric.{name}" for name in metric_by_name},
            *{f"dimension.{name}" for name in dimension_by_name},
        }
        for term in model.business_terms:
            if term.mapped_object not in valid_targets:
                errors.append(f"Business term {term.term} references unknown object: {term.mapped_object}")

        if db is None:
            return sorted(set(errors))

        schema_ids = list(db.scalars(select(DataSourceSchema.id).where(DataSourceSchema.datasource_id == model.datasource_id)))
        tables = list(db.scalars(select(DataSourceTable).where(DataSourceTable.schema_id.in_(schema_ids)))) if schema_ids else []
        table_by_name = {table.name: table for table in tables}
        table_ids = [table.id for table in tables]
        columns = list(db.scalars(select(DataSourceColumn).where(DataSourceColumn.table_id.in_(table_ids)))) if table_ids else []
        columns_by_table: dict[str, set[str]] = {name: set() for name in table_by_name}
        table_name_by_id = {table.id: table.name for table in tables}
        for column in columns:
            columns_by_table.setdefault(table_name_by_id[column.table_id], set()).add(column.name)

        for entity in model.entities:
            table_name = entity.source_table.split(".")[-1]
            if table_name not in table_by_name:
                errors.append(f"Entity {entity.name} references unknown table: {entity.source_table}")
                continue
            available = columns_by_table.get(table_name, set())
            if entity.primary_key not in available:
                errors.append(f"Entity {entity.name} references unknown primary key: {entity.primary_key}")
            if entity.time_dimension and entity.time_dimension not in available:
                errors.append(f"Entity {entity.name} references unknown time dimension: {entity.time_dimension}")

        def validate_qualified(reference: str, owner: str) -> None:
            if "." not in reference:
                errors.append(f"{owner} must use an entity-qualified column: {reference}")
                return
            entity_name, column_name = reference.split(".", 1)
            entity = entity_by_name.get(entity_name)
            if entity is None:
                errors.append(f"{owner} references unknown entity: {entity_name}")
                return
            table_name = entity.source_table.split(".")[-1]
            if column_name not in columns_by_table.get(table_name, set()):
                errors.append(f"{owner} references unknown column: {reference}")

        for dimension in model.dimensions:
            validate_qualified(dimension.source_column, f"Dimension {dimension.name}")
        for metric in model.metrics:
            references = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\b", metric.expression)
            if not references:
                errors.append(f"Metric {metric.name} has no entity-qualified source column")
            for reference in references:
                validate_qualified(reference, f"Metric {metric.name}")
            bare = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\b", "", metric.expression)))
            allowed_tokens = {"sum", "count", "avg", "min", "max", "nullif", "case", "when", "then", "else", "end", "and", "or"}
            unknown = sorted(token for token in bare if token.lower() not in allowed_tokens and token not in metric_by_name)
            if unknown:
                errors.append(f"Metric {metric.name} has invalid dependencies: {', '.join(unknown)}")

        for relation in model.relations:
            left = entity_by_name.get(relation.left_entity)
            right = entity_by_name.get(relation.right_entity)
            if left is None or right is None:
                continue
            left_columns = columns_by_table.get(left.source_table.split(".")[-1], set())
            right_columns = columns_by_table.get(right.source_table.split(".")[-1], set())
            for pair in relation.join_keys:
                if pair.get("left") not in left_columns:
                    errors.append(f"Relationship {relation.left_entity}->{relation.right_entity} has invalid left key: {pair.get('left')}")
                if pair.get("right") not in right_columns:
                    errors.append(f"Relationship {relation.left_entity}->{relation.right_entity} has invalid right key: {pair.get('right')}")
        return sorted(set(errors))

    def compile(self, model: SemanticModel) -> dict:
        return {
            "snapshot_schema": "chatbi-semantic-v1",
            "name": model.name,
            "description": model.description,
            "datasource_id": model.datasource_id,
            "entities": [{"name": item.name, "source_table": item.source_table, "primary_key": item.primary_key, "time_dimension": item.time_dimension} for item in model.entities],
            "metrics": [{"name": item.name, "label": item.label, "expression": item.expression, "aggregation": item.aggregation, "filters": item.filters} for item in model.metrics],
            "dimensions": [{"name": item.name, "label": item.label, "source_column": item.source_column, "type": item.type} for item in model.dimensions],
            "relationships": [{"left_entity": item.left_entity, "right_entity": item.right_entity, "join_type": item.join_type, "join_keys": item.join_keys, "cardinality": item.cardinality} for item in model.relations],
            "business_terms": [{"term": item.term, "synonyms": item.synonyms, "definition": item.definition, "mapped_object": item.mapped_object} for item in model.business_terms],
        }

    def publish(self, db: Session, model: SemanticModel) -> SemanticVersion:
        errors = self.validate(model, db)
        if errors:
            raise ValueError("; ".join(errors))
        current_max = db.scalar(select(func.max(SemanticVersion.version)).where(SemanticVersion.semantic_model_id == model.id))
        next_version = (current_max or 0) + 1
        snapshot = self.compile(model)
        snapshot["published_version"] = next_version
        version = SemanticVersion(semantic_model_id=model.id, version=next_version, snapshot=snapshot)
        model.version = next_version
        model.status = "PUBLISHED"
        db.add(version)
        db.commit()
        db.refresh(version)
        return version

    def rollback(self, db: Session, model: SemanticModel, target_version: int) -> SemanticVersion:
        source = db.scalar(select(SemanticVersion).where(
            SemanticVersion.semantic_model_id == model.id,
            SemanticVersion.version == target_version,
        ))
        if source is None:
            raise ValueError(f"Semantic version {target_version} does not exist")
        snapshot = source.snapshot
        for child_type in (BusinessTerm, SemanticRelation, Dimension, Metric, SemanticEntity):
            for child in db.scalars(select(child_type).where(child_type.semantic_model_id == model.id)):
                db.delete(child)
        db.flush()
        model.name = snapshot["name"]
        model.description = snapshot.get("description")
        model.datasource_id = snapshot["datasource_id"]
        db.add_all([SemanticEntity(semantic_model_id=model.id, **item) for item in snapshot.get("entities", [])])
        db.add_all([Metric(semantic_model_id=model.id, **item) for item in snapshot.get("metrics", [])])
        db.add_all([Dimension(semantic_model_id=model.id, **item) for item in snapshot.get("dimensions", [])])
        db.add_all([SemanticRelation(semantic_model_id=model.id, **item) for item in snapshot.get("relationships", [])])
        db.add_all([BusinessTerm(semantic_model_id=model.id, **item) for item in snapshot.get("business_terms", [])])
        db.flush()
        db.expire(model)
        refreshed = db.scalar(
            select(SemanticModel).where(SemanticModel.id == model.id).options(
                selectinload(SemanticModel.entities), selectinload(SemanticModel.metrics),
                selectinload(SemanticModel.dimensions), selectinload(SemanticModel.relations),
                selectinload(SemanticModel.business_terms),
            )
        )
        if refreshed is None:
            raise ValueError("Semantic model disappeared during rollback")
        errors = self.validate(refreshed, db)
        if errors:
            raise ValueError("Rollback snapshot is no longer valid: " + "; ".join(errors))
        current_max = db.scalar(select(func.max(SemanticVersion.version)).where(SemanticVersion.semantic_model_id == model.id)) or 0
        next_version = current_max + 1
        rollback_snapshot = self.compile(refreshed)
        rollback_snapshot.update({"published_version": next_version, "rollback_source_version": target_version})
        version = SemanticVersion(semantic_model_id=model.id, version=next_version, snapshot=rollback_snapshot)
        refreshed.version = next_version
        refreshed.status = "PUBLISHED"
        db.add(version)
        db.commit()
        db.refresh(version)
        return version


class WrenSemanticAdapter(SemanticEngine):
    """Integration boundary for a future Wren runtime; no Wren internal code is copied."""

    def __init__(self, delegate: SemanticEngine | None = None):
        self.delegate = delegate or LocalSemanticEngine()

    def capabilities(self) -> dict:
        return {
            "engine": "wren",
            "runtime_available": False,
            "validation": True,
            "manifest_compile": True,
            "note": "Day 1 manifest seam; Wren runtime is not embedded",
        }

    def validate(self, model: SemanticModel, db: Session | None = None) -> list[str]:
        return self.delegate.validate(model, db)

    def publish(self, db: Session, model: SemanticModel) -> SemanticVersion:
        return self.delegate.publish(db, model)

    def compile(self, model: SemanticModel) -> dict:
        snapshot = self.delegate.compile(model)
        return {
            "catalog": "chatbi",
            "schema": "semantic",
            "models": snapshot["entities"],
            "metrics": snapshot["metrics"],
            "relationships": snapshot["relationships"],
            "metadata": {"source": "chatbi-semantic-snapshot", "runtime_available": False},
        }
