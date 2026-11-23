import random

import pytest

from app.modules.activities.models import Activity
from app.modules.preferences.schemas import CategoryWeights
from app.modules.recommendations.service import execute_recommendation
from app.modules.recommendations.schemas import DayResult, ItineraryResult
from app.modules.routing.service import LatLon, RoutingMatrixContract, RoutingService


def make_contract(activity_ids):
    labels = {activity_id: f"a{index}" for index, activity_id in enumerate(activity_ids)}
    all_labels = ["ref", *labels.values()]
    distance = {
        source: {target: (0.0 if source == target else 100.0)
                 for target in all_labels}
        for source in all_labels
    }
    duration = {
        source: {target: (0.0 if source == target else 60.0)
                 for target in all_labels}
        for source in all_labels
    }
    return RoutingMatrixContract(
        distance_matrix=distance,
        duration_matrix=duration,
        activity_id_to_label=labels,
        label_to_activity_id={label: activity_id for activity_id, label in labels.items()},
    )


def make_catalog():
    return [
        {
            "id": "a",
            "name": "A",
            "lat": -5.8,
            "lon": -35.2,
            "categories": ["praia"],
            "duration_estimated_min": 30,
            "duration_estimated_max": 30,
        },
        {
            "id": "b",
            "name": "B",
            "lat": -5.81,
            "lon": -35.21,
            "categories": ["natureza"],
            "duration_estimated_min": 30,
            "duration_estimated_max": 30,
        },
        {
            "id": "c",
            "name": "C",
            "lat": -5.82,
            "lon": -35.22,
            "categories": ["praia"],
            "duration_estimated_min": 30,
            "duration_estimated_max": 30,
        },
    ]


def test_personalized_uses_catalog_ordered_by_compatibility():
    result = execute_recommendation(
        make_catalog(),
        make_contract(["a", "b", "c"]),
        CategoryWeights(
            praia=3, natureza=0, gastronomia=0, cultura_historia=0,
            lazer=0, religioso=0, compras_artesanato=0,
        ),
        daily_limit_min=240,
        trip_days=2,
        seed=999,
    )

    assert result.strategy == "personalized"
    assert result.seed is None
    assert set(result.activities) == {"a", "b", "c"}
    assert result.metrics.compatibility_media == 2 / 3


def test_both_strategies_pass_same_constraints_and_preserve_candidate_order(monkeypatch):
    observed = []

    def capture(candidates, *, daily_limit_min, trip_days, routing_contract):
        observed.append(
            ([candidate["id"] for candidate in candidates], daily_limit_min, trip_days, routing_contract)
        )
        return {
            "itinerary": ItineraryResult(
                days=[DayResult(day=1, activities=[]), DayResult(day=2, activities=[])]
            ),
            "excluded_activities": [],
            "ineligible_activities": [],
        }

    monkeypatch.setattr(
        "app.modules.recommendations.service.ItinerariesService.build_itinerary",
        capture,
    )
    catalog = make_catalog()
    contract = make_contract(["a", "b", "c"])
    personalized = execute_recommendation(
        catalog, contract,
        CategoryWeights(
            praia=3, natureza=0, gastronomia=0, cultura_historia=0,
            lazer=0, religioso=0, compras_artesanato=0,
        ),
        daily_limit_min=275, trip_days=2, seed=None,
    )
    baseline = execute_recommendation(
        catalog, contract,
        CategoryWeights(
            praia=0, natureza=0, gastronomia=0, cultura_historia=0,
            lazer=0, religioso=0, compras_artesanato=0,
        ),
        daily_limit_min=275, trip_days=2, seed=17,
    )

    assert observed[0][:3] == (["a", "c", "b"], 275, 2)
    expected_baseline = list("abc")
    random.Random(17).shuffle(expected_baseline)
    assert observed[1][:3] == (expected_baseline, 275, 2)
    assert observed[0][3] is contract
    assert observed[1][3] is contract
    assert personalized.seed is None
    assert baseline.seed == 17


def test_zero_weights_use_reproducible_local_baseline():
    weights = CategoryWeights(
        praia=0, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    first = execute_recommendation(
        make_catalog(), make_contract(["a", "b", "c"]), weights,
        daily_limit_min=60, trip_days=2, seed=17,
    )
    second = execute_recommendation(
        make_catalog(), make_contract(["a", "b", "c"]), weights,
        daily_limit_min=60, trip_days=2, seed=17,
    )

    assert first.strategy == "baseline_random"
    assert first.seed == 17
    assert first.activities == second.activities
    assert first.metrics.compatibility_media is None
    assert first.metrics.cobertura_interesses is None


def test_baseline_does_not_change_global_random_state():
    weights = CategoryWeights(
        praia=0, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    random.seed(1234)
    expected = random.random()
    random.seed(1234)
    execute_recommendation(
        make_catalog(), make_contract(["a", "b", "c"]), weights,
        daily_limit_min=240, trip_days=2, seed=17,
    )
    assert random.random() == expected


def test_personalized_seed_is_ignored_and_empty_metrics_are_exact():
    weights = CategoryWeights(
        praia=3, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    result = execute_recommendation(
        [], make_contract([]), weights, daily_limit_min=240, trip_days=2, seed=91
    )
    assert result.strategy == "personalized"
    assert result.seed is None
    assert result.metrics.compatibility_media is None
    assert result.metrics.cobertura_interesses == 0.0
    assert [day.activities for day in result.itinerary.days] == [[], []]


@pytest.mark.parametrize(
    ("weights", "seed", "strategy"),
    [
        (
            CategoryWeights(
                praia=3, natureza=0, gastronomia=0, cultura_historia=0,
                lazer=0, religioso=0, compras_artesanato=0,
            ),
            None,
            "personalized",
        ),
        (
            CategoryWeights(
                praia=0, natureza=0, gastronomia=0, cultura_historia=0,
                lazer=0, religioso=0, compras_artesanato=0,
            ),
            7,
            "baseline_random",
        ),
    ],
)
def test_empty_catalog_endpoint_uses_common_pipeline(client, monkeypatch, weights, seed, strategy):
    monkeypatch.setattr(
        "app.modules.recommendations.endpoints.ActivityService.list_activities",
        lambda self, limit=500: [],
    )
    payload = {
        "category_weights": weights.model_dump(),
        "trip_days": 2,
        "daily_limit_min": 240,
        "reference_point": {"lat": -5.8, "lon": -35.2},
    }
    if seed is not None:
        payload["seed"] = seed
    response = client.post("/api/v1/recommendations", json=payload)
    body = response.json()
    assert response.status_code == 200
    assert body["strategy"] == strategy
    assert body["itinerary"]["days"] == [
        {"day": 1, "activities": []},
        {"day": 2, "activities": []},
    ]


def test_empty_catalog_baseline_uses_common_itinerary_pipeline():
    weights = CategoryWeights(
        praia=0, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    result = execute_recommendation(
        [], make_contract([]), weights, daily_limit_min=240, trip_days=2, seed=7
    )
    assert result.strategy == "baseline_random"
    assert result.seed == 7
    assert [day.activities for day in result.itinerary.days] == [[], []]
    assert result.metrics.compatibility_media is None
    assert result.metrics.cobertura_interesses is None


def test_missing_baseline_seed_is_rejected_by_endpoint(client):
    response = client.post(
        "/api/v1/recommendations",
        json={
            "category_weights": {category: 0 for category in (
                "praia", "natureza", "gastronomia", "cultura_historia",
                "lazer", "religioso", "compras_artesanato",
            )},
            "trip_days": 2,
            "daily_limit_min": 240,
            "reference_point": {"lat": -5.8, "lon": -35.2},
        },
    )
    assert response.status_code == 422


def test_personalized_random_tiebreak_without_seed_is_rejected_by_endpoint(client):
    response = client.post(
        "/api/v1/recommendations",
        json={
            "category_weights": {
                "praia": 3, "natureza": 0, "gastronomia": 0,
                "cultura_historia": 0, "lazer": 0,
                "religioso": 0, "compras_artesanato": 0,
            },
            "tie_break": "random",
            "trip_days": 2,
            "daily_limit_min": 240,
            "reference_point": {"lat": -5.8, "lon": -35.2},
        },
    )
    assert response.status_code == 422
    assert "tie_break=random" in response.json()["detail"]


def test_personalized_random_tiebreak_with_seed_is_accepted(client, monkeypatch):
    contract = make_contract(["a", "b", "c"])
    monkeypatch.setattr(
        RoutingService,
        "build_matrix_contract",
        staticmethod(lambda reference, activities: contract),
    )
    monkeypatch.setattr(
        "app.modules.recommendations.endpoints.ActivityService.list_activities",
        lambda self, limit=500: [Activity(**item) for item in make_catalog()],
    )
    response = client.post(
        "/api/v1/recommendations",
        json={
            "category_weights": {
                "praia": 1, "natureza": 0, "gastronomia": 0,
                "cultura_historia": 0, "lazer": 0,
                "religioso": 0, "compras_artesanato": 0,
            },
            "tie_break": "random",
            "seed": 42,
            "trip_days": 2,
            "daily_limit_min": 240,
            "reference_point": {"lat": -5.8, "lon": -35.2},
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "personalized"
    assert body["seed"] == 42


def test_routing_failure_is_returned_as_infrastructure_error(client, monkeypatch):
    def fail(reference, activities):
        raise RuntimeError("OSRM indisponível")

    monkeypatch.setattr(RoutingService, "build_matrix_contract", staticmethod(fail))
    response = client.post(
        "/api/v1/recommendations",
        json={
            "category_weights": {
                "praia": 3, "natureza": 0, "gastronomia": 0,
                "cultura_historia": 0, "lazer": 0,
                "religioso": 0, "compras_artesanato": 0,
            },
            "trip_days": 2,
            "daily_limit_min": 240,
            "reference_point": {"lat": -5.8, "lon": -35.2},
        },
    )
    assert response.status_code == 503
    assert "OSRM indisponível" in response.json()["detail"]


def test_ineligible_and_excluded_activities_are_separated():
    catalog = make_catalog()
    catalog[0]["duration_estimated_min"] = 0
    catalog[1]["duration_estimated_min"] = 200
    catalog[1]["duration_estimated_max"] = 200
    weights = CategoryWeights(
        praia=3, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    result = execute_recommendation(
        catalog, make_contract(["a", "b", "c"]), weights,
        daily_limit_min=20, trip_days=2, seed=None,
    )
    assert [item.activity_id for item in result.ineligible_activities] == ["a"]
    assert {item.activity_id for item in result.excluded_activities} == {"b", "c"}
    assert not (
        {item.activity_id for item in result.ineligible_activities}
        & {item.activity_id for item in result.excluded_activities}
    )


def test_real_routing_contract_and_itinerary_work_together(monkeypatch):
    activities = make_catalog()[:2]
    responses = iter(
        [
            {"distances": [[10, 20]]},
            {"durations": [[60, 120]]},
            {"distances": [[11], [21]]},
            {"durations": [[66], [126]]},
        ]
    )
    monkeypatch.setattr(
        RoutingService, "load_v2_activity_ids",
        staticmethod(lambda filepath=None: ["a", "b"]),
    )
    monkeypatch.setattr(
        RoutingService, "load_v2_distance_matrix",
        staticmethod(lambda filepath: {"a0": {"a0": 0, "a1": 12}, "a1": {"a0": 13, "a1": 0}}),
    )
    monkeypatch.setattr(
        RoutingService, "load_v2_duration_matrix",
        staticmethod(lambda filepath: {"a0": {"a0": 0, "a1": 72}, "a1": {"a0": 78, "a1": 0}}),
    )
    class Response:
        def raise_for_status(self): pass
        def json(self): return next(responses)
    monkeypatch.setattr("app.modules.routing.service.httpx.get", lambda *args, **kwargs: Response())

    contract = RoutingService.build_matrix_contract(LatLon(lat=-5.8, lon=-35.2), activities)
    result = execute_recommendation(
        activities, contract,
        CategoryWeights(
            praia=3, natureza=0, gastronomia=0, cultura_historia=0,
            lazer=0, religioso=0, compras_artesanato=0,
        ),
        daily_limit_min=240, trip_days=2, seed=None,
    )
    assert contract.label_for("a") == "a0"
    assert contract.label_for("b") == "a1"
    assert set(result.activities) == {"a", "b"}


def test_personalized_equal_scores_use_stable_id_order():
    activities = [
        {**make_catalog()[1], "id": "b"},
        {**make_catalog()[0], "id": "a"},
    ]
    result = execute_recommendation(
        activities,
        make_contract(["a", "b"]),
        CategoryWeights(
            praia=1, natureza=1, gastronomia=0, cultura_historia=0,
            lazer=0, religioso=0, compras_artesanato=0,
        ),
        daily_limit_min=240,
        trip_days=2,
        seed=None,
    )
    assert result.activities == ["a", "b"]


def _tied_catalog(n):
    """Catálogo com n atividades de mesmo escore (mesma categoria e pesos)."""
    return [
        {
            "id": f"atv{i}",
            "name": f"A{i}",
            "lat": -5.8 - i * 0.01,
            "lon": -35.2 - i * 0.01,
            "categories": ["praia"],
            "duration_estimated_min": 30,
            "duration_estimated_max": 30,
        }
        for i in range(n)
    ]


def test_personalized_random_tiebreak_same_seed_same_order():
    catalog = _tied_catalog(6)
    contract = make_contract([item["id"] for item in catalog])
    weights = CategoryWeights(
        praia=1, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    first = execute_recommendation(
        catalog, contract, weights,
        daily_limit_min=240, trip_days=2, seed=42, tie_break="random",
    )
    second = execute_recommendation(
        catalog, contract, weights,
        daily_limit_min=240, trip_days=2, seed=42, tie_break="random",
    )
    assert first.strategy == "personalized"
    assert first.seed == 42
    assert first.activities == second.activities


def test_personalized_random_tiebreak_different_seeds_different_order():
    catalog = _tied_catalog(6)
    contract = make_contract([item["id"] for item in catalog])
    weights = CategoryWeights(
        praia=1, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    orders = {
        tuple(
            execute_recommendation(
                catalog, contract, weights,
                daily_limit_min=240, trip_days=2, seed=seed, tie_break="random",
            ).activities
        )
        for seed in (1, 2, 3, 4, 5, 6, 7)
    }
    assert len(orders) > 1


def test_personalized_id_arm_is_deterministic_and_ignores_seed():
    catalog = _tied_catalog(6)
    contract = make_contract([item["id"] for item in catalog])
    weights = CategoryWeights(
        praia=1, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    first = execute_recommendation(
        catalog, contract, weights,
        daily_limit_min=240, trip_days=2, seed=101,
        tie_break="id", strategy_name="personalized_id",
    )
    second = execute_recommendation(
        catalog, contract, weights,
        daily_limit_min=240, trip_days=2, seed=999,
        tie_break="id", strategy_name="personalized_id",
    )
    assert first.strategy == "personalized_id"
    assert first.seed is None
    assert first.activities == second.activities
    # Sem seed o resultado é o mesmo: seed é ignorada no desempate por id
    third = execute_recommendation(
        catalog, contract, weights,
        daily_limit_min=240, trip_days=2, seed=None,
        tie_break="id", strategy_name="personalized_id",
    )
    assert first.activities == third.activities


def test_personalized_random_tiebreak_requires_seed():
    catalog = _tied_catalog(4)
    weights = CategoryWeights(
        praia=1, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    with pytest.raises(ValueError, match="seed é obrigatória"):
        execute_recommendation(
            catalog, make_contract([item["id"] for item in catalog]), weights,
            daily_limit_min=240, trip_days=2, seed=None, tie_break="random",
        )


def test_catalog_is_loaded_by_endpoint_and_routing_failures_are_explicit(
    client, sample_activities, monkeypatch
):
    ids = [activity.id for activity in sample_activities]
    contract = make_contract(ids)
    monkeypatch.setattr(
        RoutingService,
        "build_matrix_contract",
        staticmethod(lambda reference, activities: contract),
    )

    response = client.post(
        "/api/v1/recommendations",
        json={
            "category_weights": {
                "praia": 0, "natureza": 0, "gastronomia": 0,
                "cultura_historia": 3, "lazer": 0,
                "religioso": 0, "compras_artesanato": 0,
            },
            "trip_days": 2,
            "daily_limit_min": 240,
            "reference_point": {"lat": -5.8, "lon": -35.2},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["strategy"] == "personalized"
    assert body["seed"] is None
    assert set(body["activities"]) == set(ids)


def test_recommendation_result_carries_itinerary_metrics_of_final_itinerary():
    weights = CategoryWeights(
        praia=3, natureza=1, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    catalog = make_catalog()
    contract = make_contract(["a", "b", "c"])
    durations = {
        item["id"]: (item["duration_estimated_min"] + item["duration_estimated_max"]) / 2
        for item in catalog
    }
    for seed in (None, 7):
        result = execute_recommendation(
            catalog, contract, weights, daily_limit_min=275, trip_days=2, seed=seed,
        )
        metrics = result.itinerary_metrics
        assert metrics is not None
        assert [day.day for day in metrics.days] == [1, 2]
        for day, day_metrics in zip(result.itinerary.days, metrics.days):
            assert day_metrics.visit_minutes == pytest.approx(
                sum(durations[activity_id] for activity_id in day.activities)
            )
            assert day_metrics.total_minutes == day_metrics.travel_minutes + day_metrics.visit_minutes
            assert day_metrics.limit_violations == 0
        assert metrics.total_visit_minutes == pytest.approx(
            sum(durations[activity_id] for activity_id in result.activities)
        )
        dumped = result.model_dump(mode="json")
        assert set(dumped) == {
            "strategy", "seed", "itinerary", "activities", "metrics",
            "excluded_activities", "ineligible_activities", "notes", "itinerary_metrics",
        }
        assert set(dumped["metrics"]) == {"compatibility_media", "cobertura_interesses"}
