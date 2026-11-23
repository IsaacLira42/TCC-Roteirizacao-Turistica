# Testes

Suíte em `backend/tests/`, executada com pytest (configuração em
`backend/pyproject.toml`).

## Como rodar

```bash
cd backend
pytest                        # suíte completa
pytest tests/unit             # só unitários
pytest tests/integration      # só integração
pytest tests/api              # só testes de API
pytest -v                     # verboso
pytest -k routing             # filtrar por palavra-chave
```

> Os testes de API usam substituição da sessão de banco por fixture
> (`tests/conftest.py`) e não exigem PostgreSQL ativo para os testes
> unitários. Testes que consultam matriz/OSRM usam dados falsos (fakes),
> sem chamar o serviço real.

## Estrutura

```
tests/
├── conftest.py               # fixtures compartilhadas
├── unit/                     # lógica de domínio, sem rede
│   ├── test_evaluation.py
│   ├── test_importer.py
│   ├── test_itineraries.py
│   ├── test_preference_schema.py
│   ├── test_recommendations.py
│   └── test_routing.py
├── integration/
│   └── test_evaluation_pipeline.py
└── api/                      # endpoints via TestClient
    ├── test_activities.py
    └── test_health.py
```

## Cobertura por área

| Área | O que é verificado |
|---|---|
| `preferences` | Contrato de `CategoryWeights` (7 campos, 0–3, sem extras, categorias ativas, todos_zerados) |
| `itineraries` | Heurística gulosa: elegibilidade, exclusões por motivo, limites diários, métricas por dia |
| `routing` | Validações do `RoutingMatrixContract`, leitura da matriz V2 132×132 e da matriz lote16 (142 atividades), parse de respostas OSRM `/table` |
| `recommendations` | Estratégias `personalized`/`baseline_random`, `tie_break`, compatibilidade, seed obrigatória, métricas |
| `evaluation` | Planos v4 (30 personalizadas + braço `personalized_id` + 30 baseline), hash do catálogo, agregações, exportação CSV/JSON |
| `api` | Respostas HTTP dos endpoints (activities CRUD, health, recommendations) |
| `integration` | Pipeline de avaliação ponta a ponta |
