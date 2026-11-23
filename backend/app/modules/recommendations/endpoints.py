from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.modules.recommendations.schemas import (
    RecommendationInput,
    RecommendationResult,
)
from app.modules.recommendations.service import (
    execute_recommendation,
    verificar_todos_zerados,
)
from app.modules.activities.service import ActivityService, get_session
from app.modules.routing.service import RoutingService


router = APIRouter()


@router.post(
    "/recommendations",
    response_model=RecommendationResult,
    tags=["recommendations"],
    summary="Gerar recomendações de roteiro turístico",
)
def get_recommendations(
    payload: RecommendationInput,
    session=Depends(get_session),
) -> RecommendationResult:
    """Endpoint POST /api/v1/recommendations.

    Recebe os pesos de categoria, semente, dias de viagem, limite diário e
    ponto de referência, e retorna um roteiro turístico gerado conforme a
    estratégia determinada automaticamente pelos pesos.

    A estratégia é definida da seguinte forma:
    - Se todos os pesos de categoria forem zero: estratégia baseline_random.
    - Se pelo menos um peso for maior que zero: estratégia personalized.

    Args:
        payload: objeto validado com category_weights, seed, trip_days,
            daily_limit_min e reference_point.

    Returns:
        RecommendationResult com o roteiro gerado, atividades selecionadas
        e métricas de compatibilidade e cobertura.
    """
    if verificar_todos_zerados(payload.category_weights) and payload.seed is None:
        raise HTTPException(
            status_code=422,
            detail="seed é obrigatória para a estratégia baseline_random",
        )
    if (
        not verificar_todos_zerados(payload.category_weights)
        and payload.tie_break == "random"
        and payload.seed is None
    ):
        raise HTTPException(
            status_code=422,
            detail="seed é obrigatória para desempate aleatório (tie_break=random)",
        )

    try:
        catalog = ActivityService(session=session).list_activities(limit=500)
        catalog_dicts = [
            {
                "id": activity.id,
                "name": activity.name,
                "type": activity.type,
                "lat": activity.lat,
                "lon": activity.lon,
                "city": activity.city,
                "categories": activity.categories,
                "duration_estimated_min": activity.duration_estimated_min,
                "duration_estimated_max": activity.duration_estimated_max,
            }
            for activity in catalog
        ]
        routing_contract = RoutingService.build_matrix_contract(
            payload.reference_point,
            catalog_dicts,
        )
        return execute_recommendation(
            catalog,
            routing_contract,
            payload.category_weights,
            payload.daily_limit_min,
            payload.trip_days,
            payload.seed,
            tie_break=payload.tie_break,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc