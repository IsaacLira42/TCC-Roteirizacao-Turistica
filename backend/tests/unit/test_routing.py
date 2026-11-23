"""Testes unitários da integração OSRM — Etapa 2.

Cobertura obrigatória:
- A. Carregamento da matriz V2 (distâncias e durações).
- B. Validação de dimensões e índices.
- C. Consultas OSRM /table (referência → atividades e atividades → referência).
- D. Matrizes combinadas 133×133.
- E. Tratamento de falhas (null, HTTP, timeout, JSON inválido).
- F. Conversão de coordenadas.
"""

import json
import tempfile
import os
from unittest.mock import patch, MagicMock

import pytest

from app.modules.routing.service import RoutingMatrixContract, RoutingService


# ---------------------------------------------------------------------------
# Helpers para construir respostas OSRM /table
# ---------------------------------------------------------------------------

def _osrm_table_response_distances(n_activities: int, has_null: bool = False) -> dict:
    """Constrói uma resposta OSRM /table de distâncias.

    Estrutura: {"distances": [[...], [...], ...]} onde:
      - Linha 0 = referência → todas destinações
      - Linhas 1..n = atividades → todas destinações

    Com has_null=True, injeta None na célula (1, 2) — linha 1 (atividade 1),
    coluna 2 (atividade 2). Requer n_activities >= 2.
    """
    m = []
    # Linha 0: referência → atividades
    row0 = [0.0 if j == 0 else float(j * 100 + 50) for j in range(n_activities + 1)]
    m.append(row0)
    # Linhas de atividades
    for i in range(1, n_activities + 1):
        row = []
        for j in range(n_activities + 1):
            if j == 0:
                row.append(float(i * 100 + 20))
            elif j == i:
                row.append(0.0)
            else:
                row.append(float(j * 100 + 50 + i * 10))
        m.append(row)
    if has_null and n_activities >= 2:
        # Injeta None na célula (1, 2): atividade 1 → atividade 2
        m[1][2] = None
    return {"distances": m, "durations": m}


def test_matrix_contract_maps_activity_ids_to_labels():
    labels = ["ref", "a7"]
    contract = RoutingMatrixContract(
        distance_matrix={label: {item: 0.0 for item in labels} for label in labels},
        duration_matrix={label: {item: 0.0 for item in labels} for label in labels},
        activity_id_to_label={"atividade_0008": "a7"},
        label_to_activity_id={"a7": "atividade_0008"},
    )
    contract.distance_matrix["ref"]["a7"] = 10.0
    contract.duration_matrix["ref"]["a7"] = 60.0
    contract.distance_matrix["a7"]["ref"] = 20.0
    contract.duration_matrix["a7"]["ref"] = 120.0
    contract.validate_activity_ids(["atividade_0008"])
    assert contract.label_for("atividade_0008") == "a7"
    assert contract.label_to_activity_id["a7"] == "atividade_0008"


def test_matrix_contract_rejects_unknown_activity_id():
    labels = ["ref", "a0"]
    contract = RoutingMatrixContract(
        distance_matrix={label: {item: 0.0 for item in labels} for label in labels},
        duration_matrix={label: {item: 0.0 for item in labels} for label in labels},
        activity_id_to_label={"atividade_0001": "a0"},
        label_to_activity_id={"a0": "atividade_0001"},
    )
    with pytest.raises(ValueError, match="não está associada"):
        contract.validate_activity_ids(["atividade_9999"])


def _fixed_contract():
    labels = ["ref", "a2", "a0", "a1"]
    distance = {source: {target: 0.0 for target in labels} for source in labels}
    duration = {source: {target: 0.0 for target in labels} for source in labels}
    distance["ref"].update({"a2": 20.0, "a0": 30.0, "a1": 40.0})
    duration["ref"].update({"a2": 120.0, "a0": 180.0, "a1": 240.0})
    distance["a2"]["a0"] = 201.0
    distance["a0"]["a2"] = 202.0
    duration["a2"]["a0"] = 1201.0
    duration["a0"]["a2"] = 1202.0
    distance["a0"]["ref"] = 301.0
    duration["a0"]["ref"] = 1801.0
    return RoutingMatrixContract(
        distance_matrix=distance,
        duration_matrix=duration,
        activity_id_to_label={
            "atividade-A": "a2",
            "atividade-B": "a0",
            "atividade-C": "a1",
        },
        label_to_activity_id={
            "a2": "atividade-A",
            "a0": "atividade-B",
            "a1": "atividade-C",
        },
    )


def test_fixed_ids_use_correct_distance_and_duration_cells():
    contract = _fixed_contract()
    assert contract.distance_matrix[contract.label_for("atividade-A")]["a0"] == 201.0
    assert contract.duration_matrix[contract.label_for("atividade-A")]["a0"] == 1201.0
    assert contract.distance_matrix["ref"][contract.label_for("atividade-B")] == 30.0
    assert contract.duration_matrix["a0"]["ref"] == 1801.0


@pytest.mark.parametrize(
    "kwargs, message",
    [
        (
            {
                "activity_id_to_label": {"A": "a0"},
                "label_to_activity_id": {"a0": "B"},
            },
            "IDs",
        ),
        (
            {
                "activity_id_to_label": {"A": "a0", "B": "a0"},
                "label_to_activity_id": {"a0": "A", "a1": "B"},
            },
            "labels",
        ),
        (
            {
                "activity_id_to_label": {"A": "ref"},
                "label_to_activity_id": {"ref": "A"},
            },
            "referência",
        ),
    ],
)
def test_contract_rejects_inconsistent_maps(kwargs, message):
    with pytest.raises(ValueError, match=message):
        RoutingMatrixContract(
            distance_matrix={"ref": {"ref": 0.0}},
            duration_matrix={"ref": {"ref": 0.0}},
            **kwargs,
        )


def test_contract_rejects_missing_activity_relations():
    with pytest.raises(ValueError, match="relações incompletas"):
        RoutingMatrixContract(
            distance_matrix={
                "ref": {"ref": 0.0, "a0": 1.0},
                "a0": {"ref": 1.0},
            },
            duration_matrix={
                "ref": {"ref": 0.0, "a0": 1.0},
                "a0": {"ref": 1.0, "a0": 0.0},
            },
            activity_id_to_label={"A": "a0"},
            label_to_activity_id={"a0": "A"},
        )


def test_contract_rejects_distance_duration_label_order_mismatch():
    with pytest.raises(ValueError, match="ordem"):
        RoutingMatrixContract(
            distance_matrix={
                "ref": {"ref": 0.0, "a0": 1.0},
                "a0": {"ref": 1.0, "a0": 0.0},
            },
            duration_matrix={
                "a0": {"a0": 0.0, "ref": 1.0},
                "ref": {"a0": 1.0, "ref": 0.0},
            },
            activity_id_to_label={"A": "a0"},
            label_to_activity_id={"a0": "A"},
        )


# ---------------------------------------------------------------------------
# A. Carregamento da matriz V2
# ---------------------------------------------------------------------------


class TestLoadV2DistanceMatrix:
    """Testes para load_v2_distance_matrix."""

    def test_load_v2_distance_matrix_ok(self):
        """Carregamento bem-sucedido retorna dicionário aninhado com a
        dimensão lida do artefato de IDs."""
        matrix = RoutingService.load_v2_distance_matrix()
        assert isinstance(matrix, dict)
        assert len(matrix) == len(RoutingService.load_v2_activity_ids())

    def test_load_v2_distance_matrix_validates_code(self):
        """code != Ok lança ValueError."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(json.dumps({"code": "NotOk", "distances": [], "durations": [], "sources": [], "destinations": []}))
            tmppath = f.name
        try:
            with pytest.raises(ValueError, match="Matriz V2 inválida"):
                RoutingService.load_v2_distance_matrix(tmppath)
        finally:
            os.unlink(tmppath)

    def test_load_v2_distance_matrix_is_square(self):
        """Matriz carregada é quadrada, com dimensão igual ao catálogo da V2."""
        matrix = RoutingService.load_v2_distance_matrix()
        n = len(RoutingService.load_v2_activity_ids())
        assert len(matrix) == n
        for key in list(matrix.keys())[:3]:
            assert len(matrix[key]) == n
        assert matrix["a0"]["a0"] == 0.0
        assert matrix["a0"]["a1"] is not None
        assert isinstance(matrix["a0"]["a1"], float)

    def test_load_v2_distance_matrix_index_mapping(self):
        """Índice i do array V2 corresponde ao rótulo a{i}."""
        matrix = RoutingService.load_v2_distance_matrix()
        n = len(matrix)
        assert "a0" in matrix
        assert "a1" in matrix
        assert f"a{n - 1}" in matrix
        assert matrix[f"a{n - 1}"][f"a{n - 1}"] == 0.0


class TestLoadV2DurationMatrix:
    """Testes para load_v2_duration_matrix."""

    def test_load_v2_duration_matrix_same_dimension_as_distance(self):
        """Matriz de durações tem mesma dimensão que distâncias."""
        matrix = RoutingService.load_v2_duration_matrix()
        n = len(RoutingService.load_v2_activity_ids())
        assert len(matrix) == n
        for key in list(matrix.keys())[:3]:
            assert len(matrix[key]) == n
        assert matrix["a0"]["a0"] == 0.0
        assert isinstance(matrix["a0"]["a1"], float)


# ---------------------------------------------------------------------------
# B. Validação de dimensões e índices
# ---------------------------------------------------------------------------


class TestV2MatrixDimensions:
    """Validação de dimensões e rejeição de dimensões inválidas."""

    def test_invalid_distance_matrix_rows(self):
        """Matriz não quadrada lança ValueError."""
        bad_data = {
            "code": "Ok",
            "distances": [[0, 1], [0, 1], [0, 1, 1]],
            "durations": [],
            "sources": [],
            "destinations": [],
        }
        with pytest.raises(ValueError, match="quadrada"):
            RoutingService.load_v2_distance_matrix_from_dict(bad_data)

    def test_invalid_distance_matrix_cols(self):
        """Matriz com número incorreto de colunas lança ValueError."""
        bad_data = {
            "code": "Ok",
            "distances": [[0] * 3 for _ in range(2)],
            "durations": [],
            "sources": [],
            "destinations": [],
        }
        with pytest.raises(ValueError, match="quadrada"):
            RoutingService.load_v2_distance_matrix_from_dict(bad_data)


# ---------------------------------------------------------------------------
# C. Consultas OSRM /table
# ---------------------------------------------------------------------------


class TestBuildOSRMTableURL:
    """Testes para _build_osrm_table_url."""

    def test_url_format_ref_to_activities(self):
        """URL para referência → atividades: sources=0, destinations=1;2;...;132."""
        coord = ["-35.182087,-5.843243", "-35.188570,-5.789570", "-35.293503,-5.826730"]
        url = RoutingService._build_osrm_table_url(coord, sources=[0], destinations=[1, 2])
        assert "/table/v1/driving/" in url
        assert "sources=0" in url
        assert "destinations=1;2" in url
        assert "annotations=distance,duration" in url
        assert "geometries=" not in url
        assert "layer=" not in url

    def test_url_format_activities_to_ref(self):
        """URL para atividades → referência: sources=1;2;...;132, destinations=0."""
        coord = ["-35.182087,-5.843243", "-35.188570,-5.789570", "-35.293503,-5.826730"]
        url = RoutingService._build_osrm_table_url(coord, sources=[1, 2], destinations=[0])
        assert "sources=1;2" in url
        assert "destinations=0" in url


class TestParseOSRMTableResponse:
    """Testes para _parse_osrm_table_response."""

    def test_parse_distances_ref_to_activities(self):
        """Parse distâncias: matriz completa (n+1)×(n+1)."""
        data = _osrm_table_response_distances(3)
        result = RoutingService._parse_osrm_table_response(data, 3)
        # Retorna matriz completa: linha 0 = ref, linhas 1..n = atividades
        assert len(result) == 4
        # Cada linha tem n+1 colunas
        for row in result:
            assert len(row) == 4

    def test_parse_distances_activities_to_all(self):
        """Parse distâncias: cada linha tem n+1 colunas."""
        data = _osrm_table_response_distances(2)
        result = RoutingService._parse_osrm_table_response(data, 2)
        assert len(result) == 3
        assert len(result[0]) == 3
        assert len(result[1]) == 3
        assert len(result[2]) == 3

    def test_parse_distances_with_null(self):
        """Célula nula na resposta é preservada como None."""
        data = _osrm_table_response_distances(3, has_null=True)
        result = RoutingService._parse_osrm_table_response(data, 3)
        # O fixture injeta None em m[1][2]: atividade 1 → atividade 2
        assert result[1][2] is None
        # Diagonal e outras células intactas
        assert result[1][1] == 0.0
        assert result[1][0] is not None

    def test_parse_reduced_dimensions_and_preserves_null(self):
        ref_to_activities = RoutingService._parse_osrm_table_response(
            {"distances": [[10.0, None]]},
            2,
            sources=[0],
            destinations=[1, 2],
        )
        activities_to_ref = RoutingService._parse_osrm_table_response(
            {"distances": [[11.0], [None]]},
            2,
            sources=[1, 2],
            destinations=[0],
        )
        assert ref_to_activities == [[10.0, None]]
        assert activities_to_ref == [[11.0], [None]]

    def test_parse_rejects_misaligned_reduced_dimensions(self):
        with pytest.raises(ValueError, match="linhas"):
            RoutingService._parse_osrm_table_response(
                {"distances": [[10.0, 20.0], [30.0, 40.0]]},
                2,
                sources=[0],
                destinations=[1, 2],
            )


class TestParseOSRMTableResponseDuration:
    """Testes para _parse_osrm_table_response_duration."""

    def test_parse_durations_ref_to_activities(self):
        """Parse de durações: mesma estrutura que distâncias."""
        data = _osrm_table_response_distances(3)
        result = RoutingService._parse_osrm_table_response_duration(data, 3)
        assert len(result) == 4
        for row in result:
            assert len(row) == 4

    def test_parse_durations_with_null(self):
        """Célula nula em durações também vira None."""
        data = _osrm_table_response_distances(3, has_null=True)
        result = RoutingService._parse_osrm_table_response_duration(data, 3)
        assert result[1][2] is None
        assert result[1][1] == 0.0
        assert result[1][0] is not None


# ---------------------------------------------------------------------------
# D. Matrizes combinadas
# ---------------------------------------------------------------------------


class TestBuildCombinedDistanceMatrix:
    """Testes para build_combined_distance_matrix."""

    @patch("app.modules.routing.service.httpx.get")
    def test_combined_matrix_v2_lookup(self, mock_get):
        """Matriz combinada usa V2 para atividade↔atividade e OSRM para ref↔atividade."""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[500.0, 600.0]]},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[400.0], [700.0]]},
                raise_for_status=lambda: None,
            ),
        ]

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        matrix = RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

        assert "ref" in matrix
        assert "a0" in matrix
        assert "a1" in matrix
        assert "a2" not in matrix

        # Diagonal zero
        assert matrix["ref"]["ref"] == 0.0
        assert matrix["a0"]["a0"] == 0.0
        assert matrix["a1"]["a1"] == 0.0

        # OSRM ref → atividade: dist_matrix[0][i+1]
        assert matrix["ref"]["a0"] == 500.0
        assert matrix["ref"]["a1"] == 600.0

        # OSRM atividade → ref: dist_matrix[i+1][0]
        # 2ª resposta: [[0, 400, 700], [500, 0, 300], [600, 200, 0]]
        assert matrix["a0"]["ref"] == 400.0
        assert matrix["a1"]["ref"] == 700.0

    @patch("app.modules.routing.service.httpx.get")
    def test_combined_matrix_with_null_cells(self, mock_get):
        """Células nulas na resposta OSRM (ref↔atividade) são preservadas como None."""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[None, 600.0]]},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[400.0], [700.0]]},
                raise_for_status=lambda: None,
            ),
        ]

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        matrix = RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

        # O None da primeira resposta (ref → a0) é preservado
        assert matrix["ref"]["a0"] is None
        # O restante do OSRM está preenchido (não há None em a0→ref nem a1→ref)
        assert matrix["ref"]["a1"] == 600.0
        assert matrix["a0"]["ref"] == 400.0
        assert matrix["a1"]["ref"] == 700.0

    @patch("app.modules.routing.service.httpx.get")
    def test_combined_matrix_dimensions(self, mock_get):
        """Matriz combinada tem dimensão (n_activities+1) × (n_activities+1)."""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[500.0, 600.0]]},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[400.0], [700.0]]},
                raise_for_status=lambda: None,
            ),
        ]

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        matrix = RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

        n_act = len(activity_coords)
        expected_size = n_act + 1
        assert len(matrix) == expected_size
        for key in matrix:
            assert len(matrix[key]) == expected_size


# ---------------------------------------------------------------------------
# E. Tratamento de falhas
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Testes para tratamento de erros em consultas OSRM."""

    @patch("app.modules.routing.service.httpx.get")
    def test_http_error_raise_for_status(self, mock_get):
        """raise_for_status() que lança exceção é propagado como RuntimeError."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = Exception("404 Not Found")
        mock_get.return_value = mock_resp

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        with pytest.raises(RuntimeError, match="Falha ao consultar OSRM"):
            RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

    @patch("app.modules.routing.service.httpx.get")
    def test_timeout_propagation(self, mock_get):
        """Timeout na consulta OSRM é propagado como RuntimeError."""
        mock_get.side_effect = TimeoutError("Timeout")

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        with pytest.raises(RuntimeError, match="Falha ao consultar OSRM"):
            RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

    @patch("app.modules.routing.service.httpx.get")
    def test_json_decode_error(self, mock_get):
        """Resposta inválida (JSON decode error) é propagada como RuntimeError."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        mock_get.return_value = mock_resp

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        with pytest.raises(RuntimeError, match="Falha ao consultar OSRM"):
            RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

    @patch("app.modules.routing.service.httpx.get")
    def test_osrm_not_ok_code(self, mock_get):
        """Resposta sem 'distances' levanta erro."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"code": "NotOk", "message": "Some error"}
        mock_get.return_value = mock_resp

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        with pytest.raises(RuntimeError, match="Falha ao consultar OSRM"):
            RoutingService.build_combined_distance_matrix(reference_point, activity_coords)

    @patch("app.modules.routing.service.httpx.get")
    def test_unknown_id_inconsistency(self, mock_get):
        """IDs corretos (0..n_act-1) funcionam sem erro."""
        mock_get.side_effect = [
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[500.0, 600.0]]},
                raise_for_status=lambda: None,
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"distances": [[400.0], [700.0]]},
                raise_for_status=lambda: None,
            ),
        ]

        reference_point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        activity_coords = [(-35.188570, -5.789570), (-35.293503, -5.826730)]

        matrix = RoutingService.build_combined_distance_matrix(reference_point, activity_coords)
        assert "ref" in matrix
        assert "a0" in matrix
        assert "a1" in matrix


# ---------------------------------------------------------------------------
# F. Conversão de coordenadas
# ---------------------------------------------------------------------------


class TestCoordinateConversion:
    """Testes para _extract_lon_lat."""

    def test_extract_lon_lat_from_latlon(self):
        """LatLon(lat, lon) → (lon, lat)."""
        point = type("LatLon", (), {"lat": -5.843243, "lon": -35.182087})()
        result = RoutingService._extract_lon_lat(point)
        assert result == (-35.182087, -5.843243)

    def test_extract_lon_lat_from_dict(self):
        """dict lat/lon → (lon, lat)."""
        point = {"lat": -5.843243, "lon": -35.182087}
        result = RoutingService._extract_lon_lat(point)
        assert result == (-35.182087, -5.843243)

    def test_extract_lon_lat_from_tuple(self):
        """tupla (lat, lon) → (lon, lat)."""
        point = (-5.843243, -35.182087)
        result = RoutingService._extract_lon_lat(point)
        assert result == (-35.182087, -5.843243)

    def test_extract_lon_lat_reverse_order(self):
        """Verifica que a ordem lat/lon é invertida para OSRM (lon, lat)."""
        point = {"lat": -5.0, "lon": -35.0}
        result = RoutingService._extract_lon_lat(point)
        assert result == (-35.0, -5.0)


class TestLoadMatrixContract:
    """Testes para RoutingService.load_matrix_contract."""

    def test_load_matrix_contract_from_file(self, tmp_path):
        payload = {
            "reference_label": "ref",
            "activity_id_to_label": {"act_1": "a0", "act_2": "a1"},
            "label_to_activity_id": {"a0": "act_1", "a1": "act_2"},
            "distance_matrix": {
                "ref": {"ref": 0.0, "a0": 100.0, "a1": 200.0},
                "a0": {"ref": 100.0, "a0": 0.0, "a1": 150.0},
                "a1": {"ref": 200.0, "a0": 150.0, "a1": 0.0},
            },
            "duration_matrix": {
                "ref": {"ref": 0.0, "a0": 60.0, "a1": 120.0},
                "a0": {"ref": 60.0, "a0": 0.0, "a1": 90.0},
                "a1": {"ref": 120.0, "a0": 90.0, "a1": 0.0},
            },
        }
        file_path = tmp_path / "test_matrix.json"
        file_path.write_text(json.dumps(payload), encoding="utf-8")

        contract = RoutingService.load_matrix_contract(file_path)
        assert contract.reference_label == "ref"
        assert contract.label_for("act_1") == "a0"
        assert contract.label_for("act_2") == "a1"
        assert contract.distance_matrix["ref"]["a0"] == 100.0
        assert contract.duration_matrix["a0"]["a1"] == 90.0
