from typing import List, Tuple, Dict, Optional, Any

from app.modules.routing.service import RoutingMatrixContract
from app.modules.recommendations.schemas import (
    DayMetricsResult,
    ExcludedActivity,
    IneligibleActivity,
    ItineraryMetricsResult,
    ItineraryResult,
)


class ItinerariesService:
    """Heurística gulosa de inserção, independente de HTTP e OSRM."""

    @staticmethod
    def build_itinerary(
        candidates: List[Dict[str, Any]],
        distance_matrix: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
        duration_matrix: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
        daily_limit_min: int = 0,
        reference_point: Optional[Tuple[float, float]] = None,
        trip_days: int = 1,
        routing_contract: Optional[RoutingMatrixContract] = None,
    ) -> dict:
        """Constrói os dias usando um contrato de matrizes indexado por IDs.

        ``distance_matrix`` e ``duration_matrix`` continuam aceitos para
        compatibilidade, mas o contrato é a interface explícita recomendada.
        """
        if trip_days < 1:
            raise ValueError("trip_days deve ser positivo")
        if daily_limit_min < 0:
            raise ValueError("daily_limit_min não pode ser negativo")

        if routing_contract is None:
            if distance_matrix is None or duration_matrix is None:
                raise ValueError("routing_contract ou ambas as matrizes são obrigatórios")
            labels = {candidate.get("id"): f"a{i}" for i, candidate in enumerate(candidates)}
            routing_contract = RoutingMatrixContract(
                distance_matrix=distance_matrix,
                duration_matrix=duration_matrix,
                activity_id_to_label=labels,
                label_to_activity_id={label: activity_id for activity_id, label in labels.items()},
            )
        elif distance_matrix is not None and distance_matrix is not routing_contract.distance_matrix:
            raise ValueError("distance_matrix diverge do routing_contract")
        elif duration_matrix is not None and duration_matrix is not routing_contract.duration_matrix:
            raise ValueError("duration_matrix diverge do routing_contract")

        valid: List[Dict[str, Any]] = []
        ineligible: List[IneligibleActivity] = []
        seen_ids: set[str] = set()
        for candidate in candidates:
            activity_id = candidate.get("id")
            if not activity_id or activity_id in seen_ids:
                raise ValueError("Candidatos devem possuir IDs estáveis e únicos")
            seen_ids.add(activity_id)
            minimum = candidate.get("duration_estimated_min")
            maximum = candidate.get("duration_estimated_max")
            try:
                valid_duration = (
                    minimum is not None and maximum is not None
                    and float(minimum) > 0 and float(maximum) >= float(minimum)
                )
            except (TypeError, ValueError):
                valid_duration = False
            if not valid_duration:
                ineligible.append(
                    IneligibleActivity(activity_id=activity_id, motive_code="invalid_duration")
                )
            else:
                valid.append(candidate)

        routing_contract.validate_activity_ids([candidate["id"] for candidate in valid])
        days: List[List[str]] = [[] for _ in range(trip_days)]
        excluded: List[ExcludedActivity] = []

        def label(activity_id: str) -> str:
            return routing_contract.label_for(activity_id)

        by_id = {candidate["id"]: candidate for candidate in valid}

        def evaluate(sequence: List[str]) -> Optional[Tuple[float, float, float, float]]:
            """Retorna (distância, minutos, deslocamento, visitas) ou None quando falta perna.

            ``minutos`` é o valor usado pela heurística contra o limite diário;
            deslocamento e visitas são acumulados separadamente para as métricas.
            """
            total_distance = 0.0
            total_minutes = 0.0
            travel_minutes = 0.0
            visit_minutes = 0.0
            previous = routing_contract.reference_label
            for activity_id in sequence:
                current = label(activity_id)
                distance = routing_contract.distance_matrix.get(previous, {}).get(current)
                duration = routing_contract.duration_matrix.get(previous, {}).get(current)
                if distance is None or duration is None:
                    return None
                total_distance += distance
                leg_minutes = float(duration) / 60.0
                total_minutes += leg_minutes
                travel_minutes += leg_minutes
                candidate = by_id[activity_id]
                visit = (
                    float(candidate["duration_estimated_min"])
                    + float(candidate["duration_estimated_max"])
                ) / 2.0
                total_minutes += visit
                visit_minutes += visit
                previous = current
            return total_distance, total_minutes, travel_minutes, visit_minutes

        day_states: List[Tuple[float, float, float, float]] = [
            (0.0, 0.0, 0.0, 0.0) for _ in range(trip_days)
        ]

        for candidate in valid:
            activity_id = candidate["id"]
            options: List[
                Tuple[float, float, int, int, List[str], Tuple[float, float, float, float]]
            ] = []
            has_viable_route = False
            for day_index, day in enumerate(days):
                for position in range(len(day) + 1):
                    proposed = day[:position] + [activity_id] + day[position:]
                    result = evaluate(proposed)
                    if result is None:
                        continue
                    has_viable_route = True
                    distance, minutes = result[0], result[1]
                    if minutes <= daily_limit_min:
                        previous = evaluate(day)
                        if previous is None:
                            continue
                        marginal_distance = distance - previous[0]
                        remaining = daily_limit_min - minutes
                        options.append(
                            (marginal_distance, -remaining, day_index, position, proposed, result)
                        )

            if not options:
                excluded.append(
                    ExcludedActivity(
                        activity_id=activity_id,
                        motive_code="daily_limit_exceeded" if has_viable_route else "no_viable_route",
                    )
                )
                continue

            best = min(options, key=lambda option: option[:4])
            _, _, day_index, _, proposed, state = best
            days[day_index] = proposed
            day_states[day_index] = state

        return {
            "itinerary": ItineraryResult(
                days=[{"day": index + 1, "activities": activities} for index, activities in enumerate(days)]
            ),
            "excluded_activities": excluded,
            "ineligible_activities": ineligible,
            "itinerary_metrics": ItinerariesService.summarize_metrics(
                days, day_states, daily_limit_min
            ),
        }

    @staticmethod
    def summarize_metrics(
        days: List[List[str]],
        day_states: List[Tuple[float, float, float, float]],
        daily_limit_min: int,
    ) -> ItineraryMetricsResult:
        """Monta as métricas secundárias a partir do estado final de cada dia.

        ``day_states`` contém, para cada dia, a tupla (distância, minutos,
        deslocamento, visitas) calculada pela heurística para a sequência
        efetivamente aceita. Dias sem atividades não são ativos: ocupação nula.
        """
        day_metrics: List[DayMetricsResult] = []
        for index, (activities, state) in enumerate(zip(days, day_states)):
            distance, heuristic_minutes, travel, visit = state
            total = travel + visit
            active = bool(activities)
            day_metrics.append(
                DayMetricsResult(
                    day=index + 1,
                    distance_m=float(distance),
                    travel_minutes=travel,
                    visit_minutes=visit,
                    total_minutes=total,
                    occupancy=(total / daily_limit_min) if active and daily_limit_min > 0 else None,
                    limit_violations=1 if active and heuristic_minutes > daily_limit_min else 0,
                )
            )
        return ItineraryMetricsResult(
            total_distance_m=sum(day.distance_m for day in day_metrics),
            total_travel_minutes=sum(day.travel_minutes for day in day_metrics),
            total_visit_minutes=sum(day.visit_minutes for day in day_metrics),
            total_occupied_minutes=sum(day.total_minutes for day in day_metrics),
            total_violations=sum(day.limit_violations for day in day_metrics),
            days=day_metrics,
        )
