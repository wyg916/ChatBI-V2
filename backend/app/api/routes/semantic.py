from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import (
    BusinessTerm,
    DataSource,
    Dimension,
    Metric,
    SemanticEntity,
    SemanticModel,
    SemanticRelation,
)
from app.schemas.semantic import (
    BusinessTermCreate,
    BusinessTermRead,
    DimensionCreate,
    DimensionRead,
    EntityRead,
    MetricCreate,
    MetricRead,
    PublishResult,
    RelationRead,
    SemanticEntityCreate,
    SemanticModelCreate,
    SemanticModelDetail,
    SemanticModelRead,
    SemanticModelUpdate,
    SemanticRelationCreate,
)
from app.semantic import LocalSemanticEngine
from app.services.datasources import default_workspace
from app.services.semantic import get_semantic_model, list_semantic_models, semantic_payload

router = APIRouter(prefix="/semantic-models", tags=["semantic models"])


def _get_or_404(db: Session, model_id: str) -> SemanticModel:
    model = get_semantic_model(db, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Semantic model not found")
    return model


@router.post("", response_model=SemanticModelRead, status_code=status.HTTP_201_CREATED)
def create_model(data: SemanticModelCreate, db: Session = Depends(get_db)):
    if db.get(DataSource, data.datasource_id) is None:
        raise HTTPException(status_code=404, detail="Datasource not found")
    workspace = default_workspace(db)
    model = SemanticModel(workspace_id=workspace.id, **data.model_dump())
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


@router.get("", response_model=list[SemanticModelDetail])
def list_models(db: Session = Depends(get_db)):
    return [semantic_payload(model) for model in list_semantic_models(db)]


@router.get("/{model_id}", response_model=SemanticModelDetail)
def get_model(model_id: str, db: Session = Depends(get_db)):
    return semantic_payload(_get_or_404(db, model_id))


@router.put("/{model_id}", response_model=SemanticModelRead)
def update_model(model_id: str, data: SemanticModelUpdate, db: Session = Depends(get_db)):
    model = _get_or_404(db, model_id)
    if data.datasource_id is not None and db.get(DataSource, data.datasource_id) is None:
        raise HTTPException(status_code=404, detail="Datasource not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(model, key, value)
    db.commit()
    db.refresh(model)
    return model


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_model(model_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, model_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _add_child(db: Session, model_id: str, child):
    _get_or_404(db, model_id)
    child.semantic_model_id = model_id
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


def _child_or_404(db: Session, model_id: str, child_type, child_id: str):
    _get_or_404(db, model_id)
    child = db.get(child_type, child_id)
    if child is None or child.semantic_model_id != model_id:
        raise HTTPException(status_code=404, detail="Semantic resource not found")
    return child


def _replace_child(db: Session, model_id: str, child_type, child_id: str, data):
    child = _child_or_404(db, model_id, child_type, child_id)
    for key, value in data.model_dump().items():
        setattr(child, key, value)
    db.commit()
    db.refresh(child)
    return child


def _delete_child(db: Session, model_id: str, child_type, child_id: str) -> Response:
    db.delete(_child_or_404(db, model_id, child_type, child_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{model_id}/entities", response_model=EntityRead, status_code=status.HTTP_201_CREATED)
def add_entity(model_id: str, data: SemanticEntityCreate, db: Session = Depends(get_db)):
    return _add_child(db, model_id, SemanticEntity(**data.model_dump()))


@router.put("/{model_id}/entities/{resource_id}", response_model=EntityRead)
def update_entity(model_id: str, resource_id: str, data: SemanticEntityCreate, db: Session = Depends(get_db)):
    return _replace_child(db, model_id, SemanticEntity, resource_id, data)


@router.delete("/{model_id}/entities/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entity(model_id: str, resource_id: str, db: Session = Depends(get_db)):
    return _delete_child(db, model_id, SemanticEntity, resource_id)


@router.post("/{model_id}/metrics", response_model=MetricRead, status_code=status.HTTP_201_CREATED)
def add_metric(model_id: str, data: MetricCreate, db: Session = Depends(get_db)):
    return _add_child(db, model_id, Metric(**data.model_dump()))


@router.put("/{model_id}/metrics/{resource_id}", response_model=MetricRead)
def update_metric(model_id: str, resource_id: str, data: MetricCreate, db: Session = Depends(get_db)):
    return _replace_child(db, model_id, Metric, resource_id, data)


@router.delete("/{model_id}/metrics/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metric(model_id: str, resource_id: str, db: Session = Depends(get_db)):
    return _delete_child(db, model_id, Metric, resource_id)


@router.post("/{model_id}/dimensions", response_model=DimensionRead, status_code=status.HTTP_201_CREATED)
def add_dimension(model_id: str, data: DimensionCreate, db: Session = Depends(get_db)):
    return _add_child(db, model_id, Dimension(**data.model_dump()))


@router.put("/{model_id}/dimensions/{resource_id}", response_model=DimensionRead)
def update_dimension(model_id: str, resource_id: str, data: DimensionCreate, db: Session = Depends(get_db)):
    return _replace_child(db, model_id, Dimension, resource_id, data)


@router.delete("/{model_id}/dimensions/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dimension(model_id: str, resource_id: str, db: Session = Depends(get_db)):
    return _delete_child(db, model_id, Dimension, resource_id)


@router.post("/{model_id}/relationships", response_model=RelationRead, status_code=status.HTTP_201_CREATED)
def add_relationship(model_id: str, data: SemanticRelationCreate, db: Session = Depends(get_db)):
    return _add_child(db, model_id, SemanticRelation(**data.model_dump()))


@router.put("/{model_id}/relationships/{resource_id}", response_model=RelationRead)
def update_relationship(model_id: str, resource_id: str, data: SemanticRelationCreate, db: Session = Depends(get_db)):
    return _replace_child(db, model_id, SemanticRelation, resource_id, data)


@router.delete("/{model_id}/relationships/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relationship(model_id: str, resource_id: str, db: Session = Depends(get_db)):
    return _delete_child(db, model_id, SemanticRelation, resource_id)


@router.post("/{model_id}/business-terms", response_model=BusinessTermRead, status_code=status.HTTP_201_CREATED)
def add_business_term(model_id: str, data: BusinessTermCreate, db: Session = Depends(get_db)):
    return _add_child(db, model_id, BusinessTerm(**data.model_dump()))


@router.put("/{model_id}/business-terms/{resource_id}", response_model=BusinessTermRead)
def update_business_term(model_id: str, resource_id: str, data: BusinessTermCreate, db: Session = Depends(get_db)):
    return _replace_child(db, model_id, BusinessTerm, resource_id, data)


@router.delete("/{model_id}/business-terms/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_business_term(model_id: str, resource_id: str, db: Session = Depends(get_db)):
    return _delete_child(db, model_id, BusinessTerm, resource_id)


@router.post("/{model_id}/publish", response_model=PublishResult)
def publish_model(model_id: str, db: Session = Depends(get_db)):
    model = _get_or_404(db, model_id)
    try:
        version = LocalSemanticEngine().publish(db, model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PublishResult(success=True, message="Semantic model published", status="PUBLISHED", version=version.version)
