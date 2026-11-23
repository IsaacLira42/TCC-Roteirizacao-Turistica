# Visualizador geográfico das atividades do catálogo

Ferramenta local e independente que consulta a tabela `activities` do banco
PostgreSQL do projeto e gera um **mapa interativo (HTML autônomo)** com a
distribuição geográfica das atividades por município. Feita para produzir e
conferir a Figura 5 do Capítulo 4 do TCC.

Não faz parte da API de recomendação e **não altera** artefatos oficiais
(catálogo congelado, matriz de distâncias, resultados das 372 execuções).

## Tecnologias

- Python 3.11+ (desenvolvido em 3.13)
- [Folium](https://python-visualization.com/folium/) — mapa interativo
- [Esri Light Gray Canvas](https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer) — camada-base clara e limpa (`folium.TileLayer`, attr "Tiles © Esri")
- [SQLAlchemy](https://www.sqlalchemy.org) + `psycopg2-binary` — acesso ao banco
- [pytest](https://pytest.org) — testes

## Pré-requisitos

1. Container `db` do backend em execução:

   ```bash
   cd backend
   docker compose up -d db
   ```

2. Python com venv próprio:

   ```bash
   cd tools/map_viewer
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

## Configuração da conexão com o banco

A ferramenta lê as mesmas variáveis do `docker-compose.yml` do backend
(`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`,
`POSTGRES_PORT`). Rodando na máquina host, basta exportar:

```bash
export POSTGRES_HOST=localhost POSTGRES_PORT=5432 \
       POSTGRES_DB=turisticas POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres
```

Os padrões coincidem com os valores do Compose; nenhuma credencial está
escrita no código.

## Execução

```bash
cd tools/map_viewer
.venv/bin/python -m map_viewer
```

O comando informa: total de registros consultados, quantidade com
coordenadas válidas, quantidade ignorada por coordenada inválida e o
caminho do HTML gerado. Em caso de banco indisponível, mostra uma mensagem
de erro clara (exit code 1), sem stack trace.

Para outro caminho de saída:

```bash
.venv/bin/python -m map_viewer -o output/outra_figura.html
```

## Saída

`tools/map_viewer/output/mapa_atividades.html` — abre direto no navegador,
sem necessidade da API FastAPI. O diretório de saída é criado
automaticamente e não entra no controle de versão (ver `.gitignore`).

## Como interpretar

- Cada ponto colorido é uma atividade do banco, desenhado como
  `CircleMarker` de raio 3, **sempre individual em qualquer nível de zoom**
  (sem agrupamento `MarkerCluster`, sem alfinetes padrão).
- Clique no ponto para o **popup** com: nome, identificador
  (`atividade_XXXX`), município, latitude e longitude.
- A cor identifica o **município** (paleta fixa por execução).
- A categoria **“(sem município)”** (cinza) cobre registros com `city`
  vazio ou `N/A` — **não** são atribuídos a Natal, mesmo com coordenadas
  dentro do município (3 registros do catálogo: `atividade_0044`,
  `atividade_0051`, `atividade_0070`).
- A **legenda** no canto inferior esquerdo lista os municípios com as
  respectivas cores e quantidades, além do total de pontos exibidos.

## Testes

```bash
cd tools/map_viewer
.venv/bin/python -m pytest tests/ -q
```

Os testes usam apenas dados sintéticos; a execução normal consulta o banco
real.

## Estrutura

```
tools/map_viewer/
├── map_viewer/
│   ├── __init__.py       # exports
│   ├── __main__.py       # python -m map_viewer
│   ├── cli.py            # argparse, mensagens e exit codes
│   ├── config.py         # variáveis POSTGRES_* → DatabaseConfig
│   ├── data.py           # consulta SQL, validação de coordenadas, município
│   └── build.py          # mapa Folium: marcadores, cluster, popups, legenda
├── tests/
│   └── test_map_viewer.py
├── requirements.txt
├── .gitignore
└── README.md
```
