import pytest

from app.modules.itineraries.service import ItinerariesService
from app.modules.routing.service import RoutingMatrixContract


def contract(ids, distances, durations):
    labels = {activity_id: f"a{i}" for i, activity_id in enumerate(ids)}
    return RoutingMatrixContract(
        distance_matrix=distances,
        duration_matrix=durations,
        activity_id_to_label=labels,
        label_to_activity_id={label: activity_id for activity_id, label in labels.items()},
    )


def activity(activity_id, minimum=30, maximum=30):
    return {
        "id": activity_id,
        "duration_estimated_min": minimum,
        "duration_estimated_max": maximum,
    }


def matrices(ids, ref_distance=None, ref_seconds=None, edges=None):
    labels = [f"a{i}" for i in range(len(ids))]
    distances = {
        "ref": {"ref": 0.0, **{
            label: 0.0 if ref_distance is None else ref_distance[i]
            for i, label in enumerate(labels)
        }}
    }
    durations = {
        "ref": {"ref": 0.0, **{
            label: 0.0 if ref_seconds is None else ref_seconds[i]
            for i, label in enumerate(labels)
        }}
    }
    for i, source in enumerate(labels):
        distances[source] = {"ref": 0.0, **{target: 0.0 for target in labels}}
        durations[source] = {"ref": 0.0, **{target: 0.0 for target in labels}}
    for (source, target), values in (edges or {}).items():
        distances[f"a{source}"][f"a{target}"] = values[0]
        durations[f"a{source}"][f"a{target}"] = values[1]
    return contract(ids, distances, durations)


def run(candidates, matrix, limit=240, days=1):
    return ItinerariesService.build_itinerary(
        candidates, daily_limit_min=limit, trip_days=days, routing_contract=matrix
    )


def ids(result, day=0):
    return result["itinerary"].days[day].activities


def test_empty_itinerary():
    result = run([], contract([], {"ref": {"ref": 0.0}}, {"ref": {"ref": 0.0}}), days=2)
    assert [day.activities for day in result["itinerary"].days] == [[], []]


def test_uses_duration_midpoint_and_route_duration():
    matrix = matrices(["a"], ref_distance=[0], ref_seconds=[600])
    result = run([activity("a", 30, 90)], matrix, limit=100)
    assert ids(result) == ["a"]
    assert result["excluded_activities"] == []


def test_each_day_starts_at_reference_and_does_not_return():
    matrix = matrices(["a"], ref_distance=[10], ref_seconds=[60])
    result = run([activity("a", 1, 1)], matrix, limit=2, days=2)
    assert ids(result, 0) == ["a"]
    assert ids(result, 1) == []


def test_insertion_can_be_at_start_middle_and_end():
    matrix = matrices(
        ["a", "b", "c"],
        ref_distance=[1, 1, 1],
        ref_seconds=[60, 60, 60],
        edges={(0, 1): (10, 60), (1, 0): (10, 60), (0, 2): (10, 60),
               (2, 0): (10, 60), (1, 2): (10, 60), (2, 1): (10, 60)},
    )
    result = run([activity("a", 1, 1), activity("b", 1, 1), activity("c", 1, 1)],
                 matrix, limit=240)
    assert set(ids(result)) == {"a", "b", "c"}


def test_chooses_smallest_distance_position():
    matrix = matrices(
        ["a", "b", "c"], ref_distance=[1, 1, 1], ref_seconds=[60, 60, 60],
        edges={(0, 1): (10, 60), (1, 0): (10, 60), (0, 2): (10, 60),
               (2, 0): (10, 60), (1, 2): (1, 60), (2, 1): (100, 60)},
    )
    result = run([activity("a"), activity("b"), activity("c")], matrix)
    assert ids(result) == ["b", "c", "a"]


def test_daily_limit_includes_visits_and_displacements():
    matrix = matrices(["a"], ref_distance=[0], ref_seconds=[60])
    result = run([activity("a", 61, 61)], matrix, limit=61)
    assert result["excluded_activities"][0].motive_code == "daily_limit_exceeded"


def test_none_is_no_route():
    matrix = matrices(["a"], ref_distance=[None], ref_seconds=[None])
    result = run([activity("a")], matrix)
    assert result["excluded_activities"][0].motive_code == "no_viable_route"


def test_route_exists_but_time_exceeds_limit():
    matrix = matrices(["a"], ref_distance=[1], ref_seconds=[3600])
    result = run([activity("a")], matrix, limit=30)
    assert result["excluded_activities"][0].motive_code == "daily_limit_exceeded"


def test_invalid_duration_is_ineligible():
    matrix = matrices(["a"], ref_distance=[0], ref_seconds=[0])
    result = run([activity("a", 0, 10)], matrix)
    assert result["ineligible_activities"][0].motive_code == "invalid_duration"


def test_preserves_received_order():
    matrix = matrices(["a", "b"], ref_distance=[1, 1], ref_seconds=[60, 60],
                      edges={(0, 1): (100, 60), (1, 0): (1, 60)})
    result = run([activity("b"), activity("a")], matrix)
    assert ids(result) == ["b", "a"]


def test_ids_map_to_matrix_labels_when_catalog_order_differs():
    matrix = matrices(["a", "b"], ref_distance=[1, 1], ref_seconds=[60, 60],
                      edges={(0, 1): (10, 60), (1, 0): (20, 60)})
    result = run([activity("b"), activity("a")], matrix)
    assert set(ids(result)) == {"a", "b"}


def test_fixed_id_mapping_changes_heuristic_result_if_indices_are_swapped():
    labels = ["ref", "a2", "a0"]
    distance = {source: {target: 0.0 for target in labels} for source in labels}
    duration = {source: {target: 0.0 for target in labels} for source in labels}
    distance["ref"].update({"a2": 1.0, "a0": 1.0})
    duration["ref"].update({"a2": 60.0, "a0": 60.0})
    distance["a2"]["a0"] = 1.0
    duration["a2"]["a0"] = 120.0
    distance["a0"]["a2"] = 100.0
    contract_with_fixed_labels = RoutingMatrixContract(
        distance_matrix=distance,
        duration_matrix=duration,
        activity_id_to_label={"atividade-A": "a2", "atividade-B": "a0"},
        label_to_activity_id={"a2": "atividade-A", "a0": "atividade-B"},
    )
    result = run(
        [activity("atividade-B"), activity("atividade-A")],
        contract_with_fixed_labels,
    )
    assert ids(result) == ["atividade-A", "atividade-B"]
    assert contract_with_fixed_labels.distance_matrix["a2"]["a0"] == 1.0
    assert contract_with_fixed_labels.duration_matrix["a2"]["a0"] == 120.0


def test_subset_keeps_mapping():
    matrix = matrices(["a", "b", "c"], ref_distance=[1, 1, 1], ref_seconds=[60, 60, 60])
    result = run([activity("c")], matrix)
    assert ids(result) == ["c"]


def test_inconsistent_id_raises():
    matrix = matrices(["a"], ref_distance=[1], ref_seconds=[60])
    with pytest.raises(ValueError, match="não está associada"):
        run([activity("missing")], matrix)


def test_duplicate_candidate_id_raises():
    matrix = matrices(["a"], ref_distance=[1], ref_seconds=[60])
    with pytest.raises(ValueError, match="IDs estáveis"):
        run([activity("a"), activity("a")], matrix)


def test_tie_prefers_more_remaining_time():
    matrix = matrices(["a", "b"], ref_distance=[1, 1], ref_seconds=[60, 60],
                      edges={(0, 1): (0, 0), (1, 0): (0, 0)})
    result = run([activity("a"), activity("b")], matrix, limit=100, days=2)
    assert ids(result, 0) == ["b", "a"]


def test_tie_prefers_lower_day_index():
    matrix = matrices(["a", "b"], ref_distance=[1, 1], ref_seconds=[60, 60])
    result = run([activity("a"), activity("b")], matrix, limit=240, days=2)
    assert ids(result, 0) == ["b", "a"]


def test_tie_prefers_lower_position_index():
    matrix = matrices(
        ["a", "b", "c"], ref_distance=[1, 1, 1], ref_seconds=[60, 60, 60],
        edges={(0, 1): (0, 0), (1, 0): (0, 0), (0, 2): (0, 0),
               (2, 0): (0, 0), (1, 2): (0, 0), (2, 1): (0, 0)},
    )
    result = run([activity("a"), activity("b"), activity("c")], matrix)
    assert ids(result) == ["c", "b", "a"]


def test_distance_and_duration_matrices_must_match_contract():
    matrix = matrices(["a"], ref_distance=[1], ref_seconds=[60])
    with pytest.raises(ValueError, match="diverge"):
        ItinerariesService.build_itinerary(
            [activity("a")],
            distance_matrix={},
            duration_matrix=matrix.duration_matrix,
            routing_contract=matrix,
        )


# ---- D1: viabilidade de rota verificada por posição de inserção ----

def d1_matrix():
    """A=a0, B=a1, X=a2; ref → X inexistente, A → X e X → B válidos, B → X inexistente."""
    return matrices(
        ["A", "B", "X"],
        ref_distance=[100.0, 200.0, None],
        ref_seconds=[60.0, 120.0, None],
        edges={
            (0, 1): (50.0, 60.0),
            (1, 0): (None, None),
            (0, 2): (30.0, 60.0),
            (2, 1): (40.0, 60.0),
            (1, 2): (None, None),
        },
    )


def test_activity_without_reference_route_is_inserted_between_connected_activities():
    result = run([activity("A"), activity("B"), activity("X")], d1_matrix())

    assert ids(result) == ["A", "X", "B"]
    assert result["excluded_activities"] == []
    assert result["ineligible_activities"] == []
    day = result["itinerary_metrics"].days[0]
    assert day.distance_m == pytest.approx(100.0 + 30.0 + 40.0)
    assert day.travel_minutes == pytest.approx((60.0 + 60.0 + 60.0) / 60.0)
    assert day.visit_minutes == pytest.approx(90.0)


def test_activity_without_reference_route_cannot_be_first_activity():
    alone = run([activity("X")], d1_matrix(), days=2)
    assert [day.activities for day in alone["itinerary"].days] == [[], []]
    assert [(item.activity_id, item.motive_code) for item in alone["excluded_activities"]] == [
        ("X", "no_viable_route")
    ]

    with_anchor = run([activity("A"), activity("X")], d1_matrix(), days=2)
    assert [day.activities for day in with_anchor["itinerary"].days] == [["A", "X"], []]


def test_second_day_restarts_at_reference_and_counts_its_legs():
    matrix = matrices(
        ["A", "B"],
        ref_distance=[1000.0, 2000.0],
        ref_seconds=[600.0, 1200.0],
        edges={(0, 1): (5.0, 60.0), (1, 0): (7.0, 60.0)},
    )
    result = run([activity("A", 100, 100), activity("B", 100, 100)], matrix, limit=150, days=2)

    assert [day.activities for day in result["itinerary"].days] == [["A"], ["B"]]
    first, second = result["itinerary_metrics"].days
    assert (first.distance_m, first.travel_minutes, first.visit_minutes) == (1000.0, 10.0, 100.0)
    assert (second.distance_m, second.travel_minutes, second.visit_minutes) == (2000.0, 20.0, 100.0)
    assert second.total_minutes == 120.0
    assert second.occupancy == pytest.approx(120.0 / 150.0)


# ---- Métricas secundárias do roteiro final ----

def test_metrics_exclude_return_to_reference_leg():
    ids_ = ["A", "B"]
    labels = {"ref": 0.0, "a0": 0.0, "a1": 0.0}
    distances = {
        "ref": {**labels, "a0": 100.0, "a1": 900.0},
        "a0": {**labels, "ref": 99999.0, "a1": 200.0},
        "a1": {**labels, "ref": 88888.0, "a0": 900.0},
    }
    durations = {
        "ref": {**labels, "a0": 120.0, "a1": 900.0},
        "a0": {**labels, "ref": 99999.0, "a1": 240.0},
        "a1": {**labels, "ref": 88888.0, "a0": 900.0},
    }
    result = run([activity("A", 30, 50), activity("B", 20, 20)], contract(ids_, distances, durations))

    assert ids(result) == ["A", "B"]
    metrics = result["itinerary_metrics"]
    day = metrics.days[0]
    assert day.distance_m == 300.0
    assert day.travel_minutes == pytest.approx(6.0)
    assert day.visit_minutes == pytest.approx(60.0)
    assert day.total_minutes == pytest.approx(66.0)
    assert day.occupancy == pytest.approx(66.0 / 240.0)
    assert day.limit_violations == 0
    assert metrics.total_violations == 0


def test_metrics_totals_equal_sum_of_days_and_separate_travel_from_visits():
    matrix = matrices(
        ["A", "B", "C", "D"],
        ref_distance=[1000.0, 1500.0, 2500.0, 4000.0],
        ref_seconds=[300.0, 450.0, 750.0, 1200.0],
        edges={(0, 1): (300.0, 90.0), (1, 2): (800.0, 240.0), (2, 3): (900.0, 300.0)},
    )
    candidates = [activity("A", 60, 90), activity("B", 45, 45), activity("C", 90, 120), activity("D", 30, 60)]
    result = run(candidates, matrix, limit=180, days=3)
    metrics = result["itinerary_metrics"]

    assert len(metrics.days) == 3
    assert [day.day for day in metrics.days] == [1, 2, 3]
    for day in metrics.days:
        assert day.total_minutes == day.travel_minutes + day.visit_minutes
        if day.occupancy is not None:
            assert day.occupancy == pytest.approx(day.total_minutes / 180.0)
            assert day.occupancy <= 1.0
    assert metrics.total_distance_m == pytest.approx(sum(day.distance_m for day in metrics.days))
    assert metrics.total_travel_minutes == pytest.approx(sum(day.travel_minutes for day in metrics.days))
    assert metrics.total_visit_minutes == pytest.approx(sum(day.visit_minutes for day in metrics.days))
    assert metrics.total_occupied_minutes == pytest.approx(
        metrics.total_travel_minutes + metrics.total_visit_minutes
    )
    assert metrics.total_violations == 0
    inserted = {activity_id for day in result["itinerary"].days for activity_id in day.activities}
    by_id = {candidate["id"]: candidate for candidate in candidates}
    assert metrics.total_visit_minutes == pytest.approx(
        sum((by_id[item]["duration_estimated_min"] + by_id[item]["duration_estimated_max"]) / 2 for item in inserted)
    )


def test_empty_itinerary_metrics_have_no_active_days():
    result = run([activity("X")], d1_matrix(), days=2)
    metrics = result["itinerary_metrics"]

    assert [(day.day, day.distance_m, day.travel_minutes, day.visit_minutes, day.total_minutes,
             day.occupancy, day.limit_violations) for day in metrics.days] == [
        (1, 0.0, 0.0, 0.0, 0.0, None, 0),
        (2, 0.0, 0.0, 0.0, 0.0, None, 0),
    ]
    assert (metrics.total_distance_m, metrics.total_travel_minutes, metrics.total_visit_minutes,
            metrics.total_occupied_minutes, metrics.total_violations) == (0.0, 0.0, 0.0, 0.0, 0)


def test_summarize_metrics_flags_limit_violation_in_final_state():
    metrics = ItinerariesService.summarize_metrics(
        [["A"], []], [(10.0, 250.0, 10.0, 240.0), (0.0, 0.0, 0.0, 0.0)], 240
    )

    assert metrics.days[0].limit_violations == 1
    assert metrics.days[0].occupancy == pytest.approx(250.0 / 240.0)
    assert metrics.days[1].limit_violations == 0
    assert metrics.total_violations == 1
