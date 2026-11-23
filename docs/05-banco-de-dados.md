# Banco de dados

PostgreSQL 15, acessado por SQLAlchemy 2.0 síncrono (driver `psycopg2`).

Conexão montada em `app/core/database.py` a partir das variáveis `POSTGRES_*`:

```
postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}
```

## Tabela `activities`

| Coluna | Tipo | Nulo | Descrição |
|---|---|---|---|
| `id` | String (PK) | não | Identificador estável (ex.: `atividade_0001`) |
| `name` | String | não | Nome da atividade |
| `type` | String | não | Tag OpenStreetMap (ex.: `tourism=museum`) |
| `lat` | Float | não | Latitude decimal |
| `lon` | Float | não | Longitude decimal |
| `city` | String | sim | Município |
| `origin_block` | String | sim | Bloco de origem da coleta (alimentacao, lazer...) |
| `categories` | String | sim | Lista de categorias **serializada como JSON string** |
| `duration_estimated_min` | Integer | não | Duração mínima estimada (minutos) |
| `duration_estimated_max` | Integer | não | Duração máxima estimada (minutos) |
| `source_duration` | String | sim | Origem da estimativa de duração |
| `observation_annotation` | String | sim | Observação de revisão |

Restrições (CheckConstraint):

- `chk_lat_range`: `lat BETWEEN -90 AND 90`
- `chk_lon_range`: `lon BETWEEN -180 AND 180`
- `chk_duration_min_positive`: `duration_estimated_min > 0`
- `chk_duration_min_lte_max`: `duration_estimated_min <= duration_estimated_max`

> **`categories`**: o banco guarda string JSON (ex.: `["praia","lazer"]`).
> A serialização/conversão é transparente nas bordas —
> `_serialize_categories` no repositório (lista → string na escrita) e
> validadores Pydantic (string → lista na leitura).

## Migrações (Alembic)

Arquivos em `backend/migrations/versions/`:

| Revisão | Descrição |
|---|---|
| `e42e053f4f25` | Criação da tabela `activities` (com as check constraints) |
| `4c3e1bd5f27a` | Índice em `activities.id` |

Comandos:

```bash
alembic upgrade head    # aplicar
alembic downgrade -1    # desfazer última
alembic current         # estado atual
alembic history         # histórico
```

> Dentro do Docker, o banco tem `POSTGRES_HOST=db`; fora, ajuste
> `alembic.ini` (ou use as variáveis de ambiente do projeto).
>
> **Atenção:** o diretório `backend/migrations/` está no `.gitignore` e não é
> versionado. Em clone limpo, restaure `migrations/` antes de rodar
> `alembic upgrade head`; caso contrário, use um dump que já crie a tabela.

## Importação do catálogo (arquivo A3)

Catálogo atual da rodada v4: `backend/artefatos/a3-lotes-02-16-v4.json`
(estrutura `{"registros": [...]}` com **142 registros**). O desenho histórico
usa `backend/artefatos/a3-lotes-02-15-v2.json` (**132 registros**).

Campos em português são mapeados para o modelo canônico (ex.: `nome`→`name`,
`lat`/`latitude`→`lat`, `categorias`→`categories`,
`duracao_estimada_min`→`duration_estimated_min`).

Pipeline do importer (`app/modules/activities/importer.py`):

1. `read_a3_file` — carrega o JSON.
2. `validate_record` — exige `id, name, type, lat, lon, city, categorias,
   duracao_estimada_min, duracao_estimada_max`; valida lat/lon (±90/±180) e
   durações (min > 0, min ≤ max).
3. `record_exists` — pula IDs já presentes (`duplicated`).
4. Persiste com `categories` como JSON string.

Contadores retornados: `imported`, `skipped` (validação), `duplicated`, `errors`.

```python
from app.core.database import SessionLocal
from app.modules.activities.importer import import_a3_file

session = SessionLocal()
try:
    print(import_a3_file(
        "artefatos/a3-lotes-02-16-v4.json", session, dry_run=True
    ))   # valida sem gravar
    print(import_a3_file(
        "artefatos/a3-lotes-02-16-v4.json", session, dry_run=False
    ))   # grava
    session.commit()
finally:
    session.close()
```

`import_a3_default()` continua apontando para o arquivo histórico de 132
(`a3-lotes-02-15-v2.json`). Para importar a rodada v4, passe o caminho
explicitamente para `import_a3_file`, como acima.

Busca do arquivo padrão (nesta ordem): `/app/artefatos/a3-lotes-02-15-v2.json`
(container) e caminho relativo ao projeto (host).

## Backup e restauração

Dumps disponíveis da tabela `activities`:

| Arquivo | Conteúdo |
|---|---|
| `backend/activities_backup_antes_correcoes_auditoria_20261115.sql` | 142 registros no estado **anterior** às correções de catálogo (`catalog_hash 7a239ba1...`); foi a base de `official-20261115-lote16` |
| `backend/activities_backup_antes_lote16_20261115.sql` | 132 registros (`catalog_hash 5536c882...`) |
| `backend/activities_backup_com_suas_edicoes_20261114.sql` | 132 registros com edições de durações, anotações e nomes (`catalog_hash 5536c882...`); compatível com a API HTTP |
| `backend/activities_backup.sql` | Dump antigo de desenvolvimento (2 registros de teste) — **não use** |

> **Não existe dump do catálogo 142 pós-correção** (`catalog_hash
> 9b650926...`) usado pela rodada v4. Para restaurar esse estado, importe
> `artefatos/a3-lotes-02-16-v4.json` com o importer.
>
> O A3 de 132 (`a3-lotes-02-15-v2.json`), `catalogo-experimental-132.json` e
> o dump de `20261114` têm o mesmo conteúdo de 132 registros
> (`catalog_hash 5536c882...`). As rodadas oficiais de 132 registram
> `catalog_hash 47103b8c...`; esse hash **não** é reproduzido pelos arquivos
> atuais, embora os itinerários de 132 sejam reproduzíveis.

### Restaurar 142 (rodada v4)

Pré-requisito: tabela `activities` vazia. Com migrações presentes no clone:

```bash
cd backend
docker-compose up -d
docker-compose exec app alembic upgrade head
```

Sem `migrations/` versionado, crie a tabela restaurando o dump de 142
pré-correção e depois limpe os dados:

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

> Com 142 atividades, a API `/recommendations` retorna 503 para os IDs
> `atividade_0001`..`atividade_0010`, pois a matriz V2 só cobre 132. Use o
> runner de avaliação para a rodada v4; para a API HTTP, restaure o estado
> de 132.

> Se a tabela já contém 132 registros, o importer **pula** os IDs existentes
> (`duplicated`) e apenas insere os 10 novos. Para o estado v4 completo, com
> os valores corrigidos dos 132, comece de tabela vazia.

### Restaurar 132 (compatível com a API HTTP)

O dump cria a tabela. Em banco vazio, **não** rode Alembic antes. Se a tabela
já existir, remova-a primeiro (operação destrutiva):

```bash
docker-compose exec db psql -U postgres -d turisticas \
  -c "DROP TABLE IF EXISTS activities;"
docker-compose exec -T db psql -U postgres -d turisticas \
  < activities_backup_com_suas_edicoes_20261114.sql
```

> O serviço `db` não monta `backend/` em `/app`. Use redirecionamento de
> stdin (`docker-compose exec -T ... < arquivo`), como acima.

### Verificar a restauração

```bash
# 142 para a rodada v4; 132 para o dump de 20261114
docker-compose exec db psql -U postgres -d turisticas \
  -c "SELECT count(*) FROM activities;"

# lista o catálogo via API (HTTP funciona com 132)
curl "http://localhost:8000/api/v1/activities?limit=1"
```

### Cenários de recuperação

| O que aconteceu | Ação |
|---|---|
| Volume `pgdata` intacto (containers removidos) | `docker-compose up -d` — dados voltam automaticamente |
| Tabela apagada, volume intacto | Criar tabela (`alembic upgrade head` ou dump) e importar o A3 desejado |
| Volume apagado (`docker-compose down -v`) | `up -d` + criar tabela + importar `a3-lotes-02-16-v4.json` (142) ou restaurar dump de 132 |
| Só o catálogo 132 basta | Restaurar `activities_backup_com_suas_edicoes_20261114.sql` |
| Rodada v4 (142) | Tabela vazia + `import_a3_file("artefatos/a3-lotes-02-16-v4.json", ...)` |

### Gerar novo dump (após novas edições)

```bash
docker-compose exec db pg_dump -U postgres -d turisticas > activities_backup_<data>.sql
```

