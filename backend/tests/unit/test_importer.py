"""Testes unitários do importador A3."""
import json
import pytest

from app.modules.activities.importer import (
    validate_record,
    import_a3_file,
    read_a3_file,
    _get_first,
)
from app.modules.activities.models import Activity

A3_PATH = "artefatos/a3-lotes-02-15-v2.json"


def _a3_count():
    """Contagem esperada lida do próprio artefato (não fixa no código)."""
    return len(read_a3_file(A3_PATH)["registros"])


# ---------- read_a3_file ----------

def test_read_a3_file_returns_dict():
    data = read_a3_file(A3_PATH)
    assert isinstance(data, dict)
    assert "registros" in data
    assert isinstance(data["registros"], list)


def test_read_a3_file_has_expected_records():
    data = read_a3_file(A3_PATH)
    expected = _a3_count()
    assert expected > 0
    assert len(data["registros"]) == expected


# ---------- validate_record ----------

def test_validate_record_valid():
    rec = {
        "id": "atividade_test",
        "nome": "Test",
        "tipo": "test",
        "lat": -5.8,
        "lon": -35.2,
        "cidade": "Natal",
        "categorias": ["cultura_historia"],
        "duracao_estimada_min": 60,
        "duracao_estimada_max": 90,
    }
    ok, msg = validate_record(rec)
    assert ok, msg


def test_validate_record_missing_id():
    rec = {
        "nome": "Test", "tipo": "test", "lat": -5.8, "lon": -35.2,
        "cidade": "Natal", "categorias": ["x"],
        "duracao_estimada_min": 60, "duracao_estimada_max": 90,
    }
    ok, msg = validate_record(rec)
    assert not ok
    assert "id" in msg.lower()


def test_validate_record_missing_required_fields():
    rec = {}
    ok, msg = validate_record(rec)
    assert not ok
    assert "obrigat" in msg.lower()


def test_validate_record_invalid_lat_range():
    rec = {
        "id": "atividade_test", "nome": "Test", "tipo": "test",
        "lat": 100, "lon": -35.2, "cidade": "Natal",
        "categorias": ["x"], "duracao_estimada_min": 60,
        "duracao_estimada_max": 90,
    }
    ok, msg = validate_record(rec)
    assert not ok
    assert "latitude" in msg.lower()


def test_validate_record_invalid_lon_range():
    rec = {
        "id": "atividade_test", "nome": "Test", "tipo": "test",
        "lat": -5.8, "lon": 200, "cidade": "Natal",
        "categorias": ["x"], "duracao_estimada_min": 60,
        "duracao_estimada_max": 90,
    }
    ok, msg = validate_record(rec)
    assert not ok
    assert "longitude" in msg.lower()


def test_validate_record_invalid_duration_negative():
    rec = {
        "id": "atividade_test", "nome": "Test", "tipo": "test",
        "lat": -5.8, "lon": -35.2, "cidade": "Natal",
        "categorias": ["x"], "duracao_estimada_min": -5,
        "duracao_estimada_max": 90,
    }
    ok, msg = validate_record(rec)
    assert not ok
    assert "duracao_estimada_min" in msg


def test_validate_record_invalid_duration_order():
    rec = {
        "id": "atividade_test", "nome": "Test", "tipo": "test",
        "lat": -5.8, "lon": -35.2, "cidade": "Natal",
        "categorias": ["x"], "duracao_estimada_min": 90,
        "duracao_estimada_max": 30,
    }
    ok, msg = validate_record(rec)
    assert not ok
    assert ">" in msg or "maior" in msg.lower()


# ---------- import_a3_file ----------

def test_import_valid_records(db_session):
    stats = import_a3_file(A3_PATH, db_session, dry_run=False)
    db_session.commit()

    expected = _a3_count()
    assert stats["imported"] == expected
    assert stats["skipped"] == 0
    assert stats["duplicated"] == 0
    assert stats["errors"] == 0
    assert db_session.query(Activity).count() == expected


def test_dry_run_no_persistence(db_session):
    stats = import_a3_file(A3_PATH, db_session, dry_run=True)
    # dry-run conta como "seria importado", mas não persiste
    assert stats["imported"] == _a3_count()
    assert stats["skipped"] == 0
    assert db_session.query(Activity).count() == 0


def test_import_idempotent_no_duplicates(db_session):
    expected = _a3_count()
    stats1 = import_a3_file(A3_PATH, db_session, dry_run=False)
    db_session.commit()
    assert stats1["imported"] == expected

    stats2 = import_a3_file(A3_PATH, db_session, dry_run=False)
    assert stats2["imported"] == 0
    assert stats2["duplicated"] == expected
    assert db_session.query(Activity).count() == expected


def test_import_with_existing_ids_skips_duplicates(db_session):
    # Cria 1 registro existente
    existing = Activity(
        id="atividade_0011",
        name="Existente",
        type="test",
        lat=-5.8,
        lon=-35.2,
        duration_estimated_min=10,
        duration_estimated_max=20,
    )
    db_session.add(existing)
    db_session.commit()

    stats = import_a3_file(A3_PATH, db_session, dry_run=False)
    db_session.commit()

    expected = _a3_count()
    # 1 duplicado (atividade_0011) + os demais importados
    assert stats["duplicated"] == 1
    assert stats["imported"] == expected - 1
    assert db_session.query(Activity).count() == expected


def test_import_skips_invalid_records(db_session, tmp_path):
    # Cria arquivo temporário com 1 válido e 1 inválido
    data = {
        "registros": [
            {
                "id": "atividade_ok", "nome": "OK", "tipo": "test",
                "lat": -5.8, "lon": -35.2, "cidade": "Natal",
                "categorias": ["x"], "duracao_estimada_min": 10,
                "duracao_estimada_max": 20,
            },
            {
                "id": "atividade_invalida", "nome": "BAD", "tipo": "test",
                "lat": 200, "lon": -35.2, "cidade": "Natal",
                "categorias": ["x"], "duracao_estimada_min": 10,
                "duracao_estimada_max": 20,
            },
        ]
    }
    filepath = tmp_path / "test_a3.json"
    filepath.write_text(json.dumps(data))

    stats = import_a3_file(str(filepath), db_session, dry_run=False)
    db_session.commit()

    assert stats["imported"] == 1
    assert stats["skipped"] == 1
    assert db_session.query(Activity).count() == 1


# ---------- _get_first ----------

def test_get_first_prefers_first_key():
    rec = {"nome": "A", "name": "B"}
    assert _get_first(rec, "nome", "name") == "A"


def test_get_first_falls_back():
    rec = {"name": "B"}
    assert _get_first(rec, "nome", "name") == "B"


def test_get_first_returns_none_if_all_missing():
    assert _get_first({}, "nome", "name") is None