# Instalação e execução

## Requisitos

- Docker + Docker Compose (execução recomendada; não é preciso Python local)
- **Alternativa local:** Python 3.11+, PostgreSQL 15 e serviço OSRM acessível

## Execução com Docker Compose (recomendado)

```bash
cd backend
cp .env.example .env            # ajuste se necessário
docker-compose up --build
```

Serviços iniciados:

- **app** (API FastAPI) → `http://localhost:8000`
- **osrm** (osrm-routed, MLD) → `http://localhost:5000` (uso interno da API)
- **db** (PostgreSQL 15) → `localhost:5432` (usuário/senha: `postgres`/`postgres`, banco `turisticas`)

> O serviço `osrm` precisa do grafo em
> `artefatos/osrm/runtime/rio-grande-do-norte.osrm`. O PBF e o runtime **não
> são versionados**; em clone limpo, adquira/processe o PBF antes de subir o
> OSRM. A rodada oficial usa matriz pré-calculada e não chama o OSRM; nesse
> caso, o runner funciona mesmo com o container `osrm` parado.

Verificações rápidas:

```bash
curl http://localhost:8000/api/v1/health/       # {"status": "ok"}
curl http://localhost:8000/api/v1/health/ready  # {"status": "ready", "db": "connected"}
```

> `/api/v1/health` sem barra final responde **307** para `/api/v1/health/`.

Interface interativa (Swagger UI): `http://localhost:8000/docs`

> O app é executado por uvicorn com `--reload` implícito? **Não**: o comando é
> `uvicorn app.main:app --host 0.0.0.0 --port 8000`. Como o volume `.:/app`
> está montado, reinicie o container após alterar código para refletir mudanças.

## Variáveis de ambiente

Arquivo `backend/.env` (lido pelo `Settings`, em `app/core/config.py`):

| Variável | Padrão (`docker-compose.yml`) | Descrição |
|---|---|---|
| `POSTGRES_USER` | `postgres` | Usuário do PostgreSQL |
| `POSTGRES_PASSWORD` | `postgres` | Senha do PostgreSQL |
| `POSTGRES_DB` | `turisticas` | Nome do banco |
| `POSTGRES_HOST` | `db` (Docker) / `localhost` (local) | Host do banco |
| `POSTGRES_PORT` | `5432` | Porta do banco |
| `HEALTH_CHECK_DB` | `false` | Reservado para checagem de saúde |
| `OSRM_BASE_URL` | `http://osrm:5000` (Docker) / `http://localhost:5000` | URL do OSRM usada pela `RoutingService` |

> `.env.example` tem `POSTGRES_HOST=db`, voltado ao Docker Compose. Fora do
> Docker, use `POSTGRES_HOST=localhost` e `OSRM_BASE_URL=http://localhost:5000`.

## Execução sem Docker (desenvolvimento)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edite .env: POSTGRES_HOST=localhost, OSRM_BASE_URL=http://localhost:5000
alembic upgrade head                      # cria a tabela activities
uvicorn app.main:app --reload --port 8000 # sobe a API
```

O PostgreSQL e o OSRM continuam necessários. Para rodar apenas o OSRM
localmente com os dados do projeto:

```bash
docker run --rm -p 5000:5000 -v "$PWD/artefatos/osrm/runtime:/data:ro" \
  osrm/osrm-backend:latest osrm-routed --algorithm mld --max-table-size 200 \
  /data/rio-grande-do-norte.osrm
```

## Migrações (Alembic)

```bash
# dentro do container app ou com o venv ativado
alembic upgrade head          # aplica todas as migrações
alembic downgrade -1          # desfaz a última
alembic current               # revisão atual
```

> `alembic.ini` aponta `sqlalchemy.url = postgresql://postgres:postgres@db:5432/turisticas`
> (host `db`). Fora do Docker, ajuste a URL ou defina as variáveis `POSTGRES_*`.
>
> **Atenção:** `backend/migrations/` está no `.gitignore` e não é versionado.
> Em clone limpo, restaure `migrations/` antes de rodar Alembic; sem isso, use
> um dump que já crie a tabela `activities`.

## Popular o banco de atividades

O catálogo atual da rodada v4 tem **142 atividades**
(`artefatos/a3-lotes-02-16-v4.json`). A API HTTP ainda usa a matriz V2 de 132;
com banco de 142, `/recommendations` retorna **503** para os IDs
`atividade_0001`..`atividade_0010`.

### Catálogo 142 (rodada v4) — recomendado para o experimento

Pré-requisito: tabela `activities` vazia. Com `migrations/` presente:

```bash
cd backend
docker-compose up -d
docker-compose exec app alembic upgrade head
```

Sem `migrations/` versionado, crie a tabela restaurando o dump de 142
pré-correção e limpe os dados:

```bash
docker-compose exec -T db psql -U postgres -d turisticas \
  < activities_backup_antes_correcoes_auditoria_20261115.sql
docker-compose exec db psql -U postgres -d turisticas \
  -c "TRUNCATE TABLE activities;"
```

Importe o catálogo v4:

```bash
docker-compose exec app python -c "
from app.core.database import SessionLocal
from app.modules.activities.importer import import_a3_file
s = SessionLocal()
print(import_a3_file('artefatos/a3-lotes-02-16-v4.json', s, dry_run=False))
s.commit(); s.close()
"
```

Esperado: `{'imported': 142, 'skipped': 0, 'duplicated': 0, 'errors': 0}`.
Não existe dump do estado 142 pós-correção; o importer é o caminho suportado.

### Catálogo 132 (compatível com a API HTTP) — dump oficial

O dump cria a tabela. Em banco vazio, **não** rode Alembic antes. Se a tabela
já existir, remova-a primeiro (operação destrutiva):

```bash
docker-compose exec db psql -U postgres -d turisticas \
  -c "DROP TABLE IF EXISTS activities;"
docker-compose exec -T db psql -U postgres -d turisticas \
  < activities_backup_com_suas_edicoes_20261114.sql

# verificação: deve retornar 132
docker-compose exec db psql -U postgres -d turisticas \
  -c "SELECT count(*) FROM activities;"
```

O serviço `db` **não** monta `backend/` em `/app`; por isso o dump é enviado
por stdin (`exec -T ... < arquivo`), não com `-f /app/...`.

Detalhes e demais dumps em [05-banco-de-dados.md](05-banco-de-dados.md).

### Catálogo 132 via arquivo A3

`import_a3_default()` importa os 132 registros de
`artefatos/a3-lotes-02-15-v2.json`:

```python
from app.modules.activities.importer import import_a3_default

print(import_a3_default(dry_run=True))   # valida sem gravar
print(import_a3_default(dry_run=False))  # grava
```

Esperado: `{'imported': 132, 'skipped': 0, 'duplicated': 0, 'errors': 0}`.

> `backend/activities_backup.sql` é um dump antigo com apenas 2 registros de
> teste — não use para popular o catálogo.

## Parar e limpar

```bash
docker-compose down            # para os serviços
docker-compose down -v         # para e apaga o volume pgdata (dados!)
```
