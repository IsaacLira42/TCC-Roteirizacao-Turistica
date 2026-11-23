"""Consulta das atividades no banco e transformacao em pontos do mapa."""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import DatabaseConfig, load_config

SEM_MUNICIPIO = "(sem município)"


@dataclass(frozen=True)
class ActivityPoint:
    activity_id: str
    name: str
    city: str
    lat: float
    lon: float


def valid_coordinate(lat, lon) -> bool:
    """Coordenada valida: numero finito dentro dos limites WGS84."""
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    if isinstance(lat, bool) or isinstance(lon, bool):
        return False
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    return -90.0 <= float(lat) <= 90.0 and -180.0 <= float(lon) <= 180.0


def normalize_city(city) -> str:
    """Municipio vazio, None ou 'N/A' vira categoria propria, nunca Natal."""
    if city is None:
        return SEM_MUNICIPIO
    city = str(city).strip()
    if city in ("", "N/A", "n/a", "NA"):
        return SEM_MUNICIPIO
    return city


def make_point(activity_id: str, name: str, city, lat, lon) -> ActivityPoint | None:
    """Transforma uma linha do banco em ponto; None se coordenada invalida."""
    if not activity_id or not valid_coordinate(lat, lon):
        return None
    return ActivityPoint(
        activity_id=str(activity_id),
        name=str(name),
        city=normalize_city(city),
        lat=float(lat),
        lon=float(lon),
    )


def create_engine_for(config: DatabaseConfig) -> Engine:
    return create_engine(config.url, echo=False, future=True)


def fetch_activity_points(
    engine: Engine,
    table: str = "activities",
) -> tuple[list[ActivityPoint], int]:
    """Consulta registros com id, nome, municipio e coordenadas.

    Retorna (pontos validos, total de linhas consultadas). A filtragem de
    coordenadas invalidas e feita em Python, pois o banco ja impoe NOT NULL,
    mas a ferramenta continua correta se a restricao mudar.
    """
    query = text(
        f"SELECT id, name, city, lat, lon FROM {table} WHERE lat IS NOT NULL AND lon IS NOT NULL"
    )
    points: list[ActivityPoint] = []
    total = 0
    with engine.connect() as conn:
        for row in conn.execute(query):
            total += 1
            point = make_point(row.id, row.name, row.city, row.lat, row.lon)
            if point is not None:
                points.append(point)
    return points, total


def fetch_points_from_database(
    config: DatabaseConfig | None = None,
) -> tuple[list[ActivityPoint], int]:
    """Atalho usado pelo CLI: carrega configuracao, conecta e consulta."""
    cfg = config or load_config()
    engine = create_engine_for(cfg)
    try:
        return fetch_activity_points(engine)
    finally:
        engine.dispose()


def center_of(points: list[ActivityPoint]) -> tuple[float, float]:
    """Centro geografico simples (media das coordenadas)."""
    return (
        sum(p.lat for p in points) / len(points),
        sum(p.lon for p in points) / len(points),
    )
