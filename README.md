# Pipeline de Dados para Predição de Defeitos de Software (PDS) — Pandas

Este repositório apresenta a implementação e o estudo experimental de melhorias em uma pipeline automatizada de extração, rotulagem e tratamento de métricas estáticas de código para **Predição de Defeitos de Software (PDS)** aplicada ao repositório oficial do pacote [`pandas-dev/pandas`](https://github.com/pandas-dev/pandas).

---

## 📁 Estrutura do Repositório

```text
├── pds-data/
│   ├── src/pds/
│   │   ├── pipeline.py              # Pipeline principal (extração via GitHub API, rotulagem e tratamento)
│   │   └── pymetrix.py              # Extrator de métricas estáticas via AST
│   ├── analysis/
│   │   ├── eda.py                   # Análise Exploratória de Dados (EDA)
│   │   ├── check_merge_commits.py   # Verificação empírica de contaminação por commits de merge
│   │   ├── windows_experiment.py    # Experimento com 36 janelas temporais de coleta e validação ML
│   │   ├── RELATORIO.md             # Relatório técnico completo dos experimentos
│   │   └── out/                     # Datasets das 36 janelas e tabela consolidada (windows_summary.csv)
│   ├── v3_0_0_raw_dataset.csv       # Dataset bruto gerado pela pipeline na janela ótima (1.511 arquivos)
│   ├── v3_0_0_trf_dataset.csv       # Dataset final tratado na janela ótima (243 arquivos)
│   └── pyproject.toml
└── README.md
```

---

## 🔍 1. Diagnóstico Inicial (Análise Exploratória)

A análise exploratória ([`pds-data/analysis/eda.py`](./pds-data/analysis/eda.py)) sobre o dataset de referência inicial (`v2_3_1_trf_dataset.csv`, 1.402 registros) revelou quatro problemas críticos para a tarefa de PDS:

1. **Contaminação por arquivos de teste e utilitários externos:** 74% dos registros (1.037 arquivos) pertenciam a diretórios de testes (`/tests/`, `test_*.py`, `conftest.py`) e outros 92 arquivos estavam fora do pacote distribuído (`asv_bench/`, `scripts/`, `web/`, `setup.py`). Como todo PR de correção de bug adiciona testes de regressão nos arquivos de teste, esses arquivos recebiam rótulo `BUG=1` sem representarem código de produção defeituoso.
2. **Arquivos sem lógica (`__init__.py`):** 39 dos 52 arquivos `__init__.py` possuíam `NOF=0` e `NOC=0` (apenas reexportação de símbolos), adicionando ruído com métricas zeradas.
3. **Inflação do rótulo (`BUG=1`):** A proporção de arquivos defeituosos chegava a **52,1%** no dataset geral e a **81,6%** quando restrita ao código de produção (`pandas/core`, `pandas/io`, `pandas/plotting`), muito acima da faixa típica reportada na literatura de PDS (10% a 30%).
4. **Falsos positivos na extração de commits:** A coleta incluía PRs fechados sem merge (`state:closed` em vez de `is:merged`) e commits de merge internos (`Merge branch 'main' into ...`), cujos diffs traziam arquivos alterados por terceiros na branch principal.

---

## 🛠️ 2. Melhorias Implementadas na Pipeline ([`pipeline.py`](./pds-data/src/pds/pipeline.py))

### 2.1. Saneamento da Extração e Rotulagem
- **Apenas PRs integrados (`is:merged`):** Garante que PRs recusados/abandonados não rotulem arquivos como defeituosos.
- **Exclusão de commits de merge (`len(parents) > 1`):** Evita que sincronizações com a branch `main` contaminem os arquivos de um PR de bug-fix.
- **Normalização multiplataforma de caminhos:** Conversão de separadores `\` para `/` antes do cruzamento com os caminhos retornados pela GitHub API.
- **Janela temporal parametrizável (`delta` e `window`):** Desacopla a escolha da release alvo (`releases[delta]`) da duração da janela de coleta de correções pós-lançamento (`releases[delta - window]`).

### 2.2. Tratamento e Filtragem do Dataset (`tansform_raw_dataset`)
- **Escopo estrito ao pacote de produção:** Mantém exclusivamente arquivos sob `./pandas/pandas/`.
- **Remoção completa de suítes e infraestrutura de testes:** Filtra `/tests/`, `test_*.py`, `*_test.py`, `conftest.py`, além de `pandas/_testing/`, `pandas/testing.py`, `util/_tester.py` e `util/_test_decorators.py`.
- **Remoção de código gerado ou vendorizado:** Filtra `pandas/_version.py` e `pandas/util/version/`.
- **Filtragem semântica de `__init__.py`:** Preserva arquivos `__init__.py` apenas quando contêm implementação real (`NOF > 0` ou `NOC > 0`).
- **Preservação de outliers reais:** Arquivos centrais do pacote (`core/generic.py`, `core/frame.py`, `core/series.py`) apresentam valores extremos de `LOC` e `CYC`, mas constituem exatamente os módulos críticos de interesse para predição de defeitos.

---

## 📊 3. Experimento de Janelas Temporais e Seleção do Dataset

Foram gerados e avaliados **36 datasets** combinando 8 releases alvo (`delta` de 1 a 8, cobrindo `v2.3.3` a `v3.0.6`) e diferentes durações de janela pós-release (`window` de 1 até `delta`). Para cada recorte, avaliou-se o balanceamento de classes e o desempenho preditivo em validação cruzada estratificada 5×3 com `RandomForestClassifier` ([`windows_summary.csv`](./pds-data/analysis/out/windows_summary.csv)):

| Release Alvo | Fim da Janela | `(delta, window)` | Dias | PRs Bug-Fix | Arquivos (trf) | % Buggy | ROC-AUC | PR-AUC | F1 | MCC |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `v3.0.0` | `v3.0.1` | `(7, 1)` | 27 | 26 | 243 | 8,6% | 0,800 | 0,362 | 0,204 | 0,148 |
| `v3.0.0` | `v3.0.2` | `(7, 2)` | 68 | 61 | 243 | 14,4% | 0,856 | 0,552 | 0,530 | 0,454 |
| `v3.0.0` | `v3.0.3` | `(7, 3)` | 110 | 122 | 243 | 24,3% | 0,852 | 0,741 | 0,687 | 0,588 |
| **`v3.0.0`** | **`v3.0.4`** | **`(7, 4)`** | **158** | **173** | **243** | **26,7%** | **0,857** | **0,730** | **0,707** | **0,604** |
| `v3.0.0` | `v3.0.5` | `(7, 5)` | 182 | 273 | 243 | 32,5% | 0,860 | 0,786 | 0,688 | 0,542 |
| `v3.0.0` | `v3.1.0` | `(7, 7)` | 274 | 765 | 243 | 57,6% | 0,863 | 0,913 | 0,806 | 0,582 |
| `v3.0.2` | `v3.0.4` | `(5, 2)` | 90 | 114 | 243 | 22,6% | 0,888 | 0,759 | 0,670 | 0,580 |
| `v3.0.5` | `v3.1.0` | `(2, 2)` | 92 | 493 | 243 | 51,0% | 0,839 | 0,875 | 0,747 | 0,511 |

### Conclusão e Configuração Final
- **Janela selecionada:** `delta=7, window=4` (release alvo **`v3.0.0`** com coleta de bug-fixes até **`v3.0.4`**).
- **Justificativa:** Apresenta proporção de defeitos realista (**27,2%** na execução via API — 66 arquivos defeituosos em 243 arquivos do pacote), atinge o **maior Coeficiente de Correlação de Matthews (`MCC = 0,604`)** dentro da faixa saudável de balanceamento (15%–30%) e possui coerência de ciclo de vida (compreende as releases de patch `v3.0.1` a `v3.0.4` dedicadas a estabilizar a release major `v3.0.0`, sem misturar bugs introduzidos no desenvolvimento da série `3.1.x`).

---

## ▶️ Como Executar

```bash
cd pds-data
poetry install
poetry run python -u -m pds.pipeline <GITHUB_TOKEN>
```
