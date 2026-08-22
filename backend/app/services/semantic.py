from sqlalchemy import or_, select
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


def list_semantic_models(
    db: Session,
    *,
    workspace_id: str | None = None,
    query: str = "",
    status: str = "ALL",
    datasource_id: str = "ALL",
) -> list[SemanticModel]:
    statement = select(SemanticModel).options(*SEMANTIC_LOADS)
    if workspace_id:
        statement = statement.where(SemanticModel.workspace_id == workspace_id)
    if query.strip():
        keyword = f"%{query.strip()}%"
        statement = statement.where(or_(SemanticModel.name.ilike(keyword), SemanticModel.description.ilike(keyword)))
    if status != "ALL":
        statement = statement.where(SemanticModel.status == status)
    if datasource_id != "ALL":
        statement = statement.where(SemanticModel.datasource_id == datasource_id)
    return list(db.scalars(statement.order_by(SemanticModel.created_at.desc())))


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
