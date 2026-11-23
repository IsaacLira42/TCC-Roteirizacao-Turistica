from app.modules.evaluation.service import (
    EvaluationProfile,
    EvaluationRunner,
    EvaluationScenario,
)
from app.modules.preferences.schemas import CategoryWeights
from app.modules.routing.service import LatLon, RoutingService


def test_evaluation_recommendations_itineraries_integration(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "distances": [[100.0]],
                "durations": [[60.0]],
            }

    monkeypatch.setattr(
        RoutingService,
        "load_v2_activity_ids",
        staticmethod(lambda filepath=None: ["activity-1"]),
    )
    monkeypatch.setattr(
        RoutingService,
        "load_v2_distance_matrix",
        staticmethod(lambda filepath: {"a0": {"a0": 0.0}}),
    )
    monkeypatch.setattr(
        RoutingService,
        "load_v2_duration_matrix",
        staticmethod(lambda filepath: {"a0": {"a0": 0.0}}),
    )
    monkeypatch.setattr(
        "app.modules.routing.service.httpx.get",
        lambda *args, **kwargs: Response(),
    )
    contract = RoutingService.build_matrix_contract(
        LatLon(lat=-5.8, lon=-35.2),
        [{"id": "activity-1", "lat": -5.8, "lon": -35.2}],
    )
    profile = EvaluationProfile(
        "litoral",
        CategoryWeights(
            praia=3, natureza=0, gastronomia=0, cultura_historia=0,
            lazer=0, religioso=0, compras_artesanato=0,
        ),
    )
    runner = EvaluationRunner(
        [
            {
                "id": "activity-1",
                "categories": ["praia"],
                "duration_estimated_min": 30,
                "duration_estimated_max": 30,
            }
        ],
        contract,
        base_seed=5,
        reference_point={"lat": -5.8, "lon": -35.2},
        scenarios=(EvaluationScenario("smoke", "Smoke", 2, 240),),
        profiles=(profile,),
    )

    report = runner.run()

    assert report["status"] == "completed"
    # Desenho v4: 30 reps da personalizada (tie_break=random) + 30 da baseline
    assert len(report["executions"]) == 60
    assert report["executions"][0]["result"]["activities"] == ["activity-1"]
    assert all(
        item["result"]["itinerary"]["days"]
        for item in report["executions"]
    )
