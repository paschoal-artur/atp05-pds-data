"""
Seções 2.3 e 2.4 - Datasets com diferentes janelas de coleta e avaliação do impacto.

Para cada combinação (delta, window):
    release alvo  = releases[delta]
    início        = data de publicação da release alvo
    fim           = data de publicação de releases[delta - window]
(window = delta reproduz o comportamento original: janela até a última release.)

Coleta (sem precisar de token):
  * Releases e PRs de bug-fix (label "Bug", merged) via GitHub REST/Search API.
  * Arquivos alterados por PR via repositório git local: o pandas usa "squash merge", então cada
    PR vira um único commit "... (#NNNN)" nas branches remotas, cujo diff é o diff líquido do
    PR (equivalente ao filtro de commits de merge aplicado em pipeline.py).
  * Métricas via pds.pymetrix na tag da release alvo; tratamento via pipeline.tansform_raw_dataset.

Saídas em analysis/out/: datasets por janela (raw/trf), windows_summary.csv e windows_summary.md.
Uso (a partir de pds-data/):  python analysis/windows_experiment.py [max_delta]
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from pds import pipeline, pymetrix  # noqa: E402

OWNER, REPO = "pandas-dev", "pandas"
OUT = os.path.join("analysis", "out")
WIN_OUT = os.path.join(OUT, "windows")
os.makedirs(WIN_OUT, exist_ok=True)
H = {"Accept": "application/vnd.github+json"}
if os.environ.get("GITHUB_TOKEN"):
    H["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
MAX_DELTA = int(sys.argv[1]) if len(sys.argv) > 1 else 8
FIELDS = ['FILE', 'LOC', 'COM', 'BLK', 'NOF', 'NOC', 'APF', 'AMC', 'NER', 'NEH', 'CYC', 'MAD', 'BUG']
METRICS = FIELDS[1:-1]


def cached(path, fn):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    data = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return data


# ----------------------------------------------------------------------------- releases
releases = cached(os.path.join(OUT, "releases.json"),
                  lambda: pipeline.extract_releases_matching_semantic_versioning(
                      github_token=os.environ.get("GITHUB_TOKEN"), github_owner=OWNER, github_repository=REPO))
print("Releases:", [r["tag_name"] for r in releases[:MAX_DELTA + 1]])


# ----------------------------------------------------------------------------- PRs de bug-fix
def fetch_bug_prs():
    """PRs merged com label Bug, fechados entre releases[MAX_DELTA] e releases[0], em blocos mensais."""
    start = datetime.strptime(releases[MAX_DELTA]["published_at"][:10], "%Y-%m-%d")
    end = datetime.strptime(releases[0]["published_at"][:10], "%Y-%m-%d")
    prs = {}
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=30), end)
        q = f"repo:{OWNER}/{REPO} is:pr is:merged label:Bug closed:{cur:%Y-%m-%d}..{nxt:%Y-%m-%d}"
        page = 1
        while True:
            r = requests.get("https://api.github.com/search/issues",
                             params={"q": q, "per_page": 100, "page": page}, headers=H)
            if r.status_code == 403:  # rate limit da Search API
                print("  rate limit, aguardando 60s..."); time.sleep(60); continue
            data = r.json()
            for it in data["items"]:
                prs[str(it["number"])] = it["closed_at"]
            print(f"  {cur:%Y-%m-%d}..{nxt:%Y-%m-%d} p{page}: {len(data['items'])} (total={data['total_count']})")
            time.sleep(7 if "Authorization" not in H else 1)
            if page * 100 >= data["total_count"]:
                break
            page += 1
        cur = nxt + timedelta(days=1)
    return prs


bug_prs = cached(os.path.join(OUT, f"bug_prs_d{MAX_DELTA}.json"), fetch_bug_prs)
print("PRs de bug-fix coletados:", len(bug_prs))

# ----------------------------------------------------------------------------- PR -> arquivos (git local)
subprocess.run(["git", "-C", REPO, "fetch", "-q", "--all"], check=False)
log = subprocess.run(["git", "-C", REPO, "log", "--remotes", "--no-merges", "--name-only",
                      "--format=@@%H%x09%s"], capture_output=True, text=True, encoding="utf-8").stdout
pr_files = defaultdict(set)
current = None
for line in log.splitlines():
    if line.startswith("@@"):
        m = re.search(r"\(#(\d+)\)\s*$", line)
        current = m.group(1) if m else None
    elif line.strip() and current and line.endswith(".py"):
        pr_files[current].add(line.strip())
missing = [n for n in bug_prs if n not in pr_files]
print(f"PRs com commit localizado no git: {len(bug_prs) - len(missing)}/{len(bug_prs)}")


# ----------------------------------------------------------------------------- métricas por release
def metrics_for(tag):
    path = os.path.join(OUT, f"metrics_{tag}.csv")
    if os.path.exists(path):
        return pd.read_csv(path, sep=";")
    subprocess.run(["git", "-C", REPO, "checkout", "-q", "-f", tag], check=True)
    rows = list(pymetrix.scan_directory(f"./{REPO}/"))
    df = pd.DataFrame(rows)
    df["FILE"] = df["FILE"].str.replace(os.sep, "/", regex=False)
    df.to_csv(path, sep=";", index=False)
    return df


def legacy_transform(df):
    """Tratamento original (antes da Seção 2.2), apenas para comparação."""
    return df[(~df["FILE"].str.contains("/pandas/doc/")) & (df["LOC"] > 0)]


def cv_scores(df):
    """Avaliação rápida do potencial preditivo: RandomForest, 5x3 CV estratificada."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import RepeatedStratifiedKFold, cross_validate
    y = df["BUG"].values
    if y.sum() < 10 or (len(y) - y.sum()) < 10:
        return {"ROC_AUC": float("nan"), "PR_AUC": float("nan"), "F1": float("nan"), "MCC": float("nan")}
    cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=3, random_state=42)
    clf = RandomForestClassifier(n_estimators=300, class_weight="balanced", random_state=42, n_jobs=-1)
    s = cross_validate(clf, df[METRICS].values, y, cv=cv,
                       scoring={"ROC_AUC": "roc_auc", "PR_AUC": "average_precision", "F1": "f1", "MCC": "matthews_corrcoef"})
    return {k: round(s[f"test_{k}"].mean(), 3) for k in ["ROC_AUC", "PR_AUC", "F1", "MCC"]}


# ----------------------------------------------------------------------------- experimento
results = []
for delta in range(1, MAX_DELTA + 1):
    target = releases[delta]["tag_name"]
    metrics = metrics_for(target)
    for window in range(1, delta + 1):
        tag, start, end = pipeline.extract_post_release_timeline(releases, delta=delta, window=window)
        prs = [n for n, closed in bug_prs.items() if start <= closed[:10] <= end]
        buggy = {f"./{REPO}/{f}" for n in prs for f in pr_files.get(n, ())}
        df = metrics.copy()
        df["BUG"] = df["FILE"].isin(buggy).astype(int)

        raw_path = os.path.join(WIN_OUT, f"{tag.replace('.', '_')}_d{delta}_w{window}_raw_dataset.csv")
        df[FIELDS].to_csv(raw_path, sep=";", index=False)
        trf = pd.read_csv(pipeline.tansform_raw_dataset(raw_path), sep=";")
        leg = legacy_transform(df)

        days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
        row = {"delta": delta, "window": window, "target": tag, "end_release": releases[delta - window]["tag_name"],
               "start": start, "end": end, "days": days, "bug_prs": len(prs),
               "raw_n": len(df), "legacy_n": len(leg), "legacy_bug_%": round(100 * leg["BUG"].mean(), 1),
               "trf_n": len(trf), "trf_bug": int(trf["BUG"].sum()), "trf_bug_%": round(100 * trf["BUG"].mean(), 1)}
        row.update(cv_scores(trf))
        results.append(row)
        print(row)

summary = pd.DataFrame(results)
summary.to_csv(os.path.join(OUT, "windows_summary.csv"), sep=";", index=False)
with open(os.path.join(OUT, "windows_summary.md"), "w", encoding="utf-8") as f:
    cols = list(summary.columns)
    f.write("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n")
    for _, r in summary.iterrows():
        f.write("| " + " | ".join(str(r[c]) for c in cols) + " |\n")
print("\n", summary.to_string(index=False))
