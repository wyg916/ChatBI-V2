from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import SemanticModel


SEMANTIC_LOADS = (
    selectinload(SemanticModel.entities),
    selectinload(SemanticModel.metrics),
    selectinload(SemanticModel.dimensions),
    selectinload(SemanticModel.relations),
    selectinload(SemanticModel.business_terms),
)


def get_semantic_model(db: Session, model_id: str) -> SemanticModel | None:
    return db.scalar(select(SemanticModel).where(SemanticModel.id == model_id).options(*SEMANTIC_LOADS))


def semantic_payload(model: SemanticModel) -> dict:
    return {
        "id": model.id,
        "name": model.name,
        "description": model.description,
        "datasource_id": model.datasource_id,
        "status": model.status,
        "version": model.version,
        "created_at": model.created_at,
        "updated_at": model.updated_at,
        "entities": model.entities,
        "metrics": model.metrics,
        "dimensions": model.dimensions,
        "relationships": model.relations,
        "business_terms": model.business_terms,
    }
