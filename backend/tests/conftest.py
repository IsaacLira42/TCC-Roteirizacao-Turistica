"""Fixtures compartilhadas para os testes."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.database import Base
# Importa todos os modelos para registrá-los em Base.metadata
from app.modules.activities.models import Activity  # noqa: F401
from app.main import app
from app.modules.activities.service import get_session


@pytest.fixture
def db_engine():
    """Engine SQLite em memória, isolada por teste."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Sessão de banco em SQLite em memória."""
    TestingSessionLocal = sessionmaker(bind=db_engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client(db_session):
    """TestClient do FastAPI com sessão de teste injetada."""
    def override_get_session():
        return db_session

    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def sample_activities(db_session):
    """Cria algumas atividades de exemplo no banco de teste."""
    atividades = [
        Activity(
            id="atividade_test_001",
            name="Vale das Cascatas",
            type="historic=ruins",
            lat=-5.8430461,
            lon=-35.1820773,
            city="Natal",
            origin_block="pontos",
            categories='["cultura_historia"]',
            duration_estimated_min=60,
            duration_estimated_max=90,
            source_duration="estimada_operacional",
            observation_annotation="Teste",
        ),
        Activity(
            id="atividade_test_002",
            name="❤NATAL",
            type="tourism=attraction",
            lat=-5.7894234,
            lon=-35.1882731,
            city="Natal",
            origin_block="pontos",
            categories='["cultura_historia", "lazer"]',
            duration_estimated_min=15,
            duration_estimated_max=30,
            source_duration="estimada_operacional",
            observation_annotation="Teste",
        ),
        Activity(
            id="atividade_test_003",
            name="Restaurante X",
            type="amenity=restaurant",
            lat=-5.8,
            lon=-35.2,
            city="Natal",
            origin_block="pontos",
            categories='["gastronomia"]',
            duration_estimated_min=45,
            duration_estimated_max=60,
            source_duration="estimada_operacional",
            observation_annotation="Teste",
        ),
    ]
    db_session.add_all(atividades)
    db_session.commit()
    return atividades