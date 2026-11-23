"""Visualizador geográfico das atividades do catálogo (mapa Folium).

Ferramenta local e independente: consulta a tabela `activities` do banco
PostgreSQL do projeto e gera um HTML autônomo com a distribuição
geográfica por município. Não faz parte da API de recomendação e não
altera artefatos oficiais.
"""

from .build import build_map, city_colors, city_counts, write_map
from .data import (
    SEM_MUNICIPIO,
    ActivityPoint,
    fetch_activity_points,
    fetch_points_from_database,
    make_point,
    normalize_city,
    valid_coordinate,
)

__all__ = [
    "SEM_MUNICIPIO",
    "ActivityPoint",
    "build_map",
    "city_colors",
    "city_counts",
    "fetch_activity_points",
    "fetch_points_from_database",
    "make_point",
    "normalize_city",
    "valid_coordinate",
    "write_map",
]
