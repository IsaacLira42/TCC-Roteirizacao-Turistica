"""Testes do map_viewer com dados sintéticos (sem banco)."""

from __future__ import annotations

from pathlib import Path

import pytest

from map_viewer.build import build_map, city_colors, city_counts, write_map
from map_viewer.data import (
    SEM_MUNICIPIO,
    ActivityPoint,
    fetch_activity_points,
    make_point,
    normalize_city,
    valid_coordinate,
)


def pts(*specs):
    return [
        ActivityPoint(a, n, c, la, lo)
        for a, n, c, la, lo in specs
    ]


# ---- validação de coordenadas ------------------------------------------

def test_valid_coordinate_ranges():
    assert valid_coordinate(-5.87, -35.18)
    assert valid_coordinate(0, 0)
    assert valid_coordinate(90, 180)
    assert valid_coordinate(-90, -180)


def test_invalid_coordinates():
    assert not valid_coordinate(None, None)
    assert not valid_coordinate(float("nan"), -35.0)
    assert not valid_coordinate(float("inf"), -35.0)
    assert not valid_coordinate(91.0, -35.0)
    assert not valid_coordinate(-5.0, -181.0)
    assert not valid_coordinate("2", -35.0)


# ---- município ----------------------------------------------------------

def test_normalize_city_empty_and_na():
    assert normalize_city(None) == SEM_MUNICIPIO
    assert normalize_city("") == SEM_MUNICIPIO
    assert normalize_city("  ") == SEM_MUNICIPIO
    assert normalize_city("N/A") == SEM_MUNICIPIO
    assert normalize_city("Natal") == "Natal"
    assert normalize_city(" Natal ") == "Natal"


def test_na_point_is_not_assigned_to_natal():
    p = make_point("a1", "Praia X", "N/A", -5.8, -35.1)
    assert p.city == SEM_MUNICIPIO
    colors = city_colors([p, make_point("a2", "Y", "Natal", -5.9, -35.2)])
    assert colors[SEM_MUNICIPIO] != colors["Natal"]


# ---- transformação de registros -----------------------------------------

def test_make_point_valid():
    p = make_point("atividade_0011", "Vale", "Natal", -5.84, -35.18)
    assert p is not None
    assert p.activity_id == "atividade_0011"
    assert p.city == "Natal"


def test_make_point_invalid_coordinate_returns_none():
    assert make_point("a1", "X", "Natal", None, None) is None
    assert make_point("a1", "X", "Natal", 999, 0) is None
    assert make_point(None, "X", "Natal", -5, -35) is None


def test_fetch_activity_points_skips_invalid_rows():
    class Row:
        def __init__(self, id, name, city, lat, lon):
            self.id, self.name, self.city = id, name, city
            self.lat, self.lon = lat, lon

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def __iter__(self):
            return iter(self._rows)

    class FakeConn:
        def execute(self, query):
            return FakeResult([
                Row("a1", "Boa", "Natal", -5.8, -35.2),
                Row("a2", "SemLat", "Natal", None, -35.2),
                Row("a3", "Fora", "Parnamirim", 200.0, -35.0),
                Row("a4", "SemCidade", "N/A", -5.9, -35.3),
            ])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class FakeEngine:
        def connect(self):
            return FakeConn()

    points, total = fetch_activity_points(FakeEngine())
    assert total == 4
    assert len(points) == 2
    assert {p.activity_id for p in points} == {"a1", "a4"}
    assert points[1].city == SEM_MUNICIPIO


# ---- mapa ---------------------------------------------------------------

def test_build_map_contains_markers_popups_and_legend(tmp_path: Path):
    points = pts(
        ("a1", "Ponto Um", "Natal", -5.87, -35.18),
        ("a2", "Ponto Dois", "Parnamirim", -5.91, -35.28),
        ("a3", "Ponto Tres", SEM_MUNICIPIO, -5.78, -35.19),
    )
    mapa = build_map(points)
    html = mapa.get_root().render()

    for token in ("Ponto Um", "Ponto Dois", "Ponto Tres",
                  "a1", "a3", "Município", "Latitude", "Longitude"):
        assert token in html
    assert "Pontos por município" in html
    assert "Parnamirim: 1" in html
    assert f"{SEM_MUNICIPIO}: 1" in html
    assert "Natal: 1" in html
    assert "MarkerCluster" not in html  # sem agrupamento: pontos sempre individuais
    assert html.count("circleMarker") >= len(points)  # um CircleMarker por ponto


def test_write_map_creates_directory_and_file(tmp_path: Path):
    points = pts(
        ("a1", "Um", "Natal", -5.87, -35.18),
        ("a2", "Dois", "Extremoz", -5.70, -35.34),
    )
    out = tmp_path / "sub" / "dir" / "mapa.html"
    path = write_map(points, out)
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Um" in content and "Extremoz: 1" in content


def test_write_map_rejects_empty_points(tmp_path: Path):
    with pytest.raises(ValueError):
        write_map([], tmp_path / "mapa.html")


def test_counts_and_colors_consistency():
    points = pts(
        ("a1", "A", "Natal", -5.8, -35.2),
        ("a2", "B", "Natal", -5.9, -35.1),
        ("a3", "C", SEM_MUNICIPIO, -5.7, -35.0),
    )
    counts = city_counts(points)
    assert counts == {"Natal": 2, SEM_MUNICIPIO: 1}
    colors = city_colors(points)
    assert set(colors) == {"Natal", SEM_MUNICIPIO}
    assert len(colors) == len(set(colors.values()))
