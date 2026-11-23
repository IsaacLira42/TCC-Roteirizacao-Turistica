import csv
import json

import pytest

from app.modules.evaluation.service import (
    EvaluationRunner,
    aggregate_results,
    build_plan,
    export_report,
    evaluate_itinerary_metrics,
    official_profiles,
    catalog_hash,
)
from app.modules.preferences.schemas import CategoryWeights
from app.modules.recommendations.service import execute_recommendation
from app.modules.routing.service import RoutingMatrixContract


REFERENCE = {"lat": -5.8, "lon": -35.2}


def make_catalog():
    return [
        {
            "id": "a",
            "lat": -5.8,
            "lon": -35.2,
            "categories": ["praia"],
            "duration_estimated_min": 30,
            "duration_estimated_max": 30,
        },
        {
            "id": "b",
            "lat": -5.81,
            "lon": -35.21,
            "categories": ["natureza"],
            "duration_estimated_min": 30,
            "duration_estimated_max": 30,
        },
    ]


def make_contract():
    labels = {"a": "a0", "b": "a1"}
    labels_all = ["ref", "a0", "a1"]
    distance = {
        source: {
            target: (0.0 if source == target else 100.0)
            for target in labels_all
        }
        for source in labels_all
    }
    duration = {
        source: {
            target: (0.0 if source == target else 60.0)
            for target in labels_all
        }
        for source in labels_all
    }
    return RoutingMatrixContract(
        distance,
        duration,
        labels,
        {"a0": "a", "a1": "b"},
    )


def test_plan_has_official_combinations_counts_and_seed_bounds():
    plan = build_plan(1000, REFERENCE)

    # 12 combinações x (30 personalized + 30 baseline)
    assert len(plan) == 720
    assert len({(item.scenario_id, item.profile_id) for item in plan}) == 12
    assert {item.scenario_id for item in plan} == {"curto", "medio", "longo"}
    assert {item.profile_id for item in plan} == {
        "litoral", "cultural", "gastronomico", "diversificado"
    }
    for combination in {(item.scenario_id, item.profile_id) for item in plan}:
        items = [
            item for item in plan
            if (item.scenario_id, item.profile_id) == combination
        ]
        baseline = [item for item in items if item.strategy == "baseline_random"]
        personalized = [item for item in items if item.strategy == "personalized"]
        assert len(baseline) == 30
        assert len(personalized) == 30
        assert [item.seed for item in baseline] == list(range(1001, 1031))
        assert [item.seed for item in personalized] == list(range(1001, 1031))
        assert len({item.run_id for item in items}) == len(items)


def test_plan_id_arm_adds_single_execution_per_combination():
    plan = build_plan(1000, REFERENCE, personalized_repetitions=30, include_id_arm=True)

    assert len(plan) == 732
    for combination in {(item.scenario_id, item.profile_id) for item in plan}:
        items = [
            item for item in plan
            if (item.scenario_id, item.profile_id) == combination
        ]
        id_arm = [item for item in items if item.strategy == "personalized_id"]
        personalized = [item for item in items if item.strategy == "personalized"]
        baseline = [item for item in items if item.strategy == "baseline_random"]
        assert len(id_arm) == 1
        assert len(personalized) == 30
        assert len(baseline) == 30
        # Desempate por id ignora a semente
        assert id_arm[0].seed is None
        assert id_arm[0].run_id.endswith("-personalized_id")
        assert len({item.run_id for item in items}) == len(items)


def test_plan_supports_custom_personalized_repetitions():
    plan = build_plan(1000, REFERENCE, personalized_repetitions=5)

    assert len(plan) == 12 * (5 + 30)
    for combination in {(item.scenario_id, item.profile_id) for item in plan}:
        items = [
            item for item in plan
            if (item.scenario_id, item.profile_id) == combination
        ]
        personalized = [item for item in items if item.strategy == "personalized"]
        assert len(personalized) == 5
        assert [item.seed for item in personalized] == list(range(1001, 1006))


def test_official_profiles_have_approved_weights():
    profiles = {profile.id: profile.weights for profile in official_profiles()}

    assert profiles["litoral"].praia == 3
    assert profiles["litoral"].natureza == 2
    assert profiles["cultural"].cultura_historia == 3
    assert profiles["cultural"].religioso == 2
    assert profiles["gastronomico"].gastronomia == 3
    assert all(
        getattr(profiles["diversificado"], category) == 2
        for category in (
            "praia", "natureza", "gastronomia", "cultura_historia",
            "lazer", "religioso", "compras_artesanato",
        )
    )


def test_catalog_hash_is_stable_across_input_order():
    catalog = make_catalog()
    assert catalog_hash(catalog) == catalog_hash(list(reversed(catalog)))


def test_evaluate_itinerary_metrics_applies_profile_to_baseline_result():
    weights = official_profiles()[0].weights
    metrics = evaluate_itinerary_metrics(make_catalog(), ["a", "b"], weights)

    # litoral: pesos ativos 3 (praia), 2 (natureza), 1 (gastronomia); S_max = 3/6
    assert metrics == {
        "compatibility_media": (0.5 + 2 / 6) / 2,
        "compatibility_media_normalized": ((0.5 + 2 / 6) / 2) / (3 / 6),
        "cobertura_interesses": 2 / 3,
        "zero_score_inserted_count": 0,
        "zero_score_inserted_ratio": 0.0,
        "empty_itinerary": False,
        "active_category_count": 3,
    }


def test_evaluate_itinerary_metrics_diversificado_s_max_makes_normalized_equal_one():
    weights = official_profiles()[3].weights  # diversificado: 7 categorias com peso 2
    metrics = evaluate_itinerary_metrics(make_catalog(), ["a"], weights)

    assert metrics["compatibility_media"] == pytest.approx(2 / 14)
    assert metrics["compatibility_media_normalized"] == pytest.approx(1.0)
    assert metrics["zero_score_inserted_count"] == 0
    assert metrics["zero_score_inserted_ratio"] == 0.0


def test_evaluate_itinerary_metrics_counts_zero_scores():
    weights = official_profiles()[0].weights  # litoral
    metrics = evaluate_itinerary_metrics(
        [{"id": "c", "categories": ["cultura_historia"]}], ["c"], weights
    )

    assert metrics["compatibility_media"] == 0.0
    assert metrics["compatibility_media_normalized"] == 0.0
    assert metrics["zero_score_inserted_count"] == 1
    assert metrics["zero_score_inserted_ratio"] == 1.0


def test_evaluate_itinerary_metrics_distinguishes_empty_and_unrepresented():
    weights = official_profiles()[0].weights
    empty = evaluate_itinerary_metrics(make_catalog(), [], weights)
    unrepresented = evaluate_itinerary_metrics(
        [{"id": "c", "categories": ["cultura_historia"]}], ["c"], weights
    )

    assert empty["compatibility_media"] is None
    assert empty["compatibility_media_normalized"] is None
    assert empty["zero_score_inserted_count"] == 0
    assert empty["zero_score_inserted_ratio"] is None
    assert empty["cobertura_interesses"] == 0.0
    assert empty["empty_itinerary"] is True
    assert unrepresented["compatibility_media"] == 0.0
    assert unrepresented["cobertura_interesses"] == 0.0
    assert unrepresented["empty_itinerary"] is False


def test_evaluate_itinerary_metrics_rejects_missing_activity():
    with pytest.raises(ValueError, match="ausentes no catálogo"):
        evaluate_itinerary_metrics(
            make_catalog(), ["missing"], official_profiles()[0].weights
        )


def test_runner_reuses_recommendations_and_itineraries_with_real_result():
    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=10,
        reference_point=REFERENCE,
    )
    report = runner.run()

    assert report["status"] == "completed"
    assert report["planned_execution_count"] == 720
    assert report["expected_execution_count"] == 720
    assert report["tie_break"] == "random"
    assert report["personalized_repetitions"] == 30
    assert report["catalog_activity_count"] == 2
    assert len(report["catalog_hash"]) == 64
    assert report["failed_execution_count"] == 0
    assert all(item["status"] == "succeeded" for item in report["executions"])
    assert all(item["result"]["itinerary"]["days"] for item in report["executions"])
    baseline = next(
        item for item in report["executions"] if item["strategy"] == "baseline_random"
    )
    assert baseline["metrics"] == {
        "compatibility_media": None,
        "cobertura_interesses": None,
    }
    assert baseline["evaluation_metrics"]["active_category_count"] == 3
    baseline_aggregate = next(
        item for item in report["aggregates"]
        if item["strategy"] == "baseline_random"
        and item["scenario_id"] == "curto"
        and item["profile_id"] == "litoral"
    )
    personalized_aggregate = next(
        item for item in report["aggregates"]
        if item["strategy"] == "personalized"
        and item["scenario_id"] == "curto"
        and item["profile_id"] == "litoral"
    )
    assert baseline_aggregate["planned_count"] == 30
    assert baseline_aggregate["compatibility_media_observation_count"] == 30
    assert personalized_aggregate["p_superiority_compatibility_media"] is not None
    assert baseline["evaluation_status"] == "succeeded"
    assert baseline["result"]["strategy"] == "baseline_random"


def test_runner_applies_the_matching_profile_to_all_twelve_combinations():
    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=10,
        reference_point=REFERENCE,
    )
    report = runner.run()
    expected_active_categories = {
        "litoral": 3,
        "cultural": 6,
        "gastronomico": 7,
        "diversificado": 7,
    }
    for row in report["executions"]:
        assert row["evaluation_metrics"]["active_category_count"] == (
            expected_active_categories[row["profile_id"]]
        )
        if row["strategy"] == "baseline_random":
            assert row["result"]["strategy"] == "baseline_random"


def test_baseline_same_seed_is_reproducible_and_positive_profile_is_evaluation_only():
    first = execute_recommendation(
        make_catalog(), make_contract(), CategoryWeights(**{name: 0 for name in
        ("praia", "natureza", "gastronomia", "cultura_historia", "lazer",
         "religioso", "compras_artesanato")}), 240, 2, 77
    )
    second = execute_recommendation(
        make_catalog(), make_contract(), CategoryWeights(**{name: 0 for name in
        ("praia", "natureza", "gastronomia", "cultura_historia", "lazer",
         "religioso", "compras_artesanato")}), 240, 2, 77
    )
    assert first.model_dump() == second.model_dump()
    assert first.strategy == "baseline_random"
    assert first.metrics.compatibility_media is None

    personalized_first = execute_recommendation(
        make_catalog(), make_contract(), official_profiles()[0].weights, 240, 2, None
    )
    personalized_second = execute_recommendation(
        make_catalog(), make_contract(), official_profiles()[0].weights, 240, 2, None
    )
    assert personalized_first.model_dump() == personalized_second.model_dump()
    assert personalized_first.strategy == "personalized"


def test_runner_preserves_empty_itinerary_as_valid_result():
    empty_catalog_contract = RoutingMatrixContract(
        {"ref": {"ref": 0.0}},
        {"ref": {"ref": 0.0}},
        {},
        {},
    )
    runner = EvaluationRunner(
        [],
        empty_catalog_contract,
        base_seed=1,
        reference_point=REFERENCE,
    )
    report = runner.run()

    assert report["status"] == "completed"
    assert all(item["inserted_activity_count"] == 0 for item in report["executions"])
    personalized = [
        item for item in report["executions"] if item["strategy"] == "personalized"
    ]
    assert personalized[0]["metrics"] == {
        "compatibility_media": None,
        "cobertura_interesses": 0.0,
    }
    assert personalized[0]["evaluation_metrics"] == {
        "compatibility_media": None,
        "compatibility_media_normalized": None,
        "cobertura_interesses": 0.0,
        "zero_score_inserted_count": 0,
        "zero_score_inserted_ratio": None,
        "empty_itinerary": True,
        "active_category_count": 3,
    }


def test_failures_are_not_recorded_as_zero_metrics():
    runner = EvaluationRunner(
        [{"id": "missing", "categories": [], "duration_estimated_min": 30,
          "duration_estimated_max": 30}],
        make_contract(),
        base_seed=1,
        reference_point=REFERENCE,
    )
    report = runner.run()

    assert report["status"] == "completed_with_failures"
    assert report["failed_execution_count"] == 720
    assert all(item["metrics"] is None for item in report["executions"])
    assert all(item["result"] is None for item in report["executions"])


def test_evaluation_failure_preserves_successful_execution(monkeypatch):
    def fail_evaluation(*args, **kwargs):
        raise ValueError("catálogo incompatível")

    monkeypatch.setattr(
        "app.modules.evaluation.service.evaluate_itinerary_metrics",
        fail_evaluation,
    )
    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1,
        reference_point=REFERENCE,
        scenarios=(),
    )
    runner.scenarios = (
        type("Scenario", (), {
            "id": "smoke", "trip_days": 2, "daily_limit_min": 240
        })(),
    )
    report = runner.run()

    assert report["executions"]
    row = report["executions"][0]
    assert row["status"] == "succeeded"
    assert row["result"] is not None
    assert row["evaluation_status"] == "failed"
    assert row["evaluation_metrics"] is None
    assert row["evaluation_error"]["type"] == "ValueError"
    aggregate = report["aggregates"][0]
    assert aggregate["successful_count"] == 30
    assert aggregate["evaluation_failed_count"] == 30
    assert aggregate["compatibility_media_mean"] is None


def test_aggregate_uses_sample_standard_deviation_and_median_differences():
    def row(strategy, value, run_id):
        return {
            "run_id": run_id, "scenario_id": "s", "profile_id": "p",
            "strategy": strategy, "status": "succeeded",
            "evaluation_status": "succeeded",
            "evaluation_metrics": {
                "compatibility_media": value,
                "cobertura_interesses": value,
                "empty_itinerary": False,
            },
            "inserted_activity_count": 1,
        }

    aggregates = aggregate_results([
        row("baseline_random", 0.0, "b1"),
        row("baseline_random", 1.0, "b2"),
        row("personalized", 0.75, "p1"),
    ])
    baseline = next(item for item in aggregates if item["strategy"] == "baseline_random")
    personalized = next(item for item in aggregates if item["strategy"] == "personalized")
    assert baseline["compatibility_media_stddev"] == pytest.approx(2 ** -0.5)
    assert baseline["compatibility_media_observation_count"] == 2
    # quartis inclusivos de [0.0, 1.0]
    assert baseline["compatibility_media_q1"] == pytest.approx(0.25)
    assert baseline["compatibility_media_q3"] == pytest.approx(0.75)
    assert baseline["compatibility_media_iqr"] == pytest.approx(0.5)
    assert baseline["compatibility_media_min"] == 0.0
    assert baseline["compatibility_media_max"] == 1.0
    assert personalized["baseline_compatibility_media_median"] == 0.5
    assert personalized["compatibility_media_difference_from_baseline_median"] == 0.25
    assert personalized["cobertura_interesses_difference_from_baseline_median"] == 0.25
    # P(personalizada > baseline) sobre 1x2 comparações: 0.75 vence só 0.0
    assert personalized["p_superiority_compatibility_media"] == 0.5
    assert personalized["compatibility_media_observation_count"] == 1


def test_superiority_probability_trivial_cases():
    def rows(strategy, values):
        return [
            {
                "run_id": f"{strategy}-{index}", "scenario_id": "s", "profile_id": "p",
                "strategy": strategy, "status": "succeeded",
                "evaluation_status": "succeeded",
                "evaluation_metrics": {
                    "compatibility_media": value,
                    "compatibility_media_normalized": value,
                    "cobertura_interesses": value,
                    "zero_score_inserted_count": 0,
                    "zero_score_inserted_ratio": 0.0,
                    "empty_itinerary": False,
                },
                "inserted_activity_count": 1,
                "itinerary_metrics": {
                    "total_distance_m": value * 1000,
                    "total_travel_minutes": value,
                    "total_visit_minutes": value,
                    "total_occupied_minutes": value,
                    "total_violations": 0,
                    "days": [],
                },
            }
            for index, value in enumerate(values)
        ]

    # P = 1.0 quando toda personalizada supera toda baseline
    aggregates = aggregate_results(
        rows("baseline_random", [0.0, 0.0, 0.0]) + rows("personalized", [1.0, 1.0])
    )
    personalized = next(item for item in aggregates if item["strategy"] == "personalized")
    assert personalized["p_superiority_compatibility_media"] == 1.0
    assert personalized["p_superiority_inserted_activity_count"] == 0.5

    # P = 0.0 quando nenhuma supera
    aggregates = aggregate_results(
        rows("baseline_random", [1.0, 1.0]) + rows("personalized", [0.0, 0.0, 0.0])
    )
    personalized = next(item for item in aggregates if item["strategy"] == "personalized")
    assert personalized["p_superiority_compatibility_media"] == 0.0

    # P = 0.5 com distribuições idênticas
    aggregates = aggregate_results(
        rows("baseline_random", [0.0, 1.0]) + rows("personalized", [0.0, 1.0])
    )
    personalized = next(item for item in aggregates if item["strategy"] == "personalized")
    assert personalized["p_superiority_compatibility_media"] == 0.5

    # Sem baseline correspondente: sem probabilidade de superioridade
    aggregates = aggregate_results(rows("personalized", [1.0]))
    assert "p_superiority_compatibility_media" not in aggregates[0]
    assert "p_superiority_compatibility_media" not in aggregate_results(
        rows("baseline_random", [1.0])
    )[0]


def test_aggregate_excludes_nulls_and_empty_compatibility_but_includes_empty_coverage():
    rows = [
        {
            "run_id": "empty", "scenario_id": "s", "profile_id": "p",
            "strategy": "baseline_random", "status": "succeeded",
            "evaluation_status": "succeeded",
            "evaluation_metrics": {
                "compatibility_media": None, "cobertura_interesses": 0.0,
                "empty_itinerary": True,
            },
            "inserted_activity_count": 0,
        },
        {
            "run_id": "invalid", "scenario_id": "s", "profile_id": "p",
            "strategy": "baseline_random", "status": "succeeded",
            "evaluation_status": "failed", "evaluation_metrics": None,
            "inserted_activity_count": 1,
        },
    ]
    aggregate = aggregate_results(rows)[0]
    assert aggregate["cobertura_interesses_observation_count"] == 1
    assert aggregate["compatibility_media_observation_count"] == 0
    assert aggregate["cobertura_interesses_mean"] == 0.0
    assert aggregate["compatibility_media_mean"] is None
    assert aggregate["evaluation_failed_count"] == 1


def test_evaluation_metrics_support_profile_without_active_categories():
    weights = CategoryWeights(
        praia=0, natureza=0, gastronomia=0, cultura_historia=0,
        lazer=0, religioso=0, compras_artesanato=0,
    )
    metrics = evaluate_itinerary_metrics(make_catalog(), ["a"], weights)
    assert metrics == {
        "compatibility_media": None,
        "compatibility_media_normalized": None,
        "cobertura_interesses": None,
        "zero_score_inserted_count": 0,
        "zero_score_inserted_ratio": None,
        "empty_itinerary": False,
        "active_category_count": 0,
    }


def test_aggregate_results_and_export_preserve_individual_rows(tmp_path):
    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=2,
        reference_point=REFERENCE,
    )
    report = runner.run()
    json_path, csv_path = export_report(report, tmp_path)

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    with csv_path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert len(loaded["executions"]) == 720
    assert len(rows) == 720
    assert {
        "evaluation_status",
        "evaluation_error_type",
        "evaluation_compatibility_media_normalized",
        "evaluation_zero_score_inserted_count",
        "baseline_compatibility_media_median",
        "compatibility_media_difference_from_baseline_median",
    }.issubset(rows[0])
    assert len(report["aggregates"]) == 24
    with pytest.raises(FileExistsError):
        export_report(report, tmp_path)


def test_evaluation_runner_metadata_and_partial_execution():
    from app.modules.evaluation.service import SCENARIOS, official_profiles

    single_scenario = (SCENARIOS[0],)
    single_profile = (official_profiles()[0],)

    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=single_scenario,
        profiles=single_profile,
        routing_matrix_id="test_matrix.json",
        routing_matrix_hash="fake_hash_123",
        execution_scope="partial",
    )
    report = runner.run()
    assert report["routing_matrix_id"] == "test_matrix.json"
    assert report["routing_matrix_hash"] == "fake_hash_123"
    assert report["execution_scope"] == "partial"
    assert report["planned_execution_count"] == 60
    assert report["completed_execution_count"] == 60
    assert len(report["executions"]) == 60
    # 30 personalized + 30 baseline
    personalized = [e for e in report["executions"] if e["strategy"] == "personalized"]
    baseline = [e for e in report["executions"] if e["strategy"] == "baseline_random"]
    assert len(personalized) == 30
    assert len(baseline) == 30
    assert baseline[0]["seed"] == 1001
    assert baseline[-1]["seed"] == 1030
    assert personalized[0]["seed"] == 1001
    assert personalized[-1]["seed"] == 1030


def test_cli_parse_args_modes(monkeypatch):
    from scripts.run_evaluation import parse_args

    # 1. Sem filtros (padrão oficial de 372)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
        ],
    )
    args = parse_args()
    assert args.scenario is None
    assert args.profile is None
    assert args.matrix_path is None

    # 2. --scenario curto
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
            "--scenario", "curto",
        ],
    )
    args = parse_args()
    assert args.scenario == "curto"
    assert args.profile is None

    # 3. --profile litoral
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
            "--profile", "litoral",
        ],
    )
    args = parse_args()
    assert args.scenario is None
    assert args.profile == "litoral"

    # 4. --scenario curto --profile litoral
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
            "--scenario", "curto",
            "--profile", "litoral",
            "--matrix-path", "matriz.json",
        ],
    )
    args = parse_args()
    assert args.scenario == "curto"
    assert args.profile == "litoral"
    assert args.matrix_path == "matriz.json"
    assert args.tie_break == "random"
    assert args.personalized_repetitions == 30

    # 4b. --tie-break id e --personalized-repetitions custom
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
            "--tie-break", "id",
            "--personalized-repetitions", "10",
        ],
    )
    args = parse_args()
    assert args.tie_break == "id"
    assert args.personalized_repetitions == 10

    # 4c. --tie-break both
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
            "--tie-break", "both",
        ],
    )
    args = parse_args()
    assert args.tie_break == "both"

    # 5. Cenário/perfil inválido deve levantar SystemExit
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_evaluation.py",
            "--base-seed", "1000",
            "--output-dir", "/tmp/test",
            "--reference-lat", "-5.87",
            "--reference-lon", "-35.18",
            "--scenario", "invalido",
        ],
    )
    with pytest.raises(SystemExit):
        parse_args()


def test_four_execution_modes_planning_counts_and_scopes():
    from app.modules.evaluation.service import SCENARIOS, official_profiles

    all_scenarios = SCENARIOS
    all_profiles = official_profiles()
    curto_scenario = [s for s in SCENARIOS if s.id == "curto"]
    litoral_profile = [p for p in official_profiles() if p.id == "litoral"]

    # Modo 1: Nenhum filtro -> 720 execuções, execution_scope="full"
    runner_full = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=all_scenarios,
        profiles=all_profiles,
        execution_scope="full",
    )
    plan_full = runner_full.plan()
    assert len(plan_full) == 720
    assert runner_full.execution_scope == "full"
    assert runner_full.selected_scenario is None
    assert runner_full.selected_profile is None

    # Modo 2: --scenario curto -> 240 execuções, execution_scope="partial"
    runner_scenario = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=curto_scenario,
        profiles=all_profiles,
        execution_scope="partial",
        selected_scenario="curto",
    )
    plan_scenario = runner_scenario.plan()
    assert len(plan_scenario) == 240
    assert {item.scenario_id for item in plan_scenario} == {"curto"}
    assert len({item.profile_id for item in plan_scenario}) == 4
    assert runner_scenario.execution_scope == "partial"
    assert runner_scenario.selected_scenario == "curto"
    assert runner_scenario.selected_profile is None

    # Modo 3: --profile litoral -> 180 execuções, execution_scope="partial"
    runner_profile = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=all_scenarios,
        profiles=litoral_profile,
        execution_scope="partial",
        selected_profile="litoral",
    )
    plan_profile = runner_profile.plan()
    assert len(plan_profile) == 180
    assert len({item.scenario_id for item in plan_profile}) == 3
    assert {item.profile_id for item in plan_profile} == {"litoral"}
    assert runner_profile.execution_scope == "partial"
    assert runner_profile.selected_scenario is None
    assert runner_profile.selected_profile == "litoral"

    # Modo 4: --scenario curto --profile litoral -> 60 execuções, execution_scope="partial"
    runner_both = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=curto_scenario,
        profiles=litoral_profile,
        execution_scope="partial",
        selected_scenario="curto",
        selected_profile="litoral",
    )
    plan_both = runner_both.plan()
    assert len(plan_both) == 60
    assert {item.scenario_id for item in plan_both} == {"curto"}
    assert {item.profile_id for item in plan_both} == {"litoral"}
    assert runner_both.execution_scope == "partial"
    assert runner_both.selected_scenario == "curto"
    assert runner_both.selected_profile == "litoral"

    # Verifica sementes e estratégias em cada combinação
    for plan, expected_combinations in [
        (plan_full, 12),
        (plan_scenario, 4),
        (plan_profile, 3),
        (plan_both, 1),
    ]:
        combos = {(item.scenario_id, item.profile_id) for item in plan}
        assert len(combos) == expected_combinations
        for combo in combos:
            combo_items = [item for item in plan if (item.scenario_id, item.profile_id) == combo]
            pers = [item for item in combo_items if item.strategy == "personalized"]
            base = [item for item in combo_items if item.strategy == "baseline_random"]
            assert len(pers) == 30
            assert [item.seed for item in pers] == list(range(1001, 1031))
            assert len(base) == 30
            assert [item.seed for item in base] == list(range(1001, 1031))


def test_export_report_csv_and_json_identifies_scope(tmp_path):
    from app.modules.evaluation.service import SCENARIOS, official_profiles

    runner_partial = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=[SCENARIOS[0]],
        profiles=[official_profiles()[0]],
        execution_scope="partial",
        selected_scenario="curto",
        selected_profile="litoral",
    )
    report_partial = runner_partial.run()
    assert report_partial["execution_scope"] == "partial"
    assert report_partial["selected_scenario"] == "curto"
    assert report_partial["selected_profile"] == "litoral"

    partial_dir = tmp_path / "partial"
    json_path, csv_path = export_report(report_partial, partial_dir)

    loaded_json = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded_json["execution_scope"] == "partial"
    assert loaded_json["selected_scenario"] == "curto"
    assert loaded_json["selected_profile"] == "litoral"

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 60
    for row in reader:
        assert row["execution_scope"] == "partial"

    # Também testar escopo full
    runner_full = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=1000,
        reference_point=REFERENCE,
        scenarios=[SCENARIOS[0]],
        profiles=[official_profiles()[0]],
        execution_scope="full",
    )
    report_full = runner_full.run()
    full_dir = tmp_path / "full"
    _, csv_full_path = export_report(report_full, full_dir)
    with csv_full_path.open(newline="", encoding="utf-8") as f:
        full_reader = list(csv.DictReader(f))
    assert len(full_reader) == 60
    for row in full_reader:
        assert row["execution_scope"] == "full"


# ---- Métricas secundárias: propagação, exportação e agregação ----

def test_runner_propagates_itinerary_metrics_to_json_and_csv(tmp_path):
    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=10,
        reference_point=REFERENCE,
    )
    report = runner.run()

    for execution in report["executions"]:
        assert execution["status"] == "succeeded"
        metrics = execution["itinerary_metrics"]
        assert metrics == execution["result"]["itinerary_metrics"]
        assert len(metrics["days"]) == execution["trip_days"]
        assert metrics["total_distance_m"] == pytest.approx(sum(d["distance_m"] for d in metrics["days"]))
        assert metrics["total_travel_minutes"] == pytest.approx(
            sum(d["travel_minutes"] for d in metrics["days"])
        )
        assert metrics["total_visit_minutes"] == pytest.approx(30.0 * execution["inserted_activity_count"])
        assert metrics["total_violations"] == 0
        for day, activities in zip(metrics["days"], execution["result"]["itinerary"]["days"]):
            if activities["activities"]:
                assert day["occupancy"] == pytest.approx(day["total_minutes"] / execution["daily_limit_min"])
            else:
                assert day["occupancy"] is None

    json_path, csv_path = export_report(report, tmp_path)
    exported = json.loads(json_path.read_text(encoding="utf-8"))
    assert [item["itinerary_metrics"] for item in exported["executions"]] == [
        item["itinerary_metrics"] for item in report["executions"]
    ]
    with csv_path.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == len(report["executions"])
    for row, execution in zip(rows, report["executions"]):
        for name in (
            "total_distance_m", "total_travel_minutes", "total_visit_minutes",
            "total_occupied_minutes", "total_violations",
        ):
            assert row[name] == str(execution["itinerary_metrics"][name])
        assert "occupancy" not in row


def test_aggregates_secondary_metrics_by_strategy_without_daily_occupancy():
    runner = EvaluationRunner(
        make_catalog(),
        make_contract(),
        base_seed=10,
        reference_point=REFERENCE,
    )
    report = runner.run()
    executions = {
        (item["scenario_id"], item["profile_id"], item["strategy"], item["seed"]): item
        for item in report["executions"]
    }

    for aggregate in report["aggregates"]:
        assert not any("occupancy" in key for key in aggregate)
        group = [
            item for key, item in executions.items()
            if key[:3] == (aggregate["scenario_id"], aggregate["profile_id"], aggregate["strategy"])
        ]
        distances = [item["itinerary_metrics"]["total_distance_m"] for item in group]
        if aggregate["strategy"] == "personalized":
            assert len(group) == 30
            # personalizada determinística (mesma semente, mesmo resultado):
            # estatísticas completas agora se aplicam às duas estratégias
            assert aggregate["total_distance_m_observation_count"] == 30
            assert aggregate["total_distance_m_mean"] == pytest.approx(distances[0])
            assert aggregate["total_distance_m_min"] == min(distances)
            assert aggregate["total_distance_m_max"] == max(distances)
            assert aggregate["total_violations_max"] == 0
            assert "total_distance_m_value" not in aggregate
        else:
            assert aggregate["total_distance_m_observation_count"] == 30
            assert aggregate["total_distance_m_mean"] == pytest.approx(sum(distances) / 30)
            assert aggregate["total_distance_m_min"] == min(distances)
            assert aggregate["total_distance_m_max"] == max(distances)
            assert aggregate["total_violations_max"] == 0
            assert "total_distance_m_value" not in aggregate


def test_aggregate_secondary_metrics_statistics_and_failures():
    def row(strategy, distance, run_id, status="succeeded"):
        succeeded = status == "succeeded"
        return {
            "run_id": run_id, "scenario_id": "s", "profile_id": "p",
            "strategy": strategy, "status": status,
            "evaluation_status": "succeeded" if succeeded else "not_run",
            "evaluation_metrics": {
                "compatibility_media": 0.5, "cobertura_interesses": 0.5, "empty_itinerary": False,
            } if succeeded else None,
            "inserted_activity_count": 2 if succeeded else None,
            "itinerary_metrics": {
                "total_distance_m": distance,
                "total_travel_minutes": distance / 100,
                "total_visit_minutes": 60.0,
                "total_occupied_minutes": distance / 100 + 60.0,
                "total_violations": 0,
                "days": [{"day": 1, "occupancy": 0.25}],
            } if succeeded else None,
        }

    aggregates = aggregate_results([
        row("baseline_random", 100.0, "b1"),
        row("baseline_random", 300.0, "b2"),
        row("baseline_random", None, "b3", status="failed"),
        row("personalized", 250.0, "p1"),
    ])
    baseline = next(item for item in aggregates if item["strategy"] == "baseline_random")
    personalized = next(item for item in aggregates if item["strategy"] == "personalized")

    assert baseline["total_distance_m_mean"] == 200.0
    assert baseline["total_distance_m_median"] == 200.0
    assert baseline["total_distance_m_stddev"] == pytest.approx(20000 ** 0.5)
    assert (baseline["total_distance_m_min"], baseline["total_distance_m_max"]) == (100.0, 300.0)
    assert baseline["total_distance_m_observation_count"] == 2
    assert baseline["total_occupied_minutes_mean"] == 62.0
    assert baseline["inserted_activity_count_mean"] == 2
    assert baseline["failed_count"] == 1
    # Estatísticas completas também na personalizada (1 observação)
    assert personalized["total_distance_m_mean"] == 250.0
    assert personalized["total_distance_m_observation_count"] == 1
    assert personalized["total_distance_m_stddev"] is None
    assert personalized["total_distance_m_q1"] is None
    assert personalized["total_distance_m_iqr"] is None
    assert "total_distance_m_value" not in personalized
    assert personalized["inserted_activity_count_mean"] == 2
    assert personalized["compatibility_media_difference_from_baseline_median"] == 0.0


def test_aggregate_tolerates_rows_without_itinerary_metrics():
    rows = [{
        "run_id": "legacy", "scenario_id": "s", "profile_id": "p",
        "strategy": "baseline_random", "status": "succeeded",
        "evaluation_status": "succeeded",
        "evaluation_metrics": {
            "compatibility_media": 1.0, "cobertura_interesses": 1.0, "empty_itinerary": False,
        },
        "inserted_activity_count": 1,
    }]
    aggregate = aggregate_results(rows)[0]

    assert aggregate["total_distance_m_mean"] is None
    assert aggregate["total_distance_m_observation_count"] == 0
    assert aggregate["compatibility_media_mean"] == 1.0
