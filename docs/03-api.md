# API

Base URL: `http://localhost:8000/api/v1`

Todas as rotas usam JSON. A documentação interativa (Swagger UI) está em
`http://localhost:8000/docs`.

## Endpoints

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/health/` | Liveness: `{"status": "ok"}` |
| GET | `/api/v1/health/live` | Igual ao anterior |
| GET | `/api/v1/health/ready` | Readiness: valida conexão com o PostgreSQL (503 se indisponível) |
| GET | `/api/v1/activities` | Lista atividades com paginação e filtros |
| GET | `/api/v1/activities/{activity_id}` | Detalhe de uma atividade |
| POST | `/api/v1/activities` | Cria atividade (201) |
| PUT | `/api/v1/activities/{activity_id}` | Atualiza campos parciais |
| DELETE | `/api/v1/activities/{activity_id}` | Remove atividade (204) |
| POST | `/api/v1/recommendations` | **Gera roteiro turístico personalizado** |

> `GET /api/v1/health` (sem barra final) responde **307** para
> `/api/v1/health/`; use a rota com barra para receber o JSON.

## GET /activities — listagem

Parâmetros de query:

| Param | Padrão | Descrição |
|---|---|---|
| `skip` | 0 | Registros a pular (≥ 0) |
| `limit` | 100 | Máximo por página (1–500) |
| `name` | — | Filtro por nome (busca parcial, `ILIKE`) |
| `category` | — | Filtro por categoria (busca parcial no JSON de categorias) |

```bash
curl "http://localhost:8000/api/v1/activities?limit=3&category=praia"
```

Exemplo de item de resposta:

```json
{
  "id": "atividade_0001",
  "name": "Praia de Ponta Negra",
  "type": "natural=beach",
  "lat": -5.882,
  "lon": -35.184,
  "city": "Natal",
  "origin_block": "lazer",
  "categories": ["praia", "lazer"],
  "duration_estimated_min": 60,
  "duration_estimated_max": 180,
  "source_duration": "estimativa_manual",
  "observation_annotation": null
}
```

## POST /recommendations — geração de roteiro

### Corpo de entrada

| Campo | Tipo | Regras | Descrição |
|---|---|---|---|
| `category_weights` | objeto | 7 chaves obrigatórias, inteiros 0–3, sem extras | Pesos de interesse por categoria |
| `seed` | int | obrigatória se todos os pesos = 0 **ou** se `tie_break="random"` com algum peso > 0 | Semente da baseline ou do desempate aleatório |
| `tie_break` | string | `"id"` (padrão) ou `"random"` | Desempate entre atividades de mesmo escore na estratégia `personalized` |
| `trip_days` | int | ∈ {2, 4, 7} | Dias da viagem |
| `daily_limit_min` | int | 240–360 | Limite de minutos por dia (240 no cenário de 2 dias; 360 nos demais) |
| `reference_point` | objeto | `{lat, lon}`, valores válidos | Ponto de partida do roteiro |

Categorias aceitas em `category_weights`:

`praia`, `natureza`, `gastronomia`, `cultura_historia`, `lazer`, `religioso`,
`compras_artesanato`

### Exemplo de requisição (perfil "litoral", cenário curto)

```bash
curl -X POST http://localhost:8000/api/v1/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "category_weights": {
      "praia": 3, "natureza": 2, "gastronomia": 1,
      "cultura_historia": 0, "lazer": 0,
      "religioso": 0, "compras_artesanato": 0
    },
    "seed": null,
    "trip_days": 2,
    "daily_limit_min": 240,
    "reference_point": {"lat": -5.87335, "lon": -35.18066}
  }'
```

> Ponto de referência oficial do experimento: Praça Ponta Negra
> `lat = -5.873350031512726`, `lon = -35.180663304041595`.

### Exemplo de baseline (todos os pesos zero)

```bash
curl -X POST http://localhost:8000/api/v1/recommendations \
  -H "Content-Type: application/json" \
  -d '{
    "category_weights": {
      "praia": 0, "natureza": 0, "gastronomia": 0,
      "cultura_historia": 0, "lazer": 0,
      "religioso": 0, "compras_artesanato": 0
    },
    "seed": 42,
    "trip_days": 2,
    "daily_limit_min": 240,
    "reference_point": {"lat": -5.873350031512726, "lon": -35.180663304041595}
  }'
```

Sem `seed` nessa condição, a API responde **422**:
`{"detail": "seed é obrigatória para a estratégia baseline_random"}`.

Com pesos não zerados e `tie_break="random"`, `seed` também é obrigatória:
`{"detail": "seed é obrigatória para desempate aleatório (tie_break=random)"}`.

### Estrutura da resposta

```jsonc
{
  "strategy": "personalized",            // ou "baseline_random"
  "seed": null,                          // seed usada (baseline ou tie_break random)
  "itinerary": {
    "days": [
      {"day": 1, "activities": ["atividade_0010", "atividade_0042"]},
      {"day": 2, "activities": ["atividade_0003"]}
    ]
  },
  "activities": ["atividade_0010", "atividade_0042", "atividade_0003"],
  "metrics": {
    "compatibility_media": 0.82,         // null em baseline_random
    "cobertura_interesses": 1.0          // null em baseline_random
  },
  "excluded_activities": [
    // atividade elegível que não coube no roteiro
    {"activity_id": "atividade_0007", "motive_code": "daily_limit_exceeded"}
  ],
  "ineligible_activities": [
    // atividade removida antes da seleção
    {"activity_id": "atividade_0011", "motive_code": "invalid_duration"}
  ],
  "itinerary_metrics": {
    "total_distance_m": 24530.5,
    "total_travel_minutes": 96.3,
    "total_visit_minutes": 300.0,
    "total_occupied_minutes": 396.3,
    "total_violations": 0,
    "days": [
      {
        "day": 1,
        "distance_m": 15000.0,
        "travel_minutes": 60.0,
        "visit_minutes": 180.0,
        "total_minutes": 240.0,
        "occupancy": 1.0,
        "limit_violations": 0
      }
      // ...
    ]
  },
  "notes": "Seleção baseada em compatibilidade decrescente com preferências explícitas."
}
```

### Códigos de motivo (`motive_code`)

| Código | Significado |
|---|---|
| `invalid_duration` | Durações ausentes/inválidas (min ≤ 0 ou min > max) → atividade **inelegível** |
| `no_viable_route` | Nenhuma perna de roteamento disponível para inserção |
| `daily_limit_exceeded` | Existe rota viável, mas o limite diário (240/360 min) impede a inserção |

### Erros

| HTTP | Quando |
|---|---|
| 422 | Payload inválido (pesos fora de 0–3, `trip_days` fora de {2,4,7}, `tie_break` inválido, `seed` ausente na baseline ou em `tie_break="random"`, extras no JSON) |
| 503 | Falha no OSRM (`RuntimeError`/`ValueError`) ou atividade fora da matriz V2 de 132 |

> A API HTTP ainda usa a matriz V2 de 132. Com banco de 142 atividades
> (rodada v4), o endpoint retorna **503** para os IDs `atividade_0001` a
> `atividade_0010`; use o runner de avaliação para a rodada de 142.
