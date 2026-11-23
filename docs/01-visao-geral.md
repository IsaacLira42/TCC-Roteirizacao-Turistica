# Visão geral

## O que o sistema faz

O backend implementa um sistema experimental de **roteirização turística
personalizada**. Dado o perfil de interesses de um turista expresso em pesos
(inteiros 0–3) para sete categorias de turismo, o sistema:

1. Carrega o **catálogo de atividades turísticas** do banco de dados
   (região do Rio Grande do Norte / Natal). A rodada v4 usa **142
   atividades** (`artefatos/a3-lotes-02-16-v4.json`); o desenho histórico usa
   **132** (`artefatos/a3-lotes-02-15-v2.json`).
2. Monta **matrizes de deslocamento** (distância em metros e duração em
   segundos) entre o ponto de referência e as atividades, e entre as
   atividades entre si.
3. Seleciona as atividades por **compatibilidade com as preferências**
   (estratégia `personalized`) ou de forma **aleatória com semente**
   (estratégia `baseline_random`), conforme os pesos informados.
4. Constrói um **roteiro de 2, 4 ou 7 dias**, inserindo atividades de forma
   gulosa nos dias, respeitando o limite de minutos por dia (240 min no
   cenário curto; 360 min nos demais).
5. Retorna o roteiro, atividades excluídas (com motivo), atividades
   inelegíveis e métricas (compatibilidade média, cobertura de interesses,
   distância total, tempos, ocupação e violações de limite).

## Serviços da solução

O sistema é composto por **três serviços** orquestrados pelo Docker Compose:

| Serviço | Imagem | Porta | Papel |
|---|---|---|---|
| `app` | `python:3.11-slim` + uvicorn | 8000 | API FastAPI |
| `osrm` | `osrm/osrm-backend:latest` | 5000 | Motor de roteamento (MLD), serve `/table` |
| `db` | `postgres:15` | 5432 | Banco PostgreSQL (catálogo) |

Volume persistente do banco: `pgdata`.

## Arquivo de dados crítico do OSRM

O serviço OSRM carrega o grafo pré-processado de **Rio Grande do Norte**:

- Entrada: `backend/artefatos/osrm/origem/rio-grande-do-norte.pbf`
- Dados prontos para `osrm-routed`: `backend/artefatos/osrm/runtime/rio-grande-do-norte.osrm`
  (e arquivos auxiliares `.partition`, `.cells`, `.mlgdr`, etc.)

A API prioriza a **matriz V2 pré-calculada** (132×132, atividade→atividade)
em `backend/artefatos/osrm/referencias/matriz_a3-lotes-02-15-v2.json` e usa o
OSRM `/table` apenas para as pernas que envolvem o ponto de referência.

A rodada v4 (142 atividades) usa a **matriz combinada pré-calculada** em
`backend/artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json`.

> **Limitação atual:** a API HTTP de recomendações valida o catálogo contra a
> matriz V2 de 132. Com banco de 142 atividades, os IDs `atividade_0001` a
> `atividade_0010` não existem na V2 e o endpoint retorna **503**. A rodada de
> 142 executa pelo runner com a matriz lote16, não pela API.

## Fluxo macro de uma requisição de recomendação

```
POST /api/v1/recommendations
        │
        ▼
validação (Pydantic: CategoryWeights, trip_days, daily_limit_min, reference_point)
        │
        ▼
carregar catálogo do PostgreSQL (ActivityService)
        │
        ▼
construir RoutingMatrixContract (matriz V2 132 + OSRM /table para a referência)
        │
        ▼
escolher estratégia:
  - todos os pesos zero  → baseline_random (exige seed)
  - algum peso > zero    → personalized (compatibilidade decrescente;
                            tie_break "id" ou "random"; random exige seed)
        │
        ▼
ItinerariesService.build_itinerary (inserção gulosa + avaliação de pernas)
        │
        ▼
RecommendationResult (itinerário, métricas, excluídas, inelegíveis)
```

## Estratégias de seleção

| Estratégia | Quando | Detalhe |
|---|---|---|
| `personalized` | ao menos um peso de categoria > 0 | Ordena catálogo por compatibilidade decrescente e insere gulosa. `tie_break="id"` (padrão) desempata por ID; `tie_break="random"` embaralha o empate e exige `seed`. |
| `baseline_random` | todos os pesos zerados | Embaralha catálogo com `random.Random(seed)`. Exige `seed`. |
| `personalized_id` | apenas no runner de avaliação | Braço determinístico da rodada v4: mesma seleção personalizada com `tie_break="id"`, sem seed. Não é exposto pela API HTTP. |
