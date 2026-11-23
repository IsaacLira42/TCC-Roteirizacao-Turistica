# Estrutura de arquivos do backend

```
backend/
├── app/                          # código-fonte da aplicação
│   ├── main.py                   # criação do FastAPI + router v1
│   ├── models.py                 # (reservado; modelos vivem em modules/)
│   ├── api/
│   │   └── v1/
│   │       ├── router.py         # agrega health + activities + recommendations
│   │       └── endpoints/
│   │           └── health.py     # /health/, /health/live, /health/ready
│   ├── core/
│   │   ├── config.py             # Settings (pydantic-settings, .env)
│   │   ├── database.py           # engine, SessionLocal, Base
│   │   └── exceptions.py         # (reservado)
│   ├── infrastructure/           # (reservado para adapters de infra)
│   └── modules/
│       ├── activities/
│       │   ├── endpoints.py      # CRUD /activities
│       │   ├── service.py        # regras de negócio
│       │   ├── repository.py     # acesso a dados (SQLAlchemy)
│       │   ├── models.py         # tabela activities (ORM)
│       │   ├── schemas.py        # ActivityCreate/Read/Update
│       │   └── importer.py       # importação de arquivos A3
│       ├── preferences/
│       │   └── schemas.py        # CategoryWeights (7 categorias, 0–3)
│       ├── recommendations/
│       │   ├── endpoints.py      # POST /recommendations
│       │   ├── service.py        # estratégias + compatibilidade
│       │   └── schemas.py        # RecommendationInput/Result, métricas
│       ├── itineraries/
│       │   └── service.py        # heurística gulosa dos dias
│       ├── routing/
│       │   └── service.py        # matriz V2/lote16 + OSRM /table → contrato
│       └── evaluation/
│           └── service.py        # runner, agregações, exportação
├── scripts/
│   ├── analise_v4.py             # análise auxiliar da rodada v4
│   └── run_evaluation.py         # CLI do experimento oficial
├── migrations/                   # NÃO versionado (ver .gitignore)
│   ├── env.py / script.py.mako
│   └── versions/
│       ├── e42e053f4f25_create_activities_table.py
│       └── 4c3e1bd5f27a_add_index_activities_id.py
├── tests/
│   ├── conftest.py
│   ├── unit/                     # test_evaluation, test_importer, ...
│   ├── integration/              # test_evaluation_pipeline
│   └── api/                      # test_activities, test_health
├── artefatos/                    # dados de apoio do experimento
│   ├── a3-lotes-02-15-v2.json    # catálogo histórico (132 registros)
│   ├── a3-lotes-02-16-v4.json    # catálogo atual da rodada v4 (142 registros)
│   ├── osrm/
│   │   ├── origem/               # rio-grande-do-norte.pbf (fonte bruta; não versionado)
│   │   ├── runtime/              # grafo do osrm-routed (não versionado)
│   │   ├── referencias/          # matriz V2 132×132 + relatório de validação
│   │   └── oficiais/
│   │       ├── praca-ponta-negra/          # matriz combinada 132 (histórico)
│   │       └── praca-ponta-negra-lote16/   # matriz combinada 142 (v4)
│   ├── oficiais/                 # catálogos 132/142, metadados e manifesto
│   └── Relatorio-osrm.md         # documentação do fluxo OSRM
├── experiments/                  # resultados das execuções
│   ├── pilot-ifrn-20261109/
│   ├── official-20261111-372/ (+ -v2, -v3)   # 132, 372
│   ├── official-20261115-lote16/             # 142 pré-correção, 372
│   └── official-v4-142-732/                  # 142, 732 (v4)
├── activities_backup.sql         # dump antigo (2 registros de teste)
├── activities_backup_antes_correcoes_auditoria_20261115.sql  # 142 pré-correção
├── activities_backup_antes_lote16_20261115.sql               # 132
├── activities_backup_com_suas_edicoes_20261114.sql           # 132 com edições
├── alembic.ini                   # config Alembic
├── docker-compose.yml            # app + osrm + db
├── Dockerfile                    # python:3.11-slim + uvicorn
├── requirements.txt              # dependências
├── pyproject.toml                # config pytest
├── README.md                     # resumo do backend
├── .env                          # variáveis locais (não versionado)
└── .env.example                  # modelo de variáveis
```

## Arquivos de dados relevantes

| Arquivo | Papel |
|---|---|
| `artefatos/a3-lotes-02-16-v4.json` | Catálogo atual de 142 atividades (rodada v4) |
| `artefatos/a3-lotes-02-15-v2.json` | Catálogo histórico de 132 atividades (API HTTP e matriz V2) |
| `artefatos/oficiais/catalogo-experimental-142-v2.json` | Catálogo congelado de 142 atividades usado na v4 |
| `artefatos/oficiais/catalogo-experimental-132.json` | Catálogo congelado histórico de 132 atividades |
| `artefatos/oficiais/manifesto-experimental.json` | Manifesto do experimento oficial |
| `artefatos/osrm/referencias/matriz_a3-lotes-02-15-v2.json` | Matriz OSRM 132×132 (distâncias em metros, durações em segundos) |
| `artefatos/osrm/referencias/RELATORIO_VALIDACAO.md` | Validação da matriz de referência |
| `artefatos/osrm/oficiais/praca-ponta-negra/matriz-combinada.json` | Matriz combinada 133×133 (referência + 132) |
| `artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json` | Matriz combinada 143×143 (referência + 142) |
| `artefatos/osrm/runtime/rio-grande-do-norte.osrm` | Grafo carregado pelo `osrm-routed` (não versionado) |

## Observações de versionamento

- `backend/migrations/` está no `.gitignore`; um clone limpo não consegue
  rodar `alembic upgrade head` sem restaurar esses arquivos.
- `backend/artefatos/osrm/origem/*.pbf` e
  `backend/artefatos/osrm/runtime/` não são versionados. Clone limpo precisa
  do PBF e do grafo pré-processado para subir o OSRM; a rodada oficial usa a
  matriz combinada versionada.
- O serviço `db` do Docker Compose não monta `backend/` em `/app`; comandos
  `psql -f /app/...` não funcionam nesse serviço. Use redirecionamento de
  stdin (`docker-compose exec -T db psql ... < arquivo`).

## O que está fora deste escopo

O diretório `tools/` (raiz do projeto) contém utilitários de visualização
(`execution_viewer`, `map_viewer`) e **não faz parte do backend**.
