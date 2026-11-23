import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.modules.activities.service import ActivityService
from app.modules.evaluation.service import (
    EvaluationRunner,
    SCENARIOS,
    catalog_hash,
    export_report,
    official_profiles,
)
from app.modules.routing.service import LatLon, RoutingService

OFFICIAL_REFERENCE_LAT = -5.873350031512726
OFFICIAL_REFERENCE_LON = -35.180663304041595


def _find_default_matrix() -> Optional[Path]:
    candidates = [
        Path("artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json"),
        Path("backend/artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json"),
        Path("/app/artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json"),
        Path(__file__).resolve().parents[1]
        / "artefatos"
        / "osrm"
        / "oficiais"
        / "praca-ponta-negra-lote16"
        / "matriz-combinada.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executa o experimento de recomendações")
    parser.add_argument("--base-seed", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--reference-lat", type=float, required=True)
    parser.add_argument("--reference-lon", type=float, required=True)
    parser.add_argument(
        "--osrm-base-url",
        default=None,
        help="URL base do OSRM; também pode ser definida por OSRM_BASE_URL",
    )
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument(
        "--matrix-path",
        default=None,
        help="Caminho para arquivo de matriz pré-calculada (RoutingMatrixContract JSON)",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        choices=["curto", "medio", "longo"],
        help="Execução parcial: filtra por ID de cenário (padrão: todos os 3 cenários)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        choices=["litoral", "cultural", "gastronomico", "diversificado"],
        help="Execução parcial: filtra por ID de perfil (padrão: todos os 4 perfis)",
    )
    parser.add_argument(
        "--personalized-repetitions",
        type=int,
        default=30,
        help=(
            "Número de repetições da estratégia personalizada por combinação "
            "(padrão: 30; sementes base_seed+1 .. base_seed+n)"
        ),
    )
    parser.add_argument(
        "--tie-break",
        default="random",
        choices=["id", "random", "both"],
        help=(
            "Desempate da personalizada: 'random' (aleatório com semente, "
            "720 execuções no desenho completo), 'id' (por id crescente) ou "
            "'both' (acrescenta UMA execução do braço personalized_id por "
            "combinação, 732 execuções no desenho completo)"
        ),
    )
    return parser.parse_args()


def _code_metadata() -> dict[str, object]:
    configured = os.getenv("GIT_COMMIT")
    if configured:
        if not re.fullmatch(r"[0-9a-fA-F]{40}", configured):
            return {
                "code_version": None,
                "code_dirty": None,
                "code_version_source": "invalid_GIT_COMMIT",
            }
        dirty = os.getenv("GIT_DIRTY")
        return {
            "code_version": configured.lower(),
            "code_dirty": (
                dirty.lower() == "true"
                if dirty is not None and dirty.lower() in {"true", "false"}
                else None
            ),
            "code_version_source": "environment",
        }
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            return {
                "code_version": None,
                "code_dirty": None,
                "code_version_source": "invalid_git_output",
            }
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
        return {
            "code_version": commit.lower(),
            "code_dirty": dirty,
            "code_version_source": "git",
        }
    except (OSError, subprocess.SubprocessError):
        return {
            "code_version": None,
            "code_dirty": None,
            "code_version_source": "unavailable",
        }


def main() -> int:
    args = parse_args()
    if args.osrm_base_url is not None:
        os.environ["OSRM_BASE_URL"] = args.osrm_base_url
    configuration = {
        "base_seed": args.base_seed,
        "output_dir": args.output_dir,
        "reference_point": {"lat": args.reference_lat, "lon": args.reference_lon},
        "osrm_base_url": os.getenv("OSRM_BASE_URL"),
    }
    session = SessionLocal()
    try:
        preparation_stage = "catalog_loading"
        try:
            activity_service = ActivityService(session=session)
            catalog_count = activity_service.count_activities()
            catalog = activity_service.list_activities(limit=catalog_count)
            if len(catalog) != catalog_count:
                raise RuntimeError(
                    f"Catálogo incompleto: esperados {catalog_count}, carregados {len(catalog)}"
                )
            catalog_dicts = [
                {"id": activity.id, "lat": activity.lat, "lon": activity.lon}
                for activity in catalog
            ]

            matrix_file = None
            if args.matrix_path:
                matrix_file = Path(args.matrix_path)
            elif (
                abs(args.reference_lat - OFFICIAL_REFERENCE_LAT) < 1e-6
                and abs(args.reference_lon - OFFICIAL_REFERENCE_LON) < 1e-6
            ):
                matrix_file = _find_default_matrix()

            if matrix_file is not None and matrix_file.exists():
                preparation_stage = "routing_matrix_load"
                contract = RoutingService.load_matrix_contract(matrix_file)
                with open(matrix_file, "rb") as mf:
                    routing_matrix_hash = hashlib.sha256(mf.read()).hexdigest()
                routing_matrix_id = str(matrix_file)
                # Validar que todas as atividades do catálogo estão na matriz
                catalog_ids = [a.id for a in catalog]
                contract.validate_activity_ids(catalog_ids)
            else:
                preparation_stage = "routing_matrix_build"
                reference = LatLon(lat=args.reference_lat, lon=args.reference_lon)
                contract = RoutingService.build_matrix_contract(reference, catalog_dicts)
                routing_matrix_id = (
                    "backend/artefatos/osrm/referencias/"
                    "matriz_a3-lotes-02-15-v2.json + OSRM /table para referência"
                )
                routing_matrix_hash = None

            scenarios = (
                [s for s in SCENARIOS if s.id == args.scenario]
                if args.scenario
                else SCENARIOS
            )
            profiles = (
                [p for p in official_profiles() if p.id == args.profile]
                if args.profile
                else official_profiles()
            )
            execution_scope = "partial" if (args.scenario or args.profile) else "full"

            if args.personalized_repetitions < 0:
                raise ValueError(
                    "--personalized-repetitions não pode ser negativo"
                )

            metadata = {
                "catalog_activity_count": len(catalog),
                "catalog_hash": catalog_hash(catalog),
                "routing_matrix_id": routing_matrix_id,
                "routing_matrix_hash": routing_matrix_hash,
                "execution_scope": execution_scope,
                "tie_break": args.tie_break,
                "personalized_repetitions": args.personalized_repetitions,
                "expected_execution_count": len(scenarios) * len(profiles) * (
                    30
                    + args.personalized_repetitions
                    + (1 if args.tie_break == "both" else 0)
                ),
            }
            if args.scenario:
                metadata["selected_scenario"] = args.scenario
            if args.profile:
                metadata["selected_profile"] = args.profile

            metadata.update(_code_metadata())
            configuration.update(metadata)
        except (RuntimeError, ValueError, OSError) as exc:
            failure = {
                "schema_version": 1,
                "status": "preparation_failed",
                "failure_stage": preparation_stage,
                "configuration": configuration,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "executions": [],
                "aggregates": [],
            }
            try:
                export_report(failure, args.output_dir, allow_overwrite=args.allow_overwrite)
            except FileExistsError as export_error:
                print(f"Falha na preparação; relatório não gravado: {export_error}")
            print(f"Falha na preparação do experimento: {exc}")
            return 2

        runner = EvaluationRunner(
            catalog,
            contract,
            base_seed=args.base_seed,
            reference_point={"lat": args.reference_lat, "lon": args.reference_lon},
            scenarios=scenarios,
            profiles=profiles,
            catalog_hash_value=metadata["catalog_hash"],
            routing_matrix_id=metadata["routing_matrix_id"],
            routing_matrix_hash=metadata["routing_matrix_hash"],
            code_version=metadata["code_version"],
            code_dirty=metadata["code_dirty"],
            code_version_source=metadata["code_version_source"],
            execution_scope=metadata["execution_scope"],
            selected_scenario=metadata.get("selected_scenario"),
            selected_profile=metadata.get("selected_profile"),
            tie_break=("id" if args.tie_break == "id" else "random"),
            personalized_repetitions=args.personalized_repetitions,
            include_id_arm=(args.tie_break == "both"),
        )
        report = runner.run()
        try:
            export_report(report, args.output_dir, allow_overwrite=args.allow_overwrite)
        except FileExistsError as exc:
            print(f"Resultados já existem e não foram sobrescritos: {exc}")
            return 2
        if report["status"] != "completed":
            print(f"Experimento incompleto: {report['failed_execution_count']} falhas.")
            return 2
        print(f"Experimento concluído: {report['completed_execution_count']} execuções.")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
