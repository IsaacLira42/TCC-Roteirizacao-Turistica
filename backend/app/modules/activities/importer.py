import json
import os
from typing import Dict, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.modules.activities.models import Activity


def read_a3_file(filepath: str) -> dict:
    """Lê o arquivo A3 e retorna o dicionário de dados."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_first(record: dict, *keys: str):
    """Retorna o primeiro valor não-nulo entre as chaves dadas."""
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def validate_record(record: dict) -> Tuple[bool, str | None]:
    """Valida um registro antes da persistência.

    Returns (is_valid, error_message).
    """
    # Mapear campos obrigatórios (português do A3 → canônico)
    required = {
        "id": _get_first(record, "id", "id_atividade"),
        "name": _get_first(record, "nome", "name"),
        "type": _get_first(record, "tipo", "type"),
        "lat": _get_first(record, "lat", "latitude"),
        "lon": _get_first(record, "lon", "longitude"),
        "city": _get_first(record, "cidade", "city"),
        "categorias": _get_first(record, "categorias"),
        "duracao_estimada_min": _get_first(
            record, "duracao_estimada_min", "duracao_minima"
        ),
        "duracao_estimada_max": _get_first(
            record, "duracao_estimada_max", "duracao_maxima"
        ),
    }

    missing = [name for name, value in required.items() if value is None]
    if missing:
        return False, f"Campo(s) obrigatório(s) ausente(s): {', '.join(missing)}"

    # Validar lat/lon ranges (sem fallback entre eles — são eixos diferentes)
    try:
        lat = float(required["lat"])
        lon = float(required["lon"])
    except (TypeError, ValueError):
        return False, f"Latitude/longitude não numérica: lat={required['lat']}, lon={required['lon']}"

    if not (-90 <= lat <= 90):
        return False, f"Latitude inválida: {lat} (deve estar entre -90 e 90)"
    if not (-180 <= lon <= 180):
        return False, f"Longitude inválida: {lon} (deve estar entre -180 e 180)"

    # Validar durações
    try:
        dur_min = float(required["duracao_estimada_min"])
        dur_max = float(required["duracao_estimada_max"])
    except (TypeError, ValueError):
        return False, (
            f"Duração não numérica: "
            f"min={required['duracao_estimada_min']}, max={required['duracao_estimada_max']}"
        )

    if dur_min <= 0:
        return False, f"duracao_estimada_min deve ser > 0: {dur_min}"
    if dur_min > dur_max:
        return False, f"duracao_estimada_min ({dur_min}) > duracao_estimada_max ({dur_max})"

    return True, None


def record_exists(session: Session, activity_id: str) -> bool:
    """Verifica se um registro com este ID já existe."""
    stmt = select(Activity).where(Activity.id == activity_id)
    result = session.execute(stmt)
    return result.scalar_one_or_none() is not None


def import_a3_file(
    filepath: str,
    session: Session,
    dry_run: bool = True,
) -> Dict[str, int]:
    """Importa registros de um arquivo A3 para o banco de dados.

    Returns dict with counts: imported, skipped, duplicated, errors.
    """
    data = read_a3_file(filepath)
    registros = data.get("registros", [])

    stats = {
        "imported": 0,
        "skipped": 0,      # validation errors
        "duplicated": 0,   # already exists
        "errors": 0,       # other errors
    }

    for record in registros:
        is_valid, error_msg = validate_record(record)
        if not is_valid:
            stats["skipped"] += 1
            continue

        activity_id = _get_first(record, "id", "id_atividade")

        # Em dry-run, apenas valida e conta como "seria importado"
        if dry_run or session is None:
            stats["imported"] += 1
            continue

        if record_exists(session, activity_id):
            stats["duplicated"] += 1
            continue

        try:
            db_activity = Activity(
                id=activity_id,
                name=_get_first(record, "nome", "name"),
                type=_get_first(record, "tipo", "type"),
                lat=float(_get_first(record, "lat", "latitude")),
                lon=float(_get_first(record, "lon", "longitude")),
                city=_get_first(record, "cidade", "city") or None,
                origin_block=_get_first(record, "origem_bloco"),
                categories=(
                    json.dumps(_get_first(record, "categorias"))
                    if _get_first(record, "categorias")
                    else None
                ),
                duration_estimated_min=int(
                    _get_first(record, "duracao_estimada_min", "duracao_minima")
                ),
                duration_estimated_max=int(
                    _get_first(record, "duracao_estimada_max", "duracao_maxima")
                ),
                source_duration=_get_first(record, "fonte_duracao"),
                observation_annotation=_get_first(record, "observacao_anotacao"),
            )
            session.add(db_activity)
            stats["imported"] += 1
        except Exception:
            stats["errors"] += 1

    return stats


def import_a3_default(dry_run: bool = True) -> Dict[str, int]:
    """Importa o arquivo A3 padrão.

    Procura primeiro no caminho do container (/app/artefatos/...) e
    depois no caminho relativo ao projeto, para funcionar tanto dentro
    do Docker quanto rodando direto no host.

    Args:
        dry_run: Se True, apenas valida sem persistir.

    Returns:
        Dict with counts of imported, skipped, duplicated, errors.
    """
    candidates = [
        "/app/artefatos/a3-lotes-02-15-v2.json",
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "artefatos",
            "a3-lotes-02-15-v2.json",
        ),
    ]

    a3_path = next((p for p in candidates if os.path.exists(p)), None)
    if a3_path is None:
        raise FileNotFoundError(
            "Arquivo A3 não encontrado. Tentou:\n  " + "\n  ".join(candidates)
        )

    session = SessionLocal()
    try:
        stats = import_a3_file(a3_path, session, dry_run=dry_run)
        if not dry_run:
            session.commit()
        return stats
    finally:
        session.close()