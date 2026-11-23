# Experimento e avaliação

A avaliação do TCC é executada pela CLI `backend/scripts/run_evaluation.py`,
que usa o módulo `app/modules/evaluation`. O desenho atual (v4, catálogo de
142 atividades) roda **61 execuções por combinação** de cenário × perfil:
30 personalizadas com desempate aleatório + 1 braço `personalized_id` + 30
repetições baseline. Total: **3 × 4 × 61 = 732 execuções**.

O desenho histórico de 132 atividades rodava **31 execuções por combinação**
(1 personalizada + 30 baseline), total **372**.

## Comando

Rodada v4 oficial (142 atividades):

```bash
cd backend
python scripts/run_evaluation.py \
  --base-seed 1000 \
  --output-dir experiments/official-v4-142-732 \
  --reference-lat -5.873350031512726 \
  --reference-lon -35.180663304041595 \
  --matrix-path artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json \
  --tie-break both \
  --personalized-repetitions 30
```

> Sem `--allow-overwrite`, a CLI recusa sobrescrever um diretório existente.
> Para reproduzir sem alterar o resultado histórico, use outro `--output-dir`.
>
> O resultado histórico `official-v4-142-732` registra `tie_break: "random"` e
> inclui o braço `personalized_id` (foi gerado com `include_id_arm=True`). A
> CLI grava `tie_break: "both"` para o mesmo plano; as execuções e os demais
> metadados são equivalentes.
>
> Para comparar, use as execuções (`run_id`, atividades, métricas), não o
> arquivo `results.json` inteiro: `tie_break` e `code_dirty` podem diferir.
> Com a árvore de trabalho suja, `code_dirty` será `true`; faça commit antes
> se precisar de metadados idênticos.

Rodada histórica de 132 (372 execuções):

```bash
python scripts/run_evaluation.py \
  --base-seed 1000 \
  --output-dir experiments/repro-132-372 \
  --reference-lat -5.873350031512726 \
  --reference-lon -35.180663304041595 \
  --matrix-path artefatos/osrm/oficiais/praca-ponta-negra/matriz-combinada.json \
  --tie-break id \
  --personalized-repetitions 1
```

Esse comando exige banco com 132 atividades. O `catalog_hash` gerado será
`5536c882...`, diferente do `47103b8c...` registrado nas rodadas oficiais de
132; os itinerários, porém, são reproduzíveis.

## Parâmetros

| Flag | Obrigatório | Descrição |
|---|---|---|
| `--base-seed` | sim | Semente base das repetições |
| `--output-dir` | sim | Diretório de saída (gera `results.json` e `results.csv`; recusa sobrescrever sem `--allow-overwrite`) |
| `--reference-lat` / `--reference-lon` | sim | Coordenadas do ponto de referência |
| `--osrm-base-url` | não | URL do OSRM (alternativa à var `OSRM_BASE_URL`) |
| `--matrix-path` | não | Matriz combinada pré-calculada (JSON de `RoutingMatrixContract`). Com o ponto oficial, a CLI procura automaticamente a matriz lote16 |
| `--scenario` | não | Execução parcial: `curto`, `medio` ou `longo` |
| `--profile` | não | Execução parcial: `litoral`, `cultural`, `gastronomico`, `diversificado` |
| `--personalized-repetitions` | não | Repetições da personalizada por combinação (padrão: 30) |
| `--tie-break` | não | `random` (padrão), `id` ou `both`. `both` acrescenta o braço `personalized_id` |
| `--allow-overwrite` | não | Permite substituir resultados existentes |

Códigos de saída: `0` = concluído sem falhas; `2` = falha de preparação,
sobrescrita recusada ou execuções com falha.

Contagens no escopo completo:

| Configuração | Por combinação | Total |
|---|---|---|
| `--tie-break random` (padrão), 30 repetições | 30 personalizadas + 30 baseline = 60 | 720 |
| `--tie-break both`, 30 repetições | 30 + 1 `personalized_id` + 30 = 61 | 732 |
| `--tie-break id`, 1 repetição (histórico 132) | 1 personalizada + 30 baseline = 31 | 372 |

## Cenários e perfis oficiais

Cenários (`SCENARIOS`):

| ID | Nome | trip_days | daily_limit_min |
|---|---|---|---|
| `curto` | Curto | 2 | 240 |
| `medio` | Médio | 4 | 360 |
| `longo` | Longo | 7 | 360 |

Perfis oficiais (`official_profiles()`), pesos por categoria
(praia, natureza, gastronomia, cultura_historia, lazer, religioso, compras_artesanato):

| Perfil | Pesos |
|---|---|
| `litoral` | praia 3, natureza 2, gastronomia 1, demais 0 |
| `cultural` | cultura_historia 3, lazer 2, religioso 2, praia/natureza/gastronomia 1, compras 0 |
| `gastronomico` | gastronomia 3, lazer 2, demais 1 |
| `diversificado` | todos com peso 2 |

> **Matriz oficial:** com o ponto de referência oficial
> (`lat=-5.873350031512726`, `lon=-35.180663304041595` — Praça Ponta Negra),
> a CLI usa automaticamente
> `artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json`
> (142 atividades), sem chamar o OSRM.
>
> Para a rodada histórica de 132, passe
> `artefatos/osrm/oficiais/praca-ponta-negra/matriz-combinada.json`.
>
> Com outro ponto de referência, a CLI tenta construir a matriz via OSRM
> `/table`. Com catálogo de 142 isso falha na validação da V2 de 132; use uma
> matriz pré-calculada de 142 ou o catálogo de 132.

## Plano de execução (`build_plan`)

Para cada (cenário × perfil):

- `{cenário}-{perfil}-personalized-01..30` — 30 execuções com
  `tie_break="random"`, sementes `base_seed + 1` a `base_seed + 30`.
- `{cenário}-{perfil}-personalized_id` — 1 execução com `tie_break="id"`,
  sem seed (somente com `--tie-break both`).
- `{cenário}-{perfil}-baseline-01..30` — 30 execuções, sementes
  `base_seed + 1` a `base_seed + 30`.

Total v4: 3 cenários × 4 perfis × 61 = **732 execuções**.

## Métricas

### Por execução

- `inserted_activity_count`: nº de atividades no roteiro.
- `metrics` (resultado da recomendação):
  - `compatibility_media` e `cobertura_interesses` calculados apenas na
    estratégia `personalized`.
  - `null` em `baseline_random` e em `personalized_id`.
- **Temáticas pós-seleção** (`evaluate_itinerary_metrics`), calculadas para
  todas as estratégias com os pesos do perfil:
  - `compatibility_media`: média da compatibilidade das atividades inseridas.
  - `compatibility_media_normalized`: compatibilidade dividida pelo escore
    máximo alcançável do perfil.
  - `cobertura_interesses`: proporção de categorias ativas representadas.
  - `zero_score_inserted_count` / `zero_score_inserted_ratio`: atividades
    inseridas sem nenhuma categoria ativa em comum.
  - `empty_itinerary`, `active_category_count`.
- **Secundárias do roteiro** (`itinerary_metrics`): `total_distance_m`,
  `total_travel_minutes`, `total_visit_minutes`, `total_occupied_minutes`,
  `total_violations` (+ detalhe por dia: ocupação e violações).

### Agregadas por (cenário, perfil, estratégia)

- Estatísticas de distribuição para cada métrica primária e escalar:
  `mean`, `median`, `stddev` (amostral), `q1`, `q3`, `iqr`, `min`, `max`,
  `observation_count`.
- Contadores: `planned_count`, `successful_count`, `failed_count`,
  `evaluation_failed_count`, `empty_itinerary_count`.
- Estratégias `personalized` e `personalized_id` recebem ainda:
  - `p_superiority_<métrica>`: probabilidade empírica de superioridade sobre
    todas as comparações cruzadas com a baseline (A12 de Vargha–Delaney;
    empate conta 0,5). Métricas: `compatibility_media`,
    `compatibility_media_normalized`, `cobertura_interesses`,
    `total_distance_m`, `total_travel_minutes`, `inserted_activity_count`.
  - `baseline_compatibility_media_median` e
    `baseline_cobertura_interesses_median`.
  - `compatibility_media_difference_from_baseline_median` e
    `cobertura_interesses_difference_from_baseline_median`.

### Rastreabilidade (reprodutibilidade)

O relatório registra: `base_seed`, `catalog_hash` (SHA-256 do catálogo
normalizado), `routing_matrix_id` e `routing_matrix_hash` (SHA-256 do arquivo
da matriz, quando usado), `execution_scope`, `tie_break`,
`personalized_repetitions` e versão de código (`code_version` = hash do commit
Git de 40 hex; `code_dirty`; `code_version_source`). Em containers sem `.git`,
defina `GIT_COMMIT` (40 hexadecimais) e, opcionalmente,
`GIT_DIRTY=true|false`; sem identificação comprovável, `code_version` fica
`null`.

Hashes de referência:

| Rodada | Catálogo | `catalog_hash` | Matriz |
|---|---|---|---|
| v4 142/732 | `a3-lotes-02-16-v4.json` | `9b650926...` | lote16 `65150a2f...` |
| lote16 142/372 | dump pré-correção `20261115` | `7a239ba1...` | lote16 `65150a2f...` |
| 132/372 | `a3-lotes-02-15-v2.json` | oficial `47103b8c...`; atual `5536c882...` | `c47a5f33...` |

## Saída

`--output-dir` recebe dois arquivos:

- `results.json` — relatório completo (execuções individuais + agregações).
- `results.csv` — uma linha por execução (colunas fixas em `export_report`).

Status do relatório: `completed` (tudo OK) ou `completed_with_failures`.

## Resultados históricos no repositório

```
backend/experiments/
├── pilot-ifrn-20261109/          # piloto 132 (com validation.json e reproducibility_check.json)
├── official-20261111-372/        # oficial 132 v1
├── official-20261111-372-v2/     # oficial 132 v2
├── official-20261111-372-v3/     # oficial 132 v3
├── official-20261115-lote16/     # 142, catálogo pré-correção, 372 execuções
└── official-v4-142-732/          # v4 atual: 142 atividades, 732 execuções
```

Cada diretório contém `results.json` e `results.csv` (o piloto inclui ainda
artefatos de validação de reprodutibilidade).

## Execução parcial

Para reprocessar só parte do experimento:

```bash
python scripts/run_evaluation.py --base-seed 1000 \
  --output-dir experiments/parcial-curto-litoral \
  --reference-lat -5.873350031512726 --reference-lon -35.180663304041595 \
  --matrix-path artefatos/osrm/oficiais/praca-ponta-negra-lote16/matriz-combinada.json \
  --scenario curto --profile litoral
```

O relatório marca `execution_scope: "partial"` com os filtros usados.
