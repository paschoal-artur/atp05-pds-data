# Módulo `pds-data` — Extração e Tratamento de Métricas de Código

Pacote responsável por extrair métricas estáticas de código Python ([`pymetrix.py`](./src/pds/pymetrix.py)) e construir datasets rotulados para Predição de Defeitos de Software ([`pipeline.py`](./src/pds/pipeline.py)) a partir do histórico de releases e Pull Requests do projeto [Pandas](https://github.com/pandas-dev/pandas).

## Estrutura do Pacote

```text
pds-data
├── src/pds/
│   ├── __init__.py
│   ├── pipeline.py
│   └── pymetrix.py
├── analysis/
│   ├── eda.py
│   ├── check_merge_commits.py
│   ├── windows_experiment.py
│   └── RELATORIO.md
├── pyproject.toml
└── README.md
```

## Esquema do Dataset

| Campo | Descrição |
|---|---|
| `FILE` | Caminho do arquivo `.py` analisado |
| `LOC` | Lines of Code (linhas de código não vazias) |
| `COM` | Lines of Comments (linhas de comentário) |
| `BLK` | Lines of Blank (linhas em branco) |
| `NOF` | Number of Functions (número de funções) |
| `NOC` | Number of Classes (número de classes) |
| `APF` | Average Parameters per Function (média de parâmetros por função) |
| `AMC` | Average Methods per Class (média de métodos por classe) |
| `NER` | Number of Exception Raises (`raise`) |
| `NEH` | Number of Exception Handlers (`except`) |
| `CYC` | Cyclomatic Complexity (complexidade ciclomática de McCabe) |
| `MAD` | Max AST Depth (profundidade máxima da AST) |
| `BUG` | Rótulo alvo: `1` (defeituoso) ou `0` (não defeituoso) |

## Execução

```bash
poetry install
poetry run python -u -m pds.pipeline <GITHUB_TOKEN>
```
