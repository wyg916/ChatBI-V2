from abc import ABC, abstractmethod

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SemanticModel, SemanticVersion


class SemanticEngine(ABC):
    """Stable boundary for semantic model validation and publication."""

    @abstractmethod
    def capabilities(self) -> dict:
        pass

    @abstractmethod
    def validate(self, model: SemanticModel) -> list[str]:
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

    def validate(self, model: SemanticModel) -> list[str]:
        errors: list[str] = []
        entity_names = {entity.name for entity in model.entities}
        for relation in model.relations:
            if relation.left_entity not in entity_names:
                errors.append(f"Unknown left entity: {relation.left_entity}")
            if relation.right_entity not in entity_names:
                errors.append(f"Unknown right entity: {relation.right_entity}")
        return errors

    def compile(self, model: SemanticModel) -> dict:
        return {
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
        errors = self.validate(model)
        if errors:
            raise ValueError("; ".join(errors))
        next_version = model.version + 1 if model.status == "PUBLISHED" else model.version
        if db.scalar(select(SemanticVersion).where(SemanticVersion.semantic_model_id == model.id, SemanticVersion.version == next_version)):
            next_version += 1
        version = SemanticVersion(semantic_model_id=model.id, version=next_version, snapshot=self.compile(model))
        model.version = next_version
        model.status = "PUBLISHED"
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

    def validate(self, model: SemanticModel) -> list[str]:
        return self.delegate.validate(model)

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
