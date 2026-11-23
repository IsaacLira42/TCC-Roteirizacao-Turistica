from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Any, Sequence

import json
import os
import time
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from app.modules.preferences.schemas import CategoryWeights


_DEFAULT_V2 = (
    Path(__file__).resolve().parents[3]
    / "artefatos" / "osrm" / "referencias" / "matriz_a3-lotes-02-15-v2.json"
)


class LatLon(BaseModel):
    """Ponto geográfico com lat e lon."""

    lat: float = Field(..., description="Latitude decimal")
    lon: float = Field(..., description="Longitude decimal")

    model_config = {"extra": "forbid", "strict": True}


@dataclass(frozen=True)
class RoutingMatrixContract:
    """Matrizes de deslocamento indexadas por identidade de atividade."""

    distance_matrix: Dict[str, Dict[str, Optional[float]]]
    duration_matrix: Dict[str, Dict[str, Optional[float]]]
    activity_id_to_label: Dict[str, str]
    label_to_activity_id: Dict[str, str]
    reference_label: str = "ref"

    def __post_init__(self) -> None:
        activity_labels = list(self.activity_id_to_label.values())
        activity_ids = list(self.activity_id_to_label.keys())

        if self.reference_label in activity_labels:
            raise ValueError("O label de referência não pode ser label de atividade")
        if len(activity_labels) != len(set(activity_labels)):
            raise ValueError("activity_id_to_label contém labels duplicados")
        if len(self.label_to_activity_id) != len(set(self.label_to_activity_id)):
            raise ValueError("label_to_activity_id contém labels duplicados")
        if set(self.label_to_activity_id) != set(activity_labels):
            raise ValueError("Os mapas de atividade não possuem os mesmos labels")
        if set(self.label_to_activity_id.values()) != set(activity_ids):
            raise ValueError("Os mapas de atividade não possuem os mesmos IDs")
        for activity_id, label in self.activity_id_to_label.items():
            if self.label_to_activity_id.get(label) != activity_id:
                raise ValueError("activity_id_to_label e label_to_activity_id não são inversos")

        expected_labels = [self.reference_label, *activity_labels]
        for matrix_name, matrix in (
            ("distância", self.distance_matrix),
            ("duração", self.duration_matrix),
        ):
            if list(matrix) != expected_labels:
                raise ValueError(
                    f"Matriz de {matrix_name} deve conter exatamente os labels "
                    "na ordem do contrato"
                )
            for source in expected_labels:
                if list(matrix[source]) != expected_labels:
                    raise ValueError(
                        f"Matriz de {matrix_name} possui relações incompletas "
                        f"ou fora de ordem na origem {source!r}"
                    )
        if list(self.distance_matrix) != list(self.duration_matrix):
            raise ValueError("Matrizes de distância e duração possuem labels incompatíveis")

    def label_for(self, activity_id: str) -> str:
        try:
            return self.activity_id_to_label[activity_id]
        except KeyError as exc:
            raise ValueError(
                f"Atividade {activity_id!r} não está associada à matriz de routing"
            ) from exc

    def validate_activity_ids(self, activity_ids: Sequence[str]) -> None:
        if len(set(activity_ids)) != len(activity_ids):
            raise ValueError("A lista de atividades contém IDs duplicados")
        for activity_id in activity_ids:
            label = self.label_for(activity_id)
            if label not in self.distance_matrix or label not in self.duration_matrix:
                raise ValueError(f"Matriz incompleta para atividade {activity_id!r} ({label!r})")


class RoutingService:
    """Serviço de roteamento para cálculo de distâncias e durações.

    Responsabilidades:
    - Carregar e validar a matriz OSRM V2 quadrada N×N (atual: 132×132).
    - Construir matrizes combinadas (referência + N atividades).
    - Consultar OSRM /table para relações que envolvem o ponto de referência.
    - Converter coordenadas LatLon(lat, lon) → longitude,latitude para OSRM.
    - Gerenciar IDs de atividades pelo ordenamento do array V2.

    A arquitetura prioriza a matriz V2 para relações atividade-atividade
    e usa OSRM /table apenas para relações com o ponto de referência.
    """

    # --- Matriz V2 ---

    @staticmethod
    def _get_osrm(url: str) -> httpx.Response:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = httpx.get(url, timeout=10.0)
                response.raise_for_status()
                return response
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1 << attempt)
        raise RuntimeError(f"OSRM indisponível após 3 tentativas: {last_error}") from last_error

    @staticmethod
    def load_v2_distance_matrix_from_dict(data: dict) -> Dict[str, Dict[str, Optional[float]]]:
        """Valida dict já carregado e constrói matriz de distâncias."""
        if data.get("code") != "Ok":
            raise ValueError(f"Matriz V2 inválida: code={data.get('code')}")
        raw = data["distances"]
        n = len(raw)
        if n == 0 or any(len(row) != n for row in raw):
            raise ValueError(
                f"Matriz V2 de distâncias deve ser quadrada N×N, got {n}×{len(raw[0]) if raw else 0}"
            )
        return {
            f"a{i}": {f"a{j}": (float(raw[i][j]) if raw[i][j] is not None else None) for j in range(n)}
            for i in range(n)
        }

    @staticmethod
    def load_v2_duration_matrix_from_dict(data: dict) -> Dict[str, Dict[str, Optional[float]]]:
        """Valida dict já carregado e constrói matriz de durações."""
        if data.get("code") != "Ok":
            raise ValueError(f"Matriz V2 inválida: code={data.get('code')}")
        raw = data["durations"]
        n = len(raw)
        if n == 0 or any(len(row) != n for row in raw):
            raise ValueError(
                f"Matriz V2 de durações deve ser quadrada N×N, got {n}×{len(raw[0]) if raw else 0}"
            )
        return {
            f"a{i}": {f"a{j}": (float(raw[i][j]) if raw[i][j] is not None else None) for j in range(n)}
            for i in range(n)
        }

    @staticmethod
    def load_v2_distance_matrix(
        filepath: str | Path = _DEFAULT_V2,
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """Carrega a matriz de distâncias do artefato V2.

        A matriz é quadrada N×N, índices correspondem à ordem do array
        `a3-lotes-02-15-v2.json → registros[]`.
        Linha i, coluna j = distância em metros de registros[i] → registros[j].

        Returns:
            Dicionário aninhado: {"a0": {"a1": 6755.9, ...}, ...}.
            None indica célula vazia (não ocorre na V2 validada).
        """
        with open(filepath) as f:
            data = json.load(f)
        return RoutingService.load_v2_distance_matrix_from_dict(data)

    @staticmethod
    def load_v2_duration_matrix(
        filepath: str | Path = _DEFAULT_V2,
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """Carrega a matriz de durações do artefato V2 (em segundos)."""
        with open(filepath) as f:
            data = json.load(f)
        return RoutingService.load_v2_duration_matrix_from_dict(data)

    @staticmethod
    def load_v2_activity_ids(
        filepath: str | Path | None = None,
    ) -> List[str]:
        """Carrega os IDs na mesma ordem de ``registros[]`` usada pela matriz V2."""
        if filepath is None:
            filepath = Path(__file__).resolve().parents[3] / "artefatos" / "a3-lotes-02-15-v2.json"
        with open(filepath, encoding="utf-8") as file:
            records = json.load(file).get("registros", [])
        ids = [record.get("id") or record.get("id_atividade") for record in records]
        if not ids or any(not activity_id for activity_id in ids):
            raise ValueError("O catálogo associado à matriz V2 deve conter IDs válidos não vazios")
        if len(set(ids)) != len(ids):
            raise ValueError("O catálogo associado à matriz V2 contém IDs duplicados")
        return ids

    @staticmethod
    def load_matrix_contract(filepath: str | Path) -> RoutingMatrixContract:
        """Carrega um RoutingMatrixContract a partir de um arquivo JSON combinado pré-calculado."""
        with open(filepath, "r", encoding="utf-8") as file:
            data = json.load(file)
        return RoutingMatrixContract(
            distance_matrix=data["distance_matrix"],
            duration_matrix=data["duration_matrix"],
            activity_id_to_label=data["activity_id_to_label"],
            label_to_activity_id=data["label_to_activity_id"],
            reference_label=data.get("reference_label", "ref"),
        )

    @staticmethod
    def build_matrix_contract(
        reference_point: LatLon,
        activities: Sequence[Dict[str, Any]],
        *,
        v2_matrix_filepath: str | Path = _DEFAULT_V2,
        v2_activity_ids_filepath: str | Path | None = None,
    ) -> RoutingMatrixContract:
        """Constrói matrizes para um subconjunto em qualquer ordem de catálogo.

        A matriz atividade-atividade é sempre lida da V2 pela ordem do catálogo
        que originou o artefato. As relações com a referência são consultadas
        pelo OSRM na ordem local do subconjunto, mas armazenadas pelos labels V2.
        """
        activity_ids = [activity.get("id") for activity in activities]
        if not activities:
            return RoutingMatrixContract(
                distance_matrix={"ref": {"ref": 0.0}},
                duration_matrix={"ref": {"ref": 0.0}},
                activity_id_to_label={},
                label_to_activity_id={},
            )
        if any(not activity_id for activity_id in activity_ids):
            raise ValueError("Todas as atividades precisam de um ID estável")
        if len(set(activity_ids)) != len(activity_ids):
            raise ValueError("A lista de atividades contém IDs duplicados")

        v2_ids = RoutingService.load_v2_activity_ids(v2_activity_ids_filepath)
        v2_labels = {activity_id: f"a{i}" for i, activity_id in enumerate(v2_ids)}
        unknown = [activity_id for activity_id in activity_ids if activity_id not in v2_labels]
        if unknown:
            raise ValueError(
                f"Atividades ausentes no catálogo da matriz V2: {', '.join(unknown)}"
            )

        labels = [v2_labels[activity_id] for activity_id in activity_ids]
        v2_distance = RoutingService.load_v2_distance_matrix(v2_matrix_filepath)
        v2_duration = RoutingService.load_v2_duration_matrix(v2_matrix_filepath)
        distance: Dict[str, Dict[str, Optional[float]]] = {
            "ref": {"ref": 0.0, **{label: None for label in labels}}
        }
        duration: Dict[str, Dict[str, Optional[float]]] = {
            "ref": {"ref": 0.0, **{label: None for label in labels}}
        }
        for source in labels:
            distance[source] = {
                "ref": None,
                **{target: v2_distance[source][target] for target in labels},
            }
            duration[source] = {
                "ref": None,
                **{target: v2_duration[source][target] for target in labels},
            }
        for label in labels:
            distance[label]["ref"] = None
            duration[label]["ref"] = None

        coordinates = [
            RoutingService._extract_lon_lat({"lat": activity["lat"], "lon": activity["lon"]})
            for activity in activities
        ]
        all_coordinates = [",".join(map(str, RoutingService._extract_lon_lat(reference_point)))]
        all_coordinates.extend(",".join(map(str, coordinate)) for coordinate in coordinates)

        def query(sources: List[int], destinations: List[int], field: str) -> List[List[Optional[float]]]:
            url = RoutingService._build_osrm_table_url(
                all_coordinates, sources, destinations, "distance,duration"
            )
            try:
                response = RoutingService._get_osrm(url)
                parser = (
                    RoutingService._parse_osrm_table_response
                    if field == "distances"
                    else RoutingService._parse_osrm_table_response_duration
                )
                return parser(
                    response.json(),
                    len(activities),
                    sources,
                    destinations,
                )
            except Exception as exc:
                raise RuntimeError(f"Falha ao consultar OSRM /table: {exc}") from exc

        ref_to_activity = query([0], list(range(1, len(labels) + 1)), "distances")
        ref_to_activity_duration = query([0], list(range(1, len(labels) + 1)), "durations")
        activity_to_ref = query(list(range(1, len(labels) + 1)), [0], "distances")
        activity_to_ref_duration = query(list(range(1, len(labels) + 1)), [0], "durations")
        for i, label in enumerate(labels, start=1):
            distance["ref"][label] = ref_to_activity[0][i - 1]
            duration["ref"][label] = ref_to_activity_duration[0][i - 1]
            distance[label]["ref"] = activity_to_ref[i - 1][0]
            duration[label]["ref"] = activity_to_ref_duration[i - 1][0]

        mapping = {activity_id: v2_labels[activity_id] for activity_id in activity_ids}
        return RoutingMatrixContract(
            distance_matrix=distance,
            duration_matrix=duration,
            activity_id_to_label=mapping,
            label_to_activity_id={label: activity_id for activity_id, label in mapping.items()},
        )

    # --- Coordenadas ---

    @staticmethod
    def _extract_lon_lat(point: Any) -> Tuple[float, float]:
        """Converte LatLon, dicionário ou tupla para (lon, lat) OSRM.

        OSRM espera longitude,latitude na URL.
        - LatLon(lat, lon) → (lon, lat)
        - dict {"lat":float, "lon":float} → (lon, lat)
        - tuple/list (lat, lon) → (lon, lat)
        """
        if hasattr(point, "lat") and hasattr(point, "lon"):
            return (float(point.lon), float(point.lat))
        if isinstance(point, dict):
            return (float(point.get("lon", 0)), float(point.get("lat", 0)))
        # Assume tupla (lat, lon)
        return (float(point[1]), float(point[0]))

    # --- Lookup por índice (atividade → atividade) ---

    @staticmethod
    def _v2_index_to_label(i: int) -> str:
        """Converte índice 0–131 para rótulo da matriz V2: "a0", "a1", ..., "a131"."""
        return f"a{i}"

    # --- Consultas OSRM /table ---

    @staticmethod
    def _build_osrm_table_url(
        coordinates_lon_lat: List[str],
        sources: List[int],
        destinations: List[int],
        annotations: str = "distance,duration",
    ) -> str:
        """Constrói URL para a API OSRM /table.

        Formato: /table/v1/driving/{coordenadas}?sources=...&destinations=...&annotations=...
        - coordinates: lista de "lon,lat" separada por ";"
        - sources/destinations: índices (0-based) separados por ";"
        """
        coord_str = ";".join(coordinates_lon_lat)
        src_str = ";".join(str(s) for s in sources)
        dst_str = ";".join(str(d) for d in destinations)
        base_url = os.getenv("OSRM_BASE_URL", "http://localhost:5000").rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("OSRM_BASE_URL deve iniciar com http:// ou https://")
        return (
            f"{base_url}/table/v1/driving/{coord_str}"
            f"?sources={src_str}&destinations={dst_str}&annotations={annotations}"
        )

    @staticmethod
    def _parse_osrm_table_response(
        json_data: dict,
        n_activities: int,
        sources: Optional[Sequence[int]] = None,
        destinations: Optional[Sequence[int]] = None,
    ) -> List[List[Optional[float]]]:
        """Parseia uma resposta OSRM, completa ou reduzida.

        Quando ``sources`` e ``destinations`` são informados, as dimensões
        devem corresponder exatamente à seleção enviada ao OSRM. ``None`` é
        preservado como ausência de rota.
        """
        if not json_data or "distances" not in json_data:
            raise ValueError("Resposta OSRM /table não contém 'distances'")
        return RoutingService._parse_osrm_table_field(
            json_data["distances"], n_activities, sources, destinations
        )

    @staticmethod
    def _parse_osrm_table_response_duration(
        json_data: dict,
        n_activities: int,
        sources: Optional[Sequence[int]] = None,
        destinations: Optional[Sequence[int]] = None,
    ) -> List[List[Optional[float]]]:
        """Parseia durações OSRM, completas ou reduzidas."""
        if not json_data or "durations" not in json_data:
            raise ValueError("Resposta OSRM /table não contém 'durations'")
        return RoutingService._parse_osrm_table_field(
            json_data["durations"], n_activities, sources, destinations
        )

    @staticmethod
    def _parse_osrm_table_field(
        matrix: Any,
        n_activities: int,
        sources: Optional[Sequence[int]],
        destinations: Optional[Sequence[int]],
    ) -> List[List[Optional[float]]]:
        if not isinstance(matrix, list):
            raise ValueError("Campo da resposta OSRM /table deve ser uma matriz")
        expected_sources = list(sources) if sources is not None else list(range(n_activities + 1))
        expected_destinations = (
            list(destinations)
            if destinations is not None
            else list(range(n_activities + 1))
        )
        coordinate_count = n_activities + 1
        if any(
            index < 0 or index >= coordinate_count
            for index in [*expected_sources, *expected_destinations]
        ):
            raise ValueError("Seleção OSRM contém índice fora das coordenadas enviadas")
        if len(matrix) != len(expected_sources):
            raise ValueError(
                f"Resposta OSRM possui {len(matrix)} linhas; "
                f"esperadas {len(expected_sources)}"
            )
        result: List[List[Optional[float]]] = []
        for row in matrix:
            if not isinstance(row, list) or len(row) != len(expected_destinations):
                raise ValueError(
                    "Resposta OSRM possui colunas incompatíveis com os destinos solicitados"
                )
            result.append([float(value) if value is not None else None for value in row])
        return result

    # --- Matriz combinada: V2 + OSRM /table ---

    @staticmethod
    def build_combined_distance_matrix(
        reference_point: LatLon,
        activity_coords: List[Tuple[float, float]],
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """Constrói matriz distância 133×133: referência (índice 0) + 132 atividades.

        A matriz combina:
        - V2 atividade→atividade (índices 1–132, ou rótulos "a0".."a131")
        - OSRM /table referência→atividade (linha 0, colunas 1–132)
        - OSRM /table atividade→referência (linha 1..132, coluna 0)
        - Diagonal (0→0, i→i) = 0

        Args:
            reference_point: ponto de referência LatLon.
            activity_coords: lista de tuplas (lon, lat) na ordem do array V2
                (correspondendo a "a0".."a{n-1}").

        Returns:
            Matriz (n+1)×(n+1) como dicionário aninhado {"origem": {"destino": valor}}.
        """
        n_act = len(activity_coords)
        labels: List[str] = ["ref"] + [f"a{i}" for i in range(n_act)]

        matrix: Dict[str, Dict[str, Optional[float]]] = {
            label: {other: None for other in labels} for label in labels
        }

        # Diagonal = 0
        matrix["ref"]["ref"] = 0.0
        for i in range(n_act):
            matrix[f"a{i}"][f"a{i}"] = 0.0

        # 1. Atividade→atividade via matriz V2
        v2_dist = RoutingService.load_v2_distance_matrix()
        for i in range(n_act):
            for j in range(n_act):
                val = v2_dist.get(f"a{i}", {}).get(f"a{j}")
                if val is not None:
                    matrix[f"a{i}"][f"a{j}"] = val

        # 2. Coordenadas para OSRM /table (referência primeiro, depois atividades)
        all_coords_lon_lat: List[str] = []
        ref_lon, ref_lat = RoutingService._extract_lon_lat(reference_point)
        all_coords_lon_lat.append(f"{ref_lon},{ref_lat}")
        for c in activity_coords:
            lon, lat = c
            all_coords_lon_lat.append(f"{lon},{lat}")

        # 3. OSRM /table: referência → atividades
        sources_ref = [0]
        destinations_all = list(range(1, n_act + 1))
        url_ref_to_act = RoutingService._build_osrm_table_url(
            all_coords_lon_lat, sources_ref, destinations_all, "distance,duration"
        )
        try:
            resp = RoutingService._get_osrm(url_ref_to_act)
            data = resp.json()
            dist_matrix_ref = RoutingService._parse_osrm_table_response(
                data, n_act, sources_ref, destinations_all
            )
            # dist_matrix_ref[0][i+1] = distância ref → atividade i
            for i in range(n_act):
                matrix["ref"][f"a{i}"] = dist_matrix_ref[0][i]
        except Exception as e:
            raise RuntimeError(f"Falha ao consultar OSRM /table (ref→ativ): {e}")

        # 4. OSRM /table: atividades → referência
        sources_all = list(range(1, n_act + 1))
        destinations_ref = [0]
        url_act_to_ref = RoutingService._build_osrm_table_url(
            all_coords_lon_lat, sources_all, destinations_ref, "distance,duration"
        )
        try:
            resp = RoutingService._get_osrm(url_act_to_ref)
            data = resp.json()
            dist_matrix_act = RoutingService._parse_osrm_table_response(
                data, n_act, sources_all, destinations_ref
            )
            # dist_matrix_act[i+1][0] = distância atividade i → ref
            for i in range(n_act):
                matrix[f"a{i}"]["ref"] = dist_matrix_act[i][0]
        except Exception as e:
            raise RuntimeError(f"Falha ao consultar OSRM /table (ativ→ref): {e}")

        return matrix

    @staticmethod
    def build_combined_duration_matrix(
        reference_point: LatLon,
        activity_coords: List[Tuple[float, float]],
    ) -> Dict[str, Dict[str, Optional[float]]]:
        """Constrói matriz duração 133×133: referência (índice 0) + 132 atividades.

        Igual a build_combined_distance_matrix, porém usa a matriz V2 de durações
        e lê o campo 'durations' das respostas OSRM /table.
        """
        n_act = len(activity_coords)
        labels: List[str] = ["ref"] + [f"a{i}" for i in range(n_act)]

        matrix: Dict[str, Dict[str, Optional[float]]] = {
            label: {other: None for other in labels} for label in labels
        }

        matrix["ref"]["ref"] = 0.0
        for i in range(n_act):
            matrix[f"a{i}"][f"a{i}"] = 0.0

        # V2 de durações
        v2_dur = RoutingService.load_v2_duration_matrix()
        for i in range(n_act):
            for j in range(n_act):
                val = v2_dur.get(f"a{i}", {}).get(f"a{j}")
                if val is not None:
                    matrix[f"a{i}"][f"a{j}"] = val

        # Coordenadas
        all_coords_lon_lat: List[str] = []
        ref_lon, ref_lat = RoutingService._extract_lon_lat(reference_point)
        all_coords_lon_lat.append(f"{ref_lon},{ref_lat}")
        for c in activity_coords:
            lon, lat = c
            all_coords_lon_lat.append(f"{lon},{lat}")

        # OSRM /table: referência → atividades (duração)
        sources_ref = [0]
        destinations_all = list(range(1, n_act + 1))
        url_ref_to_act = RoutingService._build_osrm_table_url(
            all_coords_lon_lat, sources_ref, destinations_all, "distance,duration"
        )
        try:
            resp = RoutingService._get_osrm(url_ref_to_act)
            data = resp.json()
            dur_matrix_ref = RoutingService._parse_osrm_table_response_duration(
                data, n_act, sources_ref, destinations_all
            )
            for i in range(n_act):
                matrix["ref"][f"a{i}"] = dur_matrix_ref[0][i]
        except Exception as e:
            raise RuntimeError(f"Falha ao consultar OSRM /table (ref→ativ duração): {e}")

        # OSRM /table: atividades → referência (duração)
        sources_all = list(range(1, n_act + 1))
        destinations_ref = [0]
        url_act_to_ref = RoutingService._build_osrm_table_url(
            all_coords_lon_lat, sources_all, destinations_ref, "distance,duration"
        )
        try:
            resp = RoutingService._get_osrm(url_act_to_ref)
            data = resp.json()
            dur_matrix_act = RoutingService._parse_osrm_table_response_duration(
                data, n_act, sources_all, destinations_ref
            )
            for i in range(n_act):
                matrix[f"a{i}"]["ref"] = dur_matrix_act[i][0]
        except Exception as e:
            raise RuntimeError(f"Falha ao consultar OSRM /table (ativ→ref duração): {e}")

        return matrix


# Aliases de módulo (para patch em testes)
load_v2_distance_matrix = RoutingService.load_v2_distance_matrix
load_v2_duration_matrix = RoutingService.load_v2_duration_matrix
load_v2_distance_matrix_from_dict = RoutingService.load_v2_distance_matrix_from_dict
load_v2_duration_matrix_from_dict = RoutingService.load_v2_duration_matrix_from_dict