# Backend do TCC

## Estrutura

- `app/`: código-fonte da aplicação FastAPI.
- `api/`: endpoints e roteadores da API (versão v1).
- `core/`: configurações e conexão com o banco de dados.
- `modules/`: módulos de domínio (activities, preferences, recommendations, itineraries, routing, evaluation).
- `infrastructure/`: implementações de infraestrutura (database, external services).
- `migrations/`: migrações do banco com Alembic.
- `tests/`: testes unitários, integração e de API.
- `scripts/`: scripts auxiliares de desenvolvimento.
- `data/`: dados locais para desenvolvimento.

## Requisitos

- Python 3.9+
- PostgreSQL
- Alembic
- Pydantic
- FastAPI
- SQLAlchemy 2.0
- HTTPX
- Pytest

## Instalação

```bash
cp .env.example .env
# ajuste .env conforme necessidade
pip install -r requirements.txt
```

## Execução

```bash
docker-compose up --build
```

A aplicação ficará disponível em `http://localhost:8000/api/v1/health`.

## Testes

```bash
pytest
```

## Alembic

Para aplicar migrações:

```bash
alembic upgrade head
```

## Observações

- O banco de dados é executado via Docker Compose (serviço `db`).
- A aplicação usa SQLAlchemy síncrono.
- A estrutura segue a arquitetura modular aprovada.
- A CLI de Evaluation registra `code_version` somente como hash completo
  comprovado pelo Git ou por `GIT_COMMIT` validado. `code_dirty` indica
  modificações não commitadas quando detectáveis, e
  `code_version_source` registra a origem. Em containers sem `.git`, forneça
  `GIT_COMMIT` com 40 caracteres hexadecimais e, se aplicável, `GIT_DIRTY`;
  sem identificação comprovável, a versão permanece `null`.