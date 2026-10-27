# ATP05 – Melhorias na Pipeline de Dados (PDS / pandas)

Artefatos: `src/pds/pipeline.py` (entrega), `analysis/eda.py` (2.1), `analysis/check_merge_commits.py`,
`analysis/windows_experiment.py` (2.3/2.4), resultados em `analysis/out/windows_summary.csv`.

## 2.1 Análise exploratória (`v2_3_1_trf_dataset.csv`, 1402 linhas)

- Não há valores nulos nem caminhos duplicados.
- **Rótulo quase 50/50: 52,1% dos arquivos com bug.** Em datasets de defeitos o comum é 10–30%, o que indica rótulo inflado.
- As métricas são muito assimétricas (skew > 3 em LOC, CYC, AMC, NER e NEH). Só APF e MAD têm distribuição próxima da normal.
- Há redundância forte (Spearman ≥ 0,8) entre LOC, BLK, COM, NOF e CYC; BLK×LOC chega a 0,96. As métricas mais associadas a BUG são LOC e CYC (0,49).
- Arquivos com bug são maiores e mais complexos. Medianas sem bug × com bug: LOC 79 × 303; CYC 4 × 22.
- **74% das linhas (1037) são testes**, e 92 arquivos estão fora do pacote (`asv_bench`, `scripts`, `web`, `setup.py`). Há também 39 `__init__.py` sem nenhuma função ou classe.
- **Inconsistência:** o `pipeline.py` fornecido já filtrava `/pandas/tests/`, mas o CSV fornecido contém 1024 arquivos de `pandas/tests`. O CSV foi gerado por uma versão anterior do filtro.

## 2.2 Tratamento dos dados

Mudanças em `tansform_raw_dataset`:

| Regra | Justificativa |
|---|---|
| Manter só `./pandas/pandas/` | `doc`, `asv_bench`, `scripts`, `web`, `ci`, `tooling` e `typings` não fazem parte da biblioteca distribuída |
| Remover testes (`tests/`, `test_*.py`, `*_test.py`, `conftest.py`) | Quase todo PR de bug-fix adiciona um teste de regressão, então testes recebem BUG=1 sem serem defeituosos |
| Remover infraestrutura de testes (`_testing/`, `testing.py`, `util/_tester.py`, `util/_test_decorators.py`) | Mesmo motivo da regra anterior |
| Remover código gerado ou vendorizado (`_version.py`, `util/version/`) | Não é mantido pelo projeto |
| Manter `__init__.py` só se tiver função ou classe (NOF > 0 ou NOC > 0) | Os demais só reexportam nomes e têm métricas praticamente nulas |
| `LOC > 0` e remoção de duplicados | Herdado do código original e mantido |
| **Outliers mantidos** | `core/frame.py`, `core/generic.py` etc. são o núcleo do pacote e os arquivos mais propensos a defeitos. A assimetria deve ser tratada na modelagem (ex.: log), sem descartar dados |

Correções na rotulagem, também em `pipeline.py`:

1. **`is:merged`** na busca: PRs fechados sem merge não corrigem nada.
2. **Commits de merge descartados** (mais de um pai): o diff de *"Merge branch 'main' into …"* traz mudanças de terceiros. Em uma amostra de 8 PRs de bug-fix, 3 tinham esse tipo de commit (`check_merge_commits.py`).
3. **Caminhos normalizados** (`\` → `/`): no Windows, nenhum arquivo casava com os caminhos da API e todos ficavam com BUG=0.
4. Token opcional nos headers e parâmetro `window` em `extract_post_release_timeline`.

Efeito no CSV fornecido: 1402 → 245 linhas. O rótulo antigo (52,1% com bug) passa a 81,6% de bug no código de produção. Isso confirma que esse rótulo estava contaminado pela janela longa e pelos commits de merge, e motivou a Seção 2.3.

## 2.3 Janelas de coleta

- `extract_post_release_timeline(releases, delta, window)`: a release alvo é `releases[delta]`; a janela vai da data dessa release até a data de `releases[delta - window]`.
- O comportamento original equivale a `window = delta`.
- Geramos **36 datasets**: `delta` de 1 a 8 (alvos de `v3.0.6` até `v2.3.3`) × `window` de 1 a `delta`, todos com o novo tratamento.
- Coleta: 800 PRs de bug-fix (label `Bug`, merged), dos quais 789 (98,6%) foram mapeados para seus commits.

## 2.4 Impacto (extrato de `windows_summary.csv`)

| alvo | fim da janela | dias | PRs | linhas | % bug (antigo trat.) | % bug (novo) | ROC-AUC | MCC |
|---|---|---|---|---|---|---|---|---|
| v3.0.0 | v3.0.1 | 27 | 26 | 243 | 3,1 | 8,6 | 0,800 | 0,148 |
| v3.0.0 | v3.0.2 | 68 | 61 | 243 | 6,2 | 14,4 | 0,856 | 0,454 |
| v3.0.0 | v3.0.3 | 110 | 122 | 243 | 12,6 | 24,3 | 0,852 | 0,588 |
| **v3.0.0** | **v3.0.4** | **158** | **173** | **243** | **15,2** | **26,7** | **0,857** | **0,604** |
| v3.0.0 | v3.0.5 | 182 | 273 | 243 | 20,5 | 32,5 | 0,860 | 0,542 |
| v3.0.0 | v3.1.0 (original) | 274 | 765 | 243 | 38,1 | 57,6 | 0,863 | 0,582 |
| v3.0.2 | v3.0.4 | 90 | 114 | 243 | 12,2 | 22,6 | 0,888 | 0,580 |
| v3.0.5 | v3.1.0 (delta=2 padrão) | 92 | 493 | 243 | 30,6 | 51,0 | 0,839 | 0,511 |

Na tabela, "% bug (antigo trat.)" é a proporção com o tratamento original, que inclui os testes.

Observações:

- **Quantidade de registros:** praticamente constante entre as janelas (~1514 brutos, 243–245 após o tratamento). A janela muda o **rótulo**, não o volume.
- **Proporção de bug:** cresce de forma monotônica com o tamanho da janela.
  - Janelas que terminam na `v3.1.0` passam de 50% (só nos 35 dias antes dela houve 244 PRs de bug, em sua maioria corrigindo regressões da 3.1 em desenvolvimento).
  - Janelas de 1 release ficam entre ~9% e 18%, a maioria abaixo de 10%: poucos positivos (21–43) e MCC baixo na maior parte delas.
- **ROC-AUC alto nas janelas grandes é enganoso:** com mais de 50% de positivos, o modelo basicamente aprende "arquivo grande = bug" (viés de tamanho).
- Modelo usado na avaliação: RandomForest balanceado, validação cruzada estratificada 5×3.

### Escolha do dataset: `v3.0.0` com janela até `v3.0.4` (`delta=7`, `window=4`)

1. Proporção de bug realista: 26,7% (faixa de 15–30%), com 65 positivos.
2. **Maior MCC (0,604)** entre todas as janelas nessa faixa; ROC-AUC 0,857.
3. Coerência conceitual: `v3.0.1`–`v3.0.4` são as releases de correção da `v3.0.0` (release major), então os bugs corrigidos nesse intervalo são, em grande parte, defeitos da release alvo.

> Observação: `delta` é relativo à lista de releases. Se houver uma nova release, `delta=7` deixa de apontar para a `v3.0.0`.
> O experimento usa o git local para mapear PR → arquivos (o pandas usa *squash merge*); o `pipeline.py` usa a API. Diferenças pequenas entre os dois são esperadas.
