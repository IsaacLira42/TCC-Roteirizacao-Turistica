"""Configuracao de conexao com o banco (variaveis de ambiente).

Os nomes das variaveis seguem as usadas pelo docker-compose do backend
(POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT).
Nenhuma credencial e definida fora do ambiente padrao do projeto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseConfig:
    user: str
    password: str
    database: str
    host: str
    port: int

    @property
    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )


def load_config() -> DatabaseConfig:
    """Le a configuracao do ambiente; fallback = docker-compose do backend."""
    return DatabaseConfig(
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD", "postgres"),
        database=os.environ.get("POSTGRES_DB", "turisticas"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
    )
