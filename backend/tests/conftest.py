import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.core.access import Principal, get_principal
from app.db.session import get_db
from app.main import app
from app.models import AppUser, Workspace
import app.models as _models  # noqa: F401


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with session_factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db_session: Session):
    workspace = db_session.query(Workspace).first()
    if workspace is None:
        workspace = Workspace(name="Test Workspace")
        db_session.add(workspace)
        db_session.flush()
    admin = db_session.query(AppUser).filter_by(email="admin@chatbi.local").first()
    if admin is None:
        admin = AppUser(workspace_id=workspace.id, email="admin@chatbi.local", display_name="Test Admin", role="ADMIN", status="ACTIVE")
        db_session.add(admin)
        db_session.commit()

    def override_db():
        yield db_session

    def override_principal():
        return Principal(admin.id, workspace.id, admin.email, admin.display_name, admin.role)

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_principal] = override_principal
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def raw_client(db_session: Session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides.pop(get_principal, None)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def datasource_payload():
    return {
        "name": "Demo PostgreSQL",
        "type": "postgresql",
        "host": "demo-postgres",
        "port": 5432,
        "database": "chatbi_demo",
        "username": "readonly",
        "password": "safe-test-password",
        "ssl": False,
        "schema": "public",
    }


@pytest.fixture
def datasource_id(client, datasource_payload):
    response = client.post("/api/v1/datasources", json=datasource_payload)
    assert response.status_code == 201
    return response.json()["id"]
