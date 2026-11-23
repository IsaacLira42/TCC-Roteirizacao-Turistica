import json
import random
from typing import Any, Dict, List, Optional, Sequence

from app.modules.itineraries.service import ItinerariesService
from app.modules.preferences.schemas import CategoryWeights
from app.modules.recommendations.schemas import (
    DayResult,
    ExcludedActivity,
    IneligibleActivity,
    ItineraryResult,
    MetricsResult,
    RecommendationResult,
)
from app.modules.routing.service import RoutingMatrixContract


def _activity_dict(activity: Any) -> Dict[str, Any]:
    """Converte uma entidade Activity ou dict para o contrato do domínio."""
    if isinstance(activity, dict):
        data = dict(activity)
    else:
        data = {
            "id": activity.id,
            "name": activity.name,
            "type": activity.type,
            "lat": activity.lat,
            "lon": activity.lon,
            "city": activity.city,
            "origin_block": activity.origin_block,
            "categories": activity.categories,
            "duration_estimated_min": activity.duration_estimated_min,
            "duration_estimated_max": activity.duration_estimated_max,
            "source_duration": activity.source_duration,
            "observation_annotation": activity.observation_annotation,
        }
    categories = data.get("categories")
    if isinstance(categories, str):
        try:
            parsed = json.loads(categories)
            data["categories"] = parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            data["categories"] = [item.strip() for item in categories.split(",") if item.strip()]
    elif categories is None:
        data["categories"] = []
    return data


def calcular_compatibilidade(
    category_weights: CategoryWeights, activity: Dict[str, Any]
) -> Optional[float]:
    active_categories = category_weights.categorias_ativas
    if not active_categories:
        return None
    denominator = sum(getattr(category_weights, category) for category in active_categories)
    if denominator == 0:
        return None
    categories = set(activity.get("categories") or [])
    numerator = sum(
        getattr(category_weights, category)
        for category in categories.intersection(active_categories)
    )
    return numerator / denominator


def verificar_todos_zerados(category_weights: CategoryWeights) -> bool:
    return category_weights.todos_zerados


def _empty_itinerary(trip_days: int) -> dict:
    return {
        "itinerary": ItineraryResult(
            days=[DayResult(day=day, activities=[]) for day in range(1, trip_days + 1)]
        ),
        "excluded_activities": [],
        "ineligible_activities": [],
    }


def _run_strategy(
    candidates: Sequence[Dict[str, Any]],
    routing_contract: RoutingMatrixContract,
    daily_limit_min: int,
    trip_days: int,
    strategy: str,
    seed: Optional[int],
    category_weights: Optional[CategoryWeights] = None,
) -> RecommendationResult:
    itinerary_dict = ItinerariesService.build_itinerary(
        list(candidates),
        daily_limit_min=daily_limit_min,
        trip_days=trip_days,
        routing_contract=routing_contract,
    )
    itinerary = itinerary_dict["itinerary"]
    inserted_ids = [
        activity_id
        for day in itinerary.days
        for activity_id in day.activities
    ]
    by_id = {candidate["id"]: candidate for candidate in candidates}

    metrics = MetricsResult(compatibility_media=None, cobertura_interesses=None)
    if strategy == "personalized" and inserted_ids:
        scores = [
            by_id[activity_id]["compatibility"]
            for activity_id in inserted_ids
        ]
        active = category_weights.categorias_ativas if category_weights else []
        represented = set()
        for activity_id in inserted_ids:
            represented.update(set(by_id[activity_id].get("categories") or []).intersection(active))
        metrics = MetricsResult(
            compatibility_media=sum(scores) / len(scores),
            cobertura_interesses=(len(represented) / len(active)) if active else None,
        )
    elif strategy == "personalized" and category_weights and category_weights.categorias_ativas:
        metrics = MetricsResult(compatibility_media=None, cobertura_interesses=0.0)

    return RecommendationResult(
        strategy=strategy,
        seed=seed,
        itinerary=itinerary,
        activities=inserted_ids,
        metrics=metrics,
        excluded_activities=itinerary_dict["excluded_activities"],
        ineligible_activities=itinerary_dict["ineligible_activities"],
        itinerary_metrics=itinerary_dict.get("itinerary_metrics"),
        notes=(
            "Seleção baseada em compatibilidade decrescente com preferências explícitas."
            if strategy == "personalized"
            else "Baseline aleatória executada com semente reproduzível."
        ),
    )


def _ordered_personalized(
    normalized: List[Dict[str, Any]],
    tie_break: str,
    seed: Optional[int],
) -> List[Dict[str, Any]]:
    """Ordena candidatos por compatibilidade decrescente.

    Desempate: ``id`` → id crescente (determinístico); ``random`` →
    embaralhamento com semente dentro de cada grupo de mesmo escore.
    """
    ordered = sorted(
        normalized,
        key=lambda activity: (
            -activity["compatibility"],
            activity["id"],
        ),
    )
    if tie_break != "random":
        return ordered
    if seed is None:
        raise ValueError("seed é obrigatória para desempate aleatório (tie_break=random)")
    rng = random.Random(seed)
    result: List[Dict[str, Any]] = []
    index = 0
    while index < len(ordered):
        group_end = index
        while (
            group_end + 1 < len(ordered)
            and ordered[group_end + 1]["compatibility"] == ordered[index]["compatibility"]
        ):
            group_end += 1
        group = ordered[index : group_end + 1]
        rng.shuffle(group)
        result.extend(group)
        index = group_end + 1
    return result


def execute_recommendation(
    catalog: Sequence[Any],
    routing_contract: RoutingMatrixContract,
    category_weights: CategoryWeights,
    daily_limit_min: int,
    trip_days: int,
    seed: Optional[int],
    tie_break: str = "id",
    strategy_name: Optional[str] = None,
) -> RecommendationResult:
    """Orquestra seleção, contrato de routing e construção do itinerário.

    ``tie_break`` controla o desempate entre atividades de mesmo escore na
    estratégia personalizada: ``"id"`` (padrão, determinístico) ou ``"random"``
    (embaralhamento com semente). ``strategy_name`` permite rotular o braço
    da execução (ex.: ``"personalized_id"`` no desenho v4).
    """
    normalized = [_activity_dict(activity) for activity in catalog]
    personalized = not verificar_todos_zerados(category_weights)

    if personalized:
        for activity in normalized:
            activity["compatibility"] = calcular_compatibilidade(category_weights, activity) or 0.0
        ordered = _ordered_personalized(normalized, tie_break, seed)
        return _run_strategy(
            ordered,
            routing_contract,
            daily_limit_min,
            trip_days,
            strategy_name or "personalized",
            seed if tie_break == "random" else None,
            category_weights,
        )

    if seed is None:
        raise ValueError("seed é obrigatória para a estratégia baseline_random")
    ordered = list(normalized)
    random.Random(seed).shuffle(ordered)
    return _run_strategy(
        ordered,
        routing_contract,
        daily_limit_min,
        trip_days,
        "baseline_random",
        seed,
    )


def select_personalized(
    category_weights: CategoryWeights,
    catalog: List[Dict[str, Any]],
    routing_contract: RoutingMatrixContract,
    daily_limit_min: int,
    trip_days: int,
) -> RecommendationResult:
    return execute_recommendation(
        catalog, routing_contract, category_weights, daily_limit_min, trip_days, None
    )


def select_baseline(
    catalog: List[Dict[str, Any]],
    routing_contract: RoutingMatrixContract,
    daily_limit_min: int,
    trip_days: int,
    seed: int,
) -> RecommendationResult:
    return execute_recommendation(
        catalog,
        routing_contract,
        CategoryWeights(
            praia=0,
            natureza=0,
            gastronomia=0,
            cultura_historia=0,
            lazer=0,
            religioso=0,
            compras_artesanato=0,
        ),
        daily_limit_min,
        trip_days,
        seed,
    )
