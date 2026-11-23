# Relatório de validação — Matriz OSRM a3-lotes-02-15

## Configuração

- **PBF:** `rio-grande-do-norte.pbf` (OpenStreetMap, extraído com perfil `car.lua`)
- **Algoritmo de roteamento:** MLD (Multi-Level Dijkstra)
- **Pontos:** 132 atividades do artefato `a3-lotes-02-15.json`
- **Gerado em:** 2026-11-08 (ver timestamp do JSON)
- **Servidor:** `osrm/osrm-backend:v5.26.0`, `--max-table-size 200`

## Validação interna (matriz v2)

| Métrica | Valor |
|---|---|
| Dimensão | 132 × 132 |
| Diagonal zero | ✅ sim |
| Valores nulos | 0 |
| Distância mínima entre pontos distintos | 5,4 m |
| Distância máxima | 40.186,3 m |
| Distância média | 12.011 m |
| Duração mínima | 0,6 s |
| Duração máxima | 2.666,9 s |
| Duração média | 839 s |
| Assimetria máxima (ida vs. volta) | 6.430,2 m |

## Snaps com distância > 80 m

Após a análise de snap, 5 pontos apresentaram distância superior a 80 m entre a coordenada original e a via veicular mais próxima:

| Índice | Distância | Via de snap | Justificativa |
|---|---|---|---|
| 2 | 130 m | Rodovia Monsenhor Francisco de Assis Pereira | Atração rural (Mártires de Uruaçu, SGA) — acesso pela rodovia é o ponto correto |
| 92 | 122 m | Rodovia Monsenhor Francisco de Assis Pereira | Idem (Capela dos Mártires, SGA) |
| 107 | 164 m | Rua das Embarcações | Ponto em Parnamirim; verificar se é acesso de condomínio |
| 113 | 83 m | Avenida Benivaldo Azevedo da Mata | Área de lazer; já na via de acesso |
| 116 | 82 m | (sem nome) | Estádio Maria Lamas Farache; acesso por via sem nome é plausível |

Esses pontos foram mantidos com a coordenada original por representarem corretamente o acesso veicular.

## Normalização de coordenadas para acesso veicular

Sete das 132 atividades (índices **31, 33, 39, 40, 58, 59, 60**) tinham coordenadas originais em locais sem via veicular mapeada no OpenStreetMap — praias, dunas e interior de fortaleza. Para esses, o OSRM realizou snap automático para o acesso veicular mais próximo, com distância variando de 100 a 522 m.

### Achado metodológico

Como o OSRM calcula rotas **a partir do ponto snapado**, a matriz v1 (coordenadas originais) **já refletia, na prática, o acesso veicular**. A versão v2 do artefato substitui as coordenadas originais pelas coordenadas do snap, **tornando essa escolha explícita no dado de entrada** e eliminando a ambiguidade entre "coordenada da atração" e "ponto de roteamento".

**As matrizes v1 e v2 são numericamente equivalentes** (verificado por `diff` direto dos arrays `.distances` — resultado vazio). Isso confirma que o OSRM já operava sobre o acesso veicular e que a normalização apenas explicitou essa decisão.

### Implicação para o TCC

A normalização é metodologicamente relevante porque documenta que o modelo de roteirização adotado é baseado em **rede viária**, e **não modela deslocamento a pé** entre o estacionamento e a atração. Estudos que necessitem de tempo porta-a-porta devem complementar a matriz com estimativas de caminhada.

A matriz v2 é adotada como **artefato oficial** do trabalho.

## Arquivos gerados

- `matriz_a3-lotes-02-15.json` — matriz v1 (coordenadas originais)
- `matriz_a3-lotes-02-15-v2.json` — matriz v2 (7 pontos normalizados) ✅ **oficial**
- `matriz_a3-lotes-02-15-v2_distancias.txt` — distâncias formatadas
- `matriz_a3-lotes-02-15-v2_duracoes.txt` — durações formatadas
