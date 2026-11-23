# Documentação do Backend — TCC Roteirização Turística

Este diretório reúne a documentação prática do backend do sistema experimental de
roteirização turística personalizada, desenvolvido como parte do Trabalho de
Conclusão de Curso (TCC).

O sistema é uma API REST que recebe o perfil de interesses de um turista
(pesos por categoria), gera recomendações de atividades turísticas e monta um
roteiro multi-dia respeitando limites de tempo por dia e deslocamentos reais
(calculados via OSRM).

## Índice

| Documento | Conteúdo |
|---|---|
| [01-visao-geral.md](01-visao-geral.md) | O que o sistema faz, visão geral da arquitetura e dos serviços |
| [02-instalacao-e-execucao.md](02-instalacao-e-execucao.md) | Requisitos, configuração e como executar o sistema (Docker Compose) |
| [03-api.md](03-api.md) | Endpoints da API, exemplos de requisição e resposta |
| [04-arquitetura-e-modulos.md](04-arquitetura-e-modulos.md) | Camadas, módulos de domínio e fluxo de execução |
| [05-banco-de-dados.md](05-banco-de-dados.md) | Modelo de dados, migrações (Alembic) e restauração do estado atual do banco |
| [06-testes.md](06-testes.md) | Como executar a suíte de testes (pytest) |
| [07-experimento-e-avaliacao.md](07-experimento-e-avaliacao.md) | CLI de avaliação, cenários, perfis e métricas do experimento |
| [08-estrutura-de-arquivos.md](08-estrutura-de-arquivos.md) | Mapa completo da estrutura de diretórios do backend |

## Execução rápida (resumo)

```bash
cd backend
cp .env.example .env
docker-compose up --build
```

A API fica disponível em `http://localhost:8000/api/v1/health/`.

Documentação interativa (Swagger): `http://localhost:8000/docs`

## Stack

- **Python 3.11+** / FastAPI (API REST)
- **PostgreSQL 15** (catálogo de atividades)
- **SQLAlchemy 2.0 síncrono** + **Alembic** (migrações)
- **Pydantic v2** (validação de contratos de entrada/saída)
- **OSRM** (`osrm-routed`, algoritmo MLD) (matrizes de distância/duração reais)
- **pytest** (testes unitários, de integração e de API)
