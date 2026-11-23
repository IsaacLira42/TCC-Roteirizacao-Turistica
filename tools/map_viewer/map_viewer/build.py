"""Geracao do mapa Folium com marcadores por municipio, legenda e contagens."""

from __future__ import annotations

import html
from pathlib import Path

import folium

from .data import SEM_MUNICIPIO, ActivityPoint, center_of

PALETTE = [
    "#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd",
    "#8c564b", "#e377c7", "#17becf", "#bcbd22", "#7f7f7f",
    "#aec7e8", "#ffbb78",
]
SEM_MUNICIPIO_COLOR = "#555555"


def city_colors(points: list[ActivityPoint]) -> dict[str, str]:
    """Cor fixa por municipio; a categoria sem municipio tem cor propria."""
    cities = sorted({p.city for p in points} - {SEM_MUNICIPIO})
    colors = {city: PALETTE[i % len(PALETTE)] for i, city in enumerate(cities)}
    if any(p.city == SEM_MUNICIPIO for p in points):
        colors[SEM_MUNICIPIO] = SEM_MUNICIPIO_COLOR
    return colors


def popup_html(point: ActivityPoint, color: str) -> str:
    return (
        f'<div style="font-family: sans-serif; font-size: 13px;">'
        f'<b style="color:{color}">{html.escape(point.name)}</b><br>'
        f'<b>ID:</b> {html.escape(point.activity_id)}<br>'
        f'<b>Município:</b> {html.escape(point.city)}<br>'
        f'<b>Latitude:</b> {point.lat:.6f}<br>'
        f'<b>Longitude:</b> {point.lon:.6f}</div>'
    )


def legend_html(colors: dict[str, str], counts: dict[str, int], total: int) -> str:
    rows = "".join(
        f'<div style="display:flex;align-items:center;margin:2px 0;">'
        f'<span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:2px;background:{colors[city]};margin-right:6px;"></span>'
        f'{html.escape(city)}: {counts[city]}</div>'
        for city in sorted(colors, key=lambda c: -counts.get(c, 0))
    )
    return (
        f'<div style="position:fixed;bottom:20px;left:20px;z-index:9999;'
        f'background:white;padding:10px 14px;border:1px solid #999;'
        f'border-radius:4px;font-family:sans-serif;font-size:13px;'
        f'box-shadow:2px 2px 6px rgba(0,0,0,0.3);">'
        f'<b>Pontos por município (total: {total})</b>{rows}</div>'
    )


def city_counts(points: list[ActivityPoint]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in points:
        counts[p.city] = counts.get(p.city, 0) + 1
    return counts


def build_map(points: list[ActivityPoint]) -> folium.Map:
    """Mapa centrado nos pontos, com micropontos individuais e legenda."""
    center = center_of(points)
    mapa = folium.Map(location=center, zoom_start=12, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri",
        name="Esri Light Gray Canvas",
    ).add_to(mapa)

    colors = city_colors(points)
    for point in points:
        color = colors[point.city]
        folium.CircleMarker(
            location=(point.lat, point.lon),
            radius=3,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            weight=0,
            popup=folium.Popup(popup_html(point, color), max_width=300),
            tooltip=point.name,
        ).add_to(mapa)

    counts = city_counts(points)
    mapa.get_root().html.add_child(
        folium.Element(legend_html(colors, counts, len(points)))
    )
    mapa.fit_bounds(
        [[min(p.lat for p in points), min(p.lon for p in points)],
         [max(p.lat for p in points), max(p.lon for p in points)]]
    )
    return mapa


def write_map(points: list[ActivityPoint], output_path: Path) -> Path:
    """Gera o HTML em disco; cria o diretorio de saida se nao existir."""
    if not points:
        raise ValueError("Nenhum ponto válido para gerar o mapa.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    build_map(points).save(str(output_path))
    return output_path
