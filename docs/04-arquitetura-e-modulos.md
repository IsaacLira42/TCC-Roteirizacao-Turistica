# Arquitetura e módulos

## Padrão geral

Arquitetura em camadas, com módulos de domínio autocontidos em
`app/modules/`:

```
app/
├── main.py               # cria FastAPI e inclui o router v1
├── api/v1/router.py      # agrega routers de health, activities e recommendations
├── core/
│   ├── config.py         # Settings (pydantic-settings, lê .env)
│   ├── database.py       # DATABASE_URL, engine, SessionLocal, Base
│   └── exceptions.py     # reservado para exceções de domínio
└── modules/
    ├── activities/       # CRUD do catálogo (endpoints, service, repository, models, schemas, importer)
    ├── preferences/      # CategoryWeights (validação de pesos por categoria)
    ├── recommendations/  # orquestração da seleção (endpoints, service, schemas)
    ├── itineraries/      # heurística gulosa de montagem dos dias
    ├── routing/          # matriz V2 + OSRM /table → RoutingMatrixContract
    └── evaluation/       # runner do experimento, agregações e exportação
```

Estilo da camada por módulo (exemplo em `activities`):

- **endpoints.py** — rotas FastAPI, dependências (`Depends`) e serialização.
- **service.py** — regras de negócio, levanta `HTTPException` quando preciso.
- **repository.py** — acesso a dados via SQLAlchemy (`select`, `session.add/commit`).
- **models.py** — modelo ORM (tabela `activities`).
- **schemas.py** — schemas Pydantic de entrada/saída (`ActivityCreate`, `ActivityRead`, `ActivityUpdate`).
- **importer.py** — importação do arquivo A3 para o banco.

## Módulos de domínio

### `preferences`

Define a **taxonomia experimental de 7 categorias** (ordem fixa):
`praia`, `natureza`, `gastronomia`, `cultura_historia`, `lazer`, `religioso`,
`compras_artesanato`.

`CategoryWeights` (Pydantic, `strict`, `extra: forbid`):
- 7 campos obrigatórios, inteiros 0–3, sem padrão.
- `categorias_ativas`: lista de categorias com peso > 0.
- `todos_zerados`: `True` quando os 7 pesos = 0 (dispara a baseline).

### `routing`

Responsável pelo deslocamento real entre pontos.

- **Matriz V2** (`artefatos/osrm/referencias/matriz_a3-lotes-02-15-v2.json`):
  132×132, rótulos `a0`..`a131`, na ordem de `registros[]` do catálogo
  `artefatos/a3-lotes-02-15-v2.json`. Distância em **metros**; duração em
  **segundos**. É a matriz usada pela API HTTP.
- **Matriz combinada lote16**
  (`artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json`):
  142 atividades + ponto de referência. Usada pela rodada v4 via
  `--matrix-path`; não é usada pela API.
- **`RoutingService.build_matrix_contract(reference_point, activities)`**:
  monta o `RoutingMatrixContract` do subconjunto pedido — matriz
  atividade→atividade vem da V2; pernas envolvendo a referência (`ref`) são
  consultadas no OSRM `/table` (`OSRM_BASE_URL`), com 3 tentativas e
  backoff (1s, 2s).
- **`RoutingMatrixContract`** (dataclass congelado, validado em `__post_init__`):
  `distance_matrix`, `duration_matrix`, `activity_id_to_label`,
  `label_to_activity_id`, `reference_label="ref"`. Valida ordem, duplicidade e
  inversão dos mapas — qualquer divergência levanta `ValueError`.

> **Limitação:** `build_matrix_contract` valida os IDs contra a V2 de 132.
> Com catálogo de 142, os IDs `atividade_0001`..`atividade_0010` não existem
> na V2 e o endpoint retorna 503. A rodada v4 contorna isso usando a matriz
> lote16 pré-calculada no runner.

### `recommendations`

Orquestra a geração:

1. Normaliza cada atividade (`_activity_dict`) para o contrato de domínio
   (decodifica `categories` de string JSON/comma para lista).
2. **Compatibilidade** (`calcular_compatibilidade`):
   `soma(pesos das categorias da atividade ∩ ativas) / soma(pesos ativos)`.
   Retorna `None` quando não há categoria ativa.
3. **Escolha de estratégia** (`execute_recommendation`):
   - `personalized`: ordena por compatibilidade decrescente e resolve empates
     com `tie_break="id"` (padrão) ou `tie_break="random"` (exige `seed`);
     calcula `compatibility_media` e `cobertura_interesses`.
   - `baseline_random`: exige `seed`; embaralha com `random.Random(seed)`.
   - `personalized_id`: braço exclusivo do runner de avaliação, com
     `tie_break="id"` e sem seed.
4. Delega a montagem dos dias ao módulo `itineraries`.

### `itineraries`

`ItinerariesService.build_itinerary` — **heurística gulosa**, independente de
HTTP/OSRM (recebe apenas o `RoutingMatrixContract`):

1. **Elegibilidade:** descarta candidaturas com duração inválida
   (`invalid_duration`) antes da seleção.
2. Para cada candidato (na ordem recebida), testa **inserção em todos os dias
   e todas as posições**:
   - `evaluate(sequence)` soma, perna a perna: distância, minutos de
     deslocamento (duração OSRM/60) e minutos de visita (média entre
     `duration_estimated_min` e `max`). Falta de perna (`None`) → sequência
     inviável.
   - Sequência válida só é opção se `total_minutes <= daily_limit_min`.
   - Custo de escolha: `(distância marginal, -minutos restantes, dia, posição)`
     — escolhe `min` (menor distância marginal; desempate por mais tempo
     restante).
3. Sem opção viável → `excluded_activities` com motivo
   (`no_viable_route` ou `daily_limit_exceeded`).
4. Gera `itinerary_metrics` por dia (`summarize_metrics`): distância,
   minutos de deslocamento/visita, ocupação (`total/limite`) e
   `limit_violations` (dia final ativo acima do limite).

O tempo usado contra o limite diário inclui a **ida do ponto de referência
à primeira atividade** de cada dia.

### `evaluation`

Infraestrutura do experimento (não exposta via HTTP; usada pela CLI
`scripts/run_evaluation.py` — ver `07-experimento-e-avaliacao.md`):
cenários/perfis oficiais, plano de execuções (personalizada, braço
`personalized_id` e baseline), `EvaluationRunner`, métricas temáticas
pós-seleção (compatibilidade, compatibilidade normalizada, cobertura,
`zero_score_*`), agregações estatísticas (média, mediana, desvio-padrão,
quartis, IQR, min, max), probabilidade de superioridade
(`p_superiority_*`) e exportação `results.json`/`results.csv`.

## Fluxo detalhado do endpoint /recommendations

```
endpoints.get_recommendations
  ├── validar payload (RecommendationInput → CategoryWeights)
  ├── exigir seed se todos os pesos = 0 ou tie_break="random" (422)
  ├── ActivityService.list_activities(limit=500)     # catálogo do banco
  ├── RoutingService.build_matrix_contract(ref, cat) # V2 132 + OSRM /table
  └── execute_recommendation(...)                    # estratégia + heurística
        ├── personalized → ordenar por compatibilidade → build_itinerary
        └── baseline_random → shuffle(seed)            → build_itinerary
```

Erros de OSRM/matrizes (`RuntimeError`, `ValueError`) são convertidos em **503**.
