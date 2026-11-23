import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, quantiles, stdev
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.modules.preferences.schemas import CategoryWeights
from app.modules.recommendations.service import execute_recommendation
from app.modules.routing.service import RoutingMatrixContract


CATALOG_FIELDS = (
    "id",
    "name",
    "type",
    "lat",
    "lon",
    "city",
    "origin_block",
    "categories",
    "duration_estimated_min",
    "duration_estimated_max",
    "source_duration",
    "observation_annotation",
)


def _catalog_value(activity: Any, field: str) -> Any:
    value = activity.get(field) if isinstance(activity, dict) else getattr(activity, field, None)
    if field == "categories" and isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = [item.strip() for item in value.split(",") if item.strip()]
    return value


def catalog_hash(catalog: Sequence[Any]) -> str:
    normalized = [
        {field: _catalog_value(activity, field) for field in CATALOG_FIELDS}
        for activity in catalog
    ]
    normalized.sort(key=lambda item: item["id"] or "")
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class EvaluationScenario:
    id: str
    name: str
    trip_days: int
    daily_limit_min: int


@dataclass(frozen=True)
class EvaluationProfile:
    id: str
    weights: CategoryWeights


@dataclass(frozen=True)
class PlannedExecution:
    run_id: str
    scenario_id: str
    profile_id: str
    strategy: str
    seed: Optional[int]
    trip_days: int
    daily_limit_min: int
    reference_point: Dict[str, float]
    profile_weights: Dict[str, int]


SCENARIOS: Tuple[EvaluationScenario, ...] = (
    EvaluationScenario("curto", "Curto", 2, 240),
    EvaluationScenario("medio", "Médio", 4, 360),
    EvaluationScenario("longo", "Longo", 7, 360),
)


def official_profiles() -> Tuple[EvaluationProfile, ...]:
    def weights(**values: int) -> CategoryWeights:
        defaults = {
            "praia": 0,
            "natureza": 0,
            "gastronomia": 0,
            "cultura_historia": 0,
            "lazer": 0,
            "religioso": 0,
            "compras_artesanato": 0,
        }
        defaults.update(values)
        return CategoryWeights(**defaults)

    return (
        EvaluationProfile("litoral", weights(praia=3, natureza=2, gastronomia=1)),
        EvaluationProfile(
            "cultural",
            weights(
                praia=1,
                natureza=1,
                gastronomia=1,
                cultura_historia=3,
                lazer=2,
                religioso=2,
            ),
        ),
        EvaluationProfile(
            "gastronomico",
            weights(
                praia=1,
                natureza=1,
                gastronomia=3,
                cultura_historia=1,
                lazer=2,
                religioso=1,
                compras_artesanato=1,
            ),
        ),
        EvaluationProfile(
            "diversificado",
            weights(
                praia=2,
                natureza=2,
                gastronomia=2,
                cultura_historia=2,
                lazer=2,
                religioso=2,
                compras_artesanato=2,
            ),
        ),
    )


def build_plan(
    base_seed: int,
    reference_point: Dict[str, float],
    scenarios: Sequence[EvaluationScenario] = SCENARIOS,
    profiles: Optional[Sequence[EvaluationProfile]] = None,
    personalized_repetitions: int = 30,
    include_id_arm: bool = False,
) -> List[PlannedExecution]:
    """Monta o plano de execuções do desenho v4.

    Por combinação cenário/perfil: ``personalized_repetitions`` execuções da
    personalizada com desempate aleatório (sementes base_seed+1 ..
    base_seed+personalized_repetitions), opcionalmente UMA execução do braço
    ``personalized_id`` (desempate por id ignora a semente) e 30 execuções da
    baseline aleatória (sementes base_seed+1 .. base_seed+30).
    """
    profiles = tuple(profiles or official_profiles())
    plan: List[PlannedExecution] = []
    for scenario in scenarios:
        for profile in profiles:
            combination = f"{scenario.id}-{profile.id}"
            for repetition in range(1, personalized_repetitions + 1):
                plan.append(
                    PlannedExecution(
                        f"{combination}-personalized-{repetition:02d}",
                        scenario.id,
                        profile.id,
                        "personalized",
                        base_seed + repetition,
                        scenario.trip_days,
                        scenario.daily_limit_min,
                        dict(reference_point),
                        profile.weights.model_dump(),
                    )
                )
            if include_id_arm:
                plan.append(
                    PlannedExecution(
                        f"{combination}-personalized_id",
                        scenario.id,
                        profile.id,
                        "personalized_id",
                        None,
                        scenario.trip_days,
                        scenario.daily_limit_min,
                        dict(reference_point),
                        profile.weights.model_dump(),
                    )
                )
            for repetition in range(1, 31):
                plan.append(
                    PlannedExecution(
                        f"{combination}-baseline-{repetition:02d}",
                        scenario.id,
                        profile.id,
                        "baseline_random",
                        base_seed + repetition,
                        scenario.trip_days,
                        scenario.daily_limit_min,
                        dict(reference_point),
                        profile.weights.model_dump(),
                    )
                )
    return plan


def _serialize_result(result: Any) -> Dict[str, Any]:
    return result.model_dump(mode="json") if hasattr(result, "model_dump") else result


def evaluate_itinerary_metrics(
    catalog: Sequence[Any],
    inserted_activity_ids: Sequence[str],
    category_weights: CategoryWeights,
) -> Dict[str, Any]:
    """Calcula métricas temáticas após a seleção, para qualquer estratégia.

    ``compatibility_media_normalized`` divide ``compatibility_media`` pelo
    escore máximo alcançável do perfil (``S_max = maior peso ativo / soma dos
    pesos ativos``). ``zero_score_inserted_count``/``ratio`` contam atividades
    inseridas com escore 0 (nenhuma categoria ativa em comum).
    """
    active_categories = category_weights.categorias_ativas
    if not active_categories:
        compatibility = None
        coverage = None
        normalized_compatibility = None
        zero_score_inserted_count = 0
        zero_score_inserted_ratio = None
    else:
        by_id = {}
        for activity in catalog:
            activity_id = activity.get("id") if isinstance(activity, dict) else activity.id
            categories = activity.get("categories") if isinstance(activity, dict) else activity.categories
            if isinstance(categories, str):
                try:
                    categories = json.loads(categories)
                except json.JSONDecodeError:
                    categories = [item.strip() for item in categories.split(",") if item.strip()]
            by_id[activity_id] = set(categories or [])

        missing = [activity_id for activity_id in inserted_activity_ids if activity_id not in by_id]
        if missing:
            raise ValueError(f"Atividades inseridas ausentes no catálogo: {', '.join(missing)}")
        denominator = sum(getattr(category_weights, category) for category in active_categories)
        scores = [
            sum(
                getattr(category_weights, category)
                for category in by_id[activity_id].intersection(active_categories)
            ) / denominator
            for activity_id in inserted_activity_ids
        ]
        represented = set().union(
            *(categories.intersection(active_categories) for categories in
              (by_id[activity_id] for activity_id in inserted_activity_ids))
        ) if inserted_activity_ids else set()
        compatibility = mean(scores) if scores else None
        coverage = len(represented) / len(active_categories) if inserted_activity_ids else 0.0
        max_active_weight = max(
            getattr(category_weights, category) for category in active_categories
        )
        max_reachable_score = max_active_weight / denominator
        normalized_compatibility = (
            compatibility / max_reachable_score if compatibility is not None else None
        )
        zero_score_inserted_count = sum(1 for score in scores if score == 0.0)
        zero_score_inserted_ratio = (
            zero_score_inserted_count / len(scores) if scores else None
        )

    return {
        "compatibility_media": compatibility,
        "compatibility_media_normalized": normalized_compatibility,
        "cobertura_interesses": coverage,
        "zero_score_inserted_count": zero_score_inserted_count,
        "zero_score_inserted_ratio": zero_score_inserted_ratio,
        "empty_itinerary": not inserted_activity_ids,
        "active_category_count": len(active_categories),
    }


def _baseline_weights() -> CategoryWeights:
    return CategoryWeights(
        praia=0,
        natureza=0,
        gastronomia=0,
        cultura_historia=0,
        lazer=0,
        religioso=0,
        compras_artesanato=0,
    )


class EvaluationRunner:
    def __init__(
        self,
        catalog: Sequence[Any],
        routing_contract: RoutingMatrixContract,
        *,
        base_seed: int,
        reference_point: Dict[str, float],
        scenarios: Sequence[EvaluationScenario] = SCENARIOS,
        profiles: Optional[Sequence[EvaluationProfile]] = None,
        catalog_hash_value: Optional[str] = None,
        routing_matrix_id: Optional[str] = None,
        routing_matrix_hash: Optional[str] = None,
        code_version: Optional[str] = None,
        code_dirty: Optional[bool] = None,
        code_version_source: Optional[str] = None,
        execution_scope: str = "full",
        selected_scenario: Optional[str] = None,
        selected_profile: Optional[str] = None,
        tie_break: str = "random",
        personalized_repetitions: int = 30,
        include_id_arm: bool = False,
    ):
        self.catalog = list(catalog)
        self.routing_contract = routing_contract
        self.base_seed = base_seed
        self.reference_point = dict(reference_point)
        self.scenarios = tuple(scenarios)
        self.profiles = tuple(profiles or official_profiles())
        self.tie_break = tie_break
        self.personalized_repetitions = personalized_repetitions
        self.include_id_arm = include_id_arm
        self.catalog_hash_value = catalog_hash_value or catalog_hash(self.catalog)
        self.routing_matrix_id = routing_matrix_id
        self.routing_matrix_hash = routing_matrix_hash
        self.code_version = code_version
        self.code_dirty = code_dirty
        self.code_version_source = code_version_source
        self.execution_scope = execution_scope
        self.selected_scenario = selected_scenario
        self.selected_profile = selected_profile

    def plan(self) -> List[PlannedExecution]:
        return build_plan(
            self.base_seed,
            self.reference_point,
            self.scenarios,
            self.profiles,
            personalized_repetitions=self.personalized_repetitions,
            include_id_arm=self.include_id_arm,
        )

    def run(self) -> Dict[str, Any]:
        profiles = {item.id: item for item in self.profiles}
        executions: List[Dict[str, Any]] = []
        for item in self.plan():
            try:
                result = execute_recommendation(
                    self.catalog,
                    self.routing_contract,
                    (
                        profiles[item.profile_id].weights
                        if item.strategy != "baseline_random"
                        else _baseline_weights()
                    ),
                    item.daily_limit_min,
                    item.trip_days,
                    item.seed,
                    tie_break=(
                        "id" if item.strategy == "personalized_id" else self.tie_break
                    ),
                    strategy_name=item.strategy,
                )
                serialized = _serialize_result(result)
            except Exception as exc:
                executions.append(
                    {
                        **asdict(item),
                        "status": "failed",
                        "result": None,
                        "metrics": None,
                        "itinerary_metrics": None,
                        "evaluation_metrics": None,
                        "evaluation_status": "not_run",
                        "evaluation_error": None,
                        "inserted_activity_count": None,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                )
                continue

            execution = {
                **asdict(item),
                "status": "succeeded",
                "result": serialized,
                "metrics": serialized["metrics"],
                "itinerary_metrics": serialized.get("itinerary_metrics"),
                "evaluation_metrics": None,
                "evaluation_status": "pending",
                "evaluation_error": None,
                "inserted_activity_count": len(serialized["activities"]),
                "error": None,
            }
            try:
                execution["evaluation_metrics"] = evaluate_itinerary_metrics(
                    self.catalog,
                    serialized["activities"],
                    profiles[item.profile_id].weights,
                )
                execution["evaluation_status"] = "succeeded"
            except Exception as exc:
                execution["evaluation_status"] = "failed"
                execution["evaluation_error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            executions.append(execution)

        failures = [item for item in executions if item["status"] == "failed"]
        return {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "completed_with_failures" if failures else "completed",
            "base_seed": self.base_seed,
            "reference_point": self.reference_point,
            "catalog_activity_count": len(self.catalog),
            "catalog_hash": self.catalog_hash_value,
            "routing_matrix_id": self.routing_matrix_id,
            "routing_matrix_hash": self.routing_matrix_hash,
            "execution_scope": self.execution_scope,
            "selected_scenario": self.selected_scenario,
            "selected_profile": self.selected_profile,
            "code_version": self.code_version,
            "code_dirty": self.code_dirty,
            "code_version_source": self.code_version_source,
            "tie_break": self.tie_break,
            "personalized_repetitions": self.personalized_repetitions,
            "expected_execution_count": len(self.plan()),
            "planned_execution_count": len(executions),
            "attempted_execution_count": len(executions),
            "completed_execution_count": len(executions) - len(failures),
            "failed_execution_count": len(failures),
            "executions": executions,
            "aggregates": aggregate_results(executions),
        }


SECONDARY_SCALAR_METRICS = (
    "total_distance_m",
    "total_travel_minutes",
    "total_visit_minutes",
    "total_occupied_minutes",
    "total_violations",
)

PRIMARY_EVALUATION_METRICS = (
    "compatibility_media",
    "compatibility_media_normalized",
    "cobertura_interesses",
    "zero_score_inserted_count",
    "zero_score_inserted_ratio",
)

SCALAR_EXECUTION_METRICS = ("inserted_activity_count", *SECONDARY_SCALAR_METRICS)

SUPERIORITY_METRICS = (
    "compatibility_media",
    "compatibility_media_normalized",
    "cobertura_interesses",
    "total_distance_m",
    "total_travel_minutes",
    "inserted_activity_count",
)


def _distribution_stats(values: Sequence[float]) -> Dict[str, Any]:
    """Estatísticas completas: média, mediana, desvio-padrão amostral,
    q1, q3, IQR, mínimo, máximo e contagem.

    Q1/Q3/IQR ficam ``None`` com menos de 2 observações; o desvio-padrão
    amostral fica ``None`` com menos de 2 observações.
    """
    values = list(values)
    if len(values) >= 2:
        quartiles = quantiles(values, n=4, method="inclusive")
        q1, q3 = quartiles[0], quartiles[2]
        iqr: Optional[float] = q3 - q1
        stddev: Optional[float] = stdev(values)
    else:
        q1 = q3 = iqr = stddev = None
    return {
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "stddev": stddev,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "observation_count": len(values),
    }


def _collect_scalar_values(successful: List[Dict[str, Any]]) -> Dict[str, List[float]]:
    """Coleta valores observados das métricas escalares por execução."""
    observed: Dict[str, List[float]] = {name: [] for name in SCALAR_EXECUTION_METRICS}
    for item in successful:
        if item.get("inserted_activity_count") is not None:
            observed["inserted_activity_count"].append(item["inserted_activity_count"])
        itinerary_metrics = item.get("itinerary_metrics") or {}
        for name in SECONDARY_SCALAR_METRICS:
            if itinerary_metrics.get(name) is not None:
                observed[name].append(itinerary_metrics[name])
    return observed


def _empirical_superiority_probability(
    personalized: Sequence[float], baseline: Sequence[float]
) -> Optional[float]:
    """Probabilidade de superioridade P(personalizada > baseline) sobre todas
    as comparações cruzadas, com empate contando 0,5 (A12 de Vargha-Delaney).
    """
    personalized = list(personalized)
    baseline = list(baseline)
    if not personalized or not baseline:
        return None
    wins = 0.0
    for x in personalized:
        for y in baseline:
            if x > y:
                wins += 1.0
            elif x == y:
                wins += 0.5
    return wins / (len(personalized) * len(baseline))


def aggregate_results(executions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for execution in executions:
        key = (
            execution["scenario_id"],
            execution["profile_id"],
            execution["strategy"],
        )
        groups.setdefault(key, []).append(execution)

    aggregates = []
    for (scenario_id, profile_id, strategy), items in groups.items():
        successful = [item for item in items if item["status"] == "succeeded"]
        evaluation_metrics = [
            item["evaluation_metrics"]
            for item in successful
            if item.get("evaluation_metrics") is not None
        ]
        primary_values = {
            name: [
                item[name]
                for item in evaluation_metrics
                if item.get(name) is not None
            ]
            for name in PRIMARY_EVALUATION_METRICS
        }
        scalar_values = _collect_scalar_values(successful)
        all_values = {**primary_values, **scalar_values}

        aggregate: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "profile_id": profile_id,
            "strategy": strategy,
            "planned_count": len(items),
            "successful_count": len(successful),
            "failed_count": len(items) - len(successful),
            "evaluation_failed_count": sum(
                1 for item in items if item.get("evaluation_status") == "failed"
            ),
            "empty_itinerary_count": sum(
                1 for item in evaluation_metrics if item["empty_itinerary"]
            ),
        }
        values_store: Dict[str, List[float]] = {}
        for name, values in all_values.items():
            values_store[name] = list(values)
            aggregate.update(
                {f"{name}_{stat}": value for stat, value in _distribution_stats(values).items()}
            )
        for name in SUPERIORITY_METRICS:
            aggregate[f"_values_{name}"] = values_store.get(name, [])
        aggregates.append(aggregate)

    by_key = {(item["scenario_id"], item["profile_id"], item["strategy"]): item for item in aggregates}
    for aggregate in aggregates:
        if aggregate["strategy"] not in ("personalized", "personalized_id"):
            continue
        baseline = by_key.get((aggregate["scenario_id"], aggregate["profile_id"], "baseline_random"))
        if not baseline:
            continue
        baseline_compatibility_median = baseline["compatibility_media_median"]
        baseline_coverage_median = baseline["cobertura_interesses_median"]
        for name in SUPERIORITY_METRICS:
            aggregate[f"p_superiority_{name}"] = _empirical_superiority_probability(
                aggregate.pop(f"_values_{name}", []),
                baseline.get(f"_values_{name}", []),
            )
        aggregate["baseline_compatibility_media_median"] = baseline_compatibility_median
        aggregate["baseline_cobertura_interesses_median"] = baseline_coverage_median
        aggregate["compatibility_media_difference_from_baseline_median"] = (
            aggregate["compatibility_media_median"] - baseline_compatibility_median
            if aggregate["compatibility_media_median"] is not None
            and baseline_compatibility_median is not None
            else None
        )
        aggregate["cobertura_interesses_difference_from_baseline_median"] = (
            aggregate["cobertura_interesses_median"] - baseline_coverage_median
            if aggregate["cobertura_interesses_median"] is not None
            and baseline_coverage_median is not None
            else None
        )
    for aggregate in aggregates:
        for name in SUPERIORITY_METRICS:
            aggregate.pop(f"_values_{name}", None)
    return aggregates


def export_report(
    report: Dict[str, Any],
    output_dir: str | Path,
    *,
    allow_overwrite: bool = False,
) -> Tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "results.json"
    csv_path = output / "results.csv"
    if not allow_overwrite and (json_path.exists() or csv_path.exists()):
        raise FileExistsError(
            f"Resultados já existem em {output}; use allow_overwrite para substituir"
        )

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = [
        "run_id", "execution_scope", "scenario_id", "profile_id", "strategy", "seed", "status",
        "trip_days", "daily_limit_min", "inserted_activity_count",
        "compatibility_media", "cobertura_interesses", "error_type", "error_message",
        "evaluation_compatibility_media", "evaluation_cobertura_interesses",
        "evaluation_compatibility_media_normalized",
        "evaluation_zero_score_inserted_count",
        "evaluation_zero_score_inserted_ratio",
        "empty_itinerary", "active_category_count", "evaluation_status",
        "evaluation_error_type", "evaluation_error_message",
        "baseline_compatibility_media_median",
        "baseline_cobertura_interesses_median",
        "compatibility_media_difference_from_baseline_median",
        "cobertura_interesses_difference_from_baseline_median",
        *SECONDARY_SCALAR_METRICS,
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        execution_scope = report.get("execution_scope", "full")
        for row in report["executions"]:
            metrics = row["metrics"] or {}
            itinerary_metrics = row.get("itinerary_metrics") or {}
            evaluation_metrics = row.get("evaluation_metrics") or {}
            error = row["error"] or {}
            evaluation_error = row.get("evaluation_error") or {}
            aggregate = next(
                (
                    item
                    for item in report["aggregates"]
                    if item["scenario_id"] == row["scenario_id"]
                    and item["profile_id"] == row["profile_id"]
                    and item["strategy"] == row["strategy"]
                ),
                {},
            )
            writer.writerow(
                {
                    "run_id": row["run_id"],
                    "execution_scope": execution_scope,
                    "scenario_id": row["scenario_id"],
                    "profile_id": row["profile_id"],
                    "strategy": row["strategy"],
                    "seed": row["seed"],
                    "status": row["status"],
                    "trip_days": row["trip_days"],
                    "daily_limit_min": row["daily_limit_min"],
                    "inserted_activity_count": row["inserted_activity_count"],
                    "compatibility_media": metrics.get("compatibility_media"),
                    "cobertura_interesses": metrics.get("cobertura_interesses"),
                    "evaluation_compatibility_media": evaluation_metrics.get("compatibility_media"),
                    "evaluation_cobertura_interesses": evaluation_metrics.get("cobertura_interesses"),
                    "evaluation_compatibility_media_normalized": evaluation_metrics.get(
                        "compatibility_media_normalized"
                    ),
                    "evaluation_zero_score_inserted_count": evaluation_metrics.get(
                        "zero_score_inserted_count"
                    ),
                    "evaluation_zero_score_inserted_ratio": evaluation_metrics.get(
                        "zero_score_inserted_ratio"
                    ),
                    "empty_itinerary": evaluation_metrics.get("empty_itinerary"),
                    "active_category_count": evaluation_metrics.get("active_category_count"),
                    "evaluation_status": row.get("evaluation_status"),
                    "evaluation_error_type": evaluation_error.get("type"),
                    "evaluation_error_message": evaluation_error.get("message"),
                    "baseline_compatibility_media_median": aggregate.get(
                        "baseline_compatibility_media_median"
                    ),
                    "baseline_cobertura_interesses_median": aggregate.get(
                        "baseline_cobertura_interesses_median"
                    ),
                    "compatibility_media_difference_from_baseline_median": aggregate.get(
                        "compatibility_media_difference_from_baseline_median"
                    ),
                    "cobertura_interesses_difference_from_baseline_median": aggregate.get(
                        "cobertura_interesses_difference_from_baseline_median"
                    ),
                    "error_type": error.get("type"),
                    "error_message": error.get("message"),
                    **{name: itinerary_metrics.get(name) for name in SECONDARY_SCALAR_METRICS},
                }
            )
    return json_path, csv_path
