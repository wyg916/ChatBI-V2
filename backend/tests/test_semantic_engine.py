from sqlalchemy import select

from app.models import DataSource, SemanticModel
from app.semantic import LocalSemanticEngine, WrenSemanticAdapter
from app.services.seed import seed_demo_semantic_model
from app.services.semantic import get_semantic_model


def test_demo_seed_and_engine_boundaries(db_session):
    seeded = seed_demo_semantic_model(db_session)
    model = get_semantic_model(db_session, seeded.id)
    assert model is not None
    assert len(model.entities) == 3
    assert len(model.metrics) == 3
    assert len(model.dimensions) == 5
    assert len(model.relations) == 2
    assert len(model.business_terms) == 5
    assert len(list(db_session.scalars(select(DataSource)))) == 2

    local = LocalSemanticEngine()
    assert local.capabilities()["runtime_available"] is True
    assert local.validate(model) == []
    assert len(local.compile(model)["entities"]) == 3

    wren = WrenSemanticAdapter()
    assert wren.capabilities()["runtime_available"] is False
    manifest = wren.compile(model)
    assert manifest["metadata"]["source"] == "chatbi-semantic-snapshot"
    assert len(manifest["models"]) == 3
