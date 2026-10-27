"""
Seção 2.1 - Análise Exploratória do dataset v2_3_1_trf_dataset.csv
Uso (a partir de pds-data/):  python analysis/eda.py [caminho_csv]
"""
import sys
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)

path = sys.argv[1] if len(sys.argv) > 1 else "v2_3_1_trf_dataset.csv"
df = pd.read_csv(path, sep=";")
METRICS = ["LOC", "COM", "BLK", "NOF", "NOC", "APF", "AMC", "NER", "NEH", "CYC", "MAD"]


def section(title):
    print("\n" + "=" * 80 + f"\n{title}\n" + "=" * 80)


section("1. Visão geral")
print(f"Linhas: {len(df)} | Colunas: {df.shape[1]}")
print(df.dtypes.to_string())

section("2. Valores faltantes e duplicados")
print("Nulos por coluna:\n", df.isna().sum().to_string())
print("FILE duplicados:", df["FILE"].duplicated().sum())
print("Linhas de métricas idênticas (exceto FILE):", df.duplicated(subset=METRICS + ["BUG"]).sum())

section("3. Distribuição do rótulo BUG")
print(df["BUG"].value_counts().to_string())
print(f"Proporção buggy: {df['BUG'].mean():.2%}")

section("4. Estatísticas descritivas")
print(df[METRICS].describe(percentiles=[.25, .5, .75, .9, .99]).T.round(2))
print("\nAssimetria (skew):\n", df[METRICS].skew().round(2).to_string())

section("5. Média das métricas por classe (BUG)")
print(df.groupby("BUG")[METRICS].median().T.rename(columns={0: "mediana_bug0", 1: "mediana_bug1"}))

section("6. Correlação (Spearman) entre métricas e com BUG")
corr = df[METRICS + ["BUG"]].corr(method="spearman").round(2)
print(corr)
pairs = (corr.where(lambda c: c.abs() >= 0.8).stack().reset_index()
         .query("level_0 < level_1"))
print("\nPares altamente correlacionados (|rho| >= 0.8):\n", pairs.to_string(index=False))

section("7. Composição por diretório (2 primeiros níveis após ./pandas/)")
parts = df["FILE"].str.replace("./pandas/", "", regex=False).str.split("/")
df["TOP"] = parts.apply(lambda p: "/".join(p[:2]) if len(p) > 2 else (p[0] if len(p) > 1 else "<raiz>"))
comp = df.groupby("TOP").agg(arquivos=("BUG", "size"), buggy=("BUG", "sum"))
comp["%buggy"] = (comp["buggy"] / comp["arquivos"] * 100).round(1)
print(comp.sort_values("arquivos", ascending=False).to_string())

section("8. Possíveis inconsistências / ruído")
name = df["FILE"].str.split("/").str[-1]
checks = {
    "arquivos de teste (test_*.py, conftest.py, /tests/)": df["FILE"].str.contains(r"/tests?/|/test_[^/]*\.py$|conftest\.py$"),
    "fora do pacote ./pandas/pandas/": ~df["FILE"].str.startswith("./pandas/pandas/"),
    "__init__.py": name.eq("__init__.py"),
    "__init__.py sem função nem classe": name.eq("__init__.py") & df["NOF"].eq(0) & df["NOC"].eq(0),
    "asv_bench (benchmarks)": df["FILE"].str.contains("/asv_bench/"),
    "scripts/ e web/": df["FILE"].str.contains(r"\./pandas/(scripts|web|ci|doc)/"),
    "NOF==0 e NOC==0 (sem lógica)": df["NOF"].eq(0) & df["NOC"].eq(0),
    "CYC==1 (sem decisões)": df["CYC"].eq(1),
    "_version / versioneer / setup": name.str.contains(r"^(_version|versioneer|setup|generate_)"),
}
for k, mask in checks.items():
    print(f"{k:55s} n={mask.sum():5d}  buggy={df.loc[mask, 'BUG'].sum():4d}")

section("9. Outliers (IQR, 1.5x) por métrica")
for m in METRICS:
    q1, q3 = df[m].quantile([.25, .75])
    iqr = q3 - q1
    out = ((df[m] < q1 - 1.5 * iqr) | (df[m] > q3 + 1.5 * iqr)).sum()
    print(f"{m}: {out} outliers")
print("\nTop 10 maiores arquivos (LOC):")
print(df.nlargest(10, "LOC")[["FILE", "LOC", "CYC", "BUG"]].to_string(index=False))
