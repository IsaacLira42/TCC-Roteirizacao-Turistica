"""Testes da API de activities, focados em categories."""
import json
import pytest

from app.modules.activities.models import Activity


def test_list_activities_empty(client):
    r = client.get("/api/v1/activities")
    assert r.status_code == 200
    assert r.json() == []


def test_list_activities_with_data(client, sample_activities):
    r = client.get("/api/v1/activities")
    assert r.status_code == 200
    assert len(r.json()) == 3


def test_get_activity_by_id(client, sample_activities):
    r = client.get("/api/v1/activities/atividade_test_001")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == "atividade_test_001"
    assert data["categories"] == ["cultura_historia"]


def test_get_activity_404(client):
    r = client.get("/api/v1/activities/inexistente")
    assert r.status_code == 404


def test_categories_single_item_is_list(client, sample_activities):
    r = client.get("/api/v1/activities/atividade_test_001")
    cats = r.json()["categories"]
    assert isinstance(cats, list)
    assert cats == ["cultura_historia"]


def test_categories_multiple_items(client, sample_activities):
    r = client.get("/api/v1/activities/atividade_test_002")
    cats = r.json()["categories"]
    assert isinstance(cats, list)
    assert set(cats) == {"cultura_historia", "lazer"}


def test_categories_filter_by_category(client, sample_activities):
    r = client.get("/api/v1/activities?category=gastronomia")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 1
    assert data[0]["id"] == "atividade_test_003"


def test_update_preserves_categories_when_not_sent(client, sample_activities):
    r = client.put(
        "/api/v1/activities/atividade_test_001",
        json={"name": "Nome alterado"},
    )
    assert r.status_code == 200
    assert r.json()["categories"] == ["cultura_historia"]


def test_update_sets_categories(client, sample_activities):
    r = client.put(
        "/api/v1/activities/atividade_test_001",
        json={"categories": ["gastronomia", "lazer"]},
    )
    assert r.status_code == 200
    cats = r.json()["categories"]
    assert set(cats) == {"gastronomia", "lazer"}


def test_update_with_empty_categories(client, sample_activities):
    r = client.put(
        "/api/v1/activities/atividade_test_001",
        json={"categories": []},
    )
    assert r.status_code == 200
    assert r.json()["categories"] == []


def test_create_activity_with_multiple_categories(client):
    payload = {
        "name": "Nova",
        "type": "test",
        "lat": -5.8,
        "lon": -35.2,
        "city": "Natal",
        "origin_block": "test",
        "categories": ["cultura_historia", "gastronomia"],
        "duration_estimated_min": 60,
        "duration_estimated_max": 90,
    }
    r = client.post("/api/v1/activities", json=payload)
    assert r.status_code in (200, 201)
    cats = r.json()["categories"]
    assert set(cats) == {"cultura_historia", "gastronomia"}


def test_create_activity_without_categories(client):
    payload = {
        "name": "Sem categoria",
        "type": "test",
        "lat": -5.8,
        "lon": -35.2,
        "duration_estimated_min": 60,
        "duration_estimated_max": 90,
    }
    r = client.post("/api/v1/activities", json=payload)
    assert r.status_code in (200, 201)
    cats = r.json().get("categories")
    # Sem categorias: None ou []
    assert cats is None or cats == []