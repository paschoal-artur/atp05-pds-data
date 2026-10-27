"""
Verifica, numa amostra de PRs de bug-fix, quantos commits de merge existem e quantos arquivos
eles "arrastam" para o rótulo (problema da rotulagem original). Usa poucas requisições sem token.
"""
import requests

H = {"Accept": "application/vnd.github+json"}
q = "repo:pandas-dev/pandas is:pr is:merged label:Bug closed:2025-07-07..2025-09-29"
prs = requests.get(f"https://api.github.com/search/issues?q={q}&per_page=8", headers=H).json()["items"]
tot_merge_files = tot_pr_files = 0
for pr in prs[:8]:
    n = pr["number"]
    commits = requests.get(f"https://api.github.com/repos/pandas-dev/pandas/pulls/{n}/commits?per_page=100", headers=H).json()
    if not isinstance(commits, list):
        print("rate limit:", commits.get("message")); break
    merges = [c for c in commits if len(c["parents"]) > 1]
    pr_files = requests.get(f"https://api.github.com/repos/pandas-dev/pandas/pulls/{n}/files?per_page=100", headers=H).json()
    extra = 0
    if merges:
        mc = requests.get(f"https://api.github.com/repos/pandas-dev/pandas/commits/{merges[0]['sha']}", headers=H).json()
        extra = len(mc.get("files", []))
    print(f"PR #{n}: commits={len(commits)} merges={len(merges)} arquivos_no_PR={len(pr_files)} arquivos_no_1o_merge={extra}")
