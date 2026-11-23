"""CLI da ferramenta: consulta o banco e gera o mapa HTML."""

from __future__ import annotations

import sys
from pathlib import Path

from .data import fetch_points_from_database
from .build import write_map

DEFAULT_OUTPUT = Path("output") / "mapa_atividades.html"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Gera mapa interativo (Folium) das atividades do banco."
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Caminho do HTML de saída (padrão: %(default)s)",
    )
    args = parser.parse_args(argv)

    try:
        points, total = fetch_points_from_database()
    except Exception as exc:
        detalhe = str(exc).strip().splitlines()[0]
        print(f"Erro: não foi possível consultar o banco de dados ({detalhe}).", file=sys.stderr)
        print(
            "Verifique se o container 'db' está ativo (docker compose up -d db) "
            "e se as variáveis POSTGRES_* estão corretas.",
            file=sys.stderr,
        )
        return 1

    if not points:
        print("Erro: nenhum registro com coordenadas válidas foi encontrado.", file=sys.stderr)
        return 1

    invalid = total - len(points)
    output = args.output if args.output.is_absolute() else Path.cwd() / args.output
    try:
        path = write_map(points, output)
    except Exception as exc:
        print(f"Erro: falha ao gerar o HTML ({exc}).", file=sys.stderr)
        return 1

    print(f"Registros consultados: {total}")
    print(f"Pontos com coordenadas válidas: {len(points)}")
    print(f"Registros ignorados (coordenada inválida): {invalid}")
    print(f"Mapa gerado em: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
