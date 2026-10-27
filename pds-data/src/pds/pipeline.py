from datetime import datetime
import requests
from pds import pymetrix
import math
import csv
from operator import itemgetter
import re
import git
import logging
import os
import sys
import pandas

logging.basicConfig(filename='pipeline.log', encoding='utf-8', level=logging.DEBUG, format='[%(asctime)s - %(levelname)s]: %(message)s')
logger = logging.getLogger(__name__)

def _github_headers(github_token:str = None) -> dict:
    """
    Monta os headers das requisições à GitHub API. O header de autorização só é
    enviado quando há token (evita o envio de "Bearer None").
    """
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    return headers

def extract_releases_matching_semantic_versioning(github_token:str = None, 
                                                  github_owner:str = None, 
                                                  github_repository:str = None) -> list[dict]:
    """
    Essa função extrai informações sobre a lista de releases do projeto hospedado no GitHub. 
    São consideradas apenas releases que seguem a seguinte o versionamento semântico: https://semver.org/
    
    Parameters:
        github_token (str): O token de acesso do GitHub. Valor padrão é None.
        github_owner (str): O nome do owner do projeto. Valor padrão é None. 
        github_repository (str): O nome do repositório do projeto. Valor padrão é None.
    
    Returns:
        filtered_releases (list[dict]): A lista de releases em ordem decrescente de data de publicação. 
        Cada release é um dicionário com os seguintes campos: 
        "id" (identificador da relsease); 
        "tag_name" (nome da tag associada a release); e  
        "published_at"(data de publicação da relsease).
    """ 
    per_page = 100
    headers = _github_headers(github_token)        
    releases_url = f"https://api.github.com/repos/{github_owner}/{github_repository}/releases?per_page={per_page}&page=1"
    
    fetched_releases = requests.get(releases_url, headers=headers).json()
    releases = []

    number_of_pages = math.ceil(len(fetched_releases)/100.00)
    
    for page_number in range(1, number_of_pages + 1):
        releases_url = f"https://api.github.com/repos/{github_owner}/{github_repository}/releases?per_page={per_page}&page={page_number}"
        fetched_releases = requests.get(releases_url, headers=headers).json()

        for release in fetched_releases:        
            if (not release.get("draft")) and (not release.get("prerelease")):
                releases.append({"id": str(release.get("id")),
                                 "name": str(release.get("name")),
                                 "tag_name": str(release.get("tag_name")),
                                 "published_at": release.get("published_at")})
    filtered_releases = []
    pattern = re.compile(r'^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)(?:-(?P<prerelease>(?:0|[1-9]\d*|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*))(?:\.(?:0|[1-9]\d*|(?:[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)))*))?(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')
    for release in releases:
        match = pattern.match(release.get("tag_name")[1:])  # Removendo o 'v' do início
        if match:
            filtered_releases.append(release)

    return sorted(filtered_releases, key=itemgetter('published_at'), reverse=True)


def extract_post_release_timeline(releases:list[dict] = None, delta:int = 2, window:int = None) -> tuple[str, str, str]:
    """
    Essa função determina a release alvo e o período de tempo a ser usado para extração 
    de pull requests de bug-fix. A release alvo é a antepenúltima release do projeto, 
    a data de início é a data de publicação da release alvo, a data de fim é a data de 
    publicação da última release do projeto.
    
    Parameters:
        releases (list[dict]): A lista de releases. Valor padrão é None. 
        Cada release é um dicionário com os seguintes campos: 
        “id” (identificador da relsease); 
        “tag_name” (nome da tag associada a release); e  
        “published_at”(data de publicação da relsease).
        delta (int): O número de releases anteriores a atual a serem 
        consideradas para definir a release alvo de coleta de dados.
        window (int): O tamanho da janela de coleta, em número de releases, a partir
        da release alvo. A data de fim passa a ser a data de publicação de
        releases[delta - window]. Valor padrão é None (equivale a window = delta,
        i.e., a janela vai até a última release, comportamento original).
    
    Returns:
        target_release_name (str): A release alvo.
        start_date (str): A data de início da extração de dados ("%Y-%m-%d").
        end_date (str): A data de fim da extração de dados ("%Y-%m-%d").
    """
    if window is None:
        window = delta
    if not (1 <= window <= delta < len(releases)):
        raise ValueError(f"Parâmetros inválidos: delta={delta}, window={window}, releases={len(releases)}")

    last_release = releases[delta - window]
    target_release = releases[delta]

    target_release_name = target_release.get("tag_name")
    target_release_date = datetime.strptime(target_release.get("published_at"), "%Y-%m-%dT%H:%M:%SZ")
    last_release_date = datetime.strptime(last_release.get("published_at"), "%Y-%m-%dT%H:%M:%SZ")
    start_date = target_release_date.strftime("%Y-%m-%d")
    end_date = last_release_date.strftime("%Y-%m-%d")
    return target_release_name, start_date, end_date

def extract_bug_fix_pull_requests(github_token:str = None, github_owner:str = None, 
                                  github_repository:str = None, label:str = "Bug", 
                                  closed_since: str=None, closed_to: str=None) -> list[str]:
    """
    Essa função faz a extração de pull requests de bug-fix no período estabelecido 
    [closed_since, closed_to]. 
    
    Parameters:
        github_token (str): O token de acesso do GitHub. Valor padrão é None.
        github_owner (str): O nome do owner do projeto. Valor padrão é None. 
        github_repository (str): O nome do repositório do projeto. Valor padrão é None.
        label (str): O rótulo a ser utilizado na filtragem. Valor padrão é "Bug".
        closed_since (str): Data que define o período inicial de pull request fechados. Valor padrão é None.
        closed_to (str): Data que define o período final de pull request fechados. Valor padrão é None.
    
    Returns:
        bug_fix_pull_request_numbers (list[str]): Lista contendo os números das pull requests selecionadas.
    """    
    date_format = "%Y-%m-%d"
    resolution_since = datetime.strptime(closed_since,date_format).strftime(date_format)
    resolution_to = datetime.strptime(closed_to,date_format).strftime(date_format)
    per_page = 100

    headers = _github_headers(github_token)
    # "is:merged": PRs fechados sem merge não corrigem nada no código e geram falsos positivos.
    query = f"repo:{github_owner}/{github_repository} is:pr is:merged label:{label} closed:{resolution_since}..{resolution_to}"
    releases_url = f"https://api.github.com/search/issues?q={query}&per_page={per_page}&page=1"

    fetched_bug_fix_pull_requests = requests.get(releases_url, headers=headers).json()
    number_of_pages = math.ceil(fetched_bug_fix_pull_requests.get("total_count")/100.00)
    
    bug_fix_pull_request_numbers = []

    for page_number in range(1, number_of_pages + 1):
        releases_url = f"https://api.github.com/search/issues?q={query}&per_page={per_page}&page={page_number}"
        fetched_bug_fix_pull_requests = requests.get(releases_url, headers=headers).json()
        pull_requests = fetched_bug_fix_pull_requests.pop("items")
        for pull_request in pull_requests:
            bug_fix_pull_request_numbers.append(str(pull_request.get("number")))

    return list(set(bug_fix_pull_request_numbers))


def extract_bug_fix_commits(github_token:str = None, github_owner:str = None, 
                            github_repository:str = None, bug_fix_pull_request_numbers:list[str] = []) -> list[str]:
    """
    Essa função faz a extração de commits de bug-fix associados às pull requests de bug-fix. 
    
    Parameters:
        github_token (str): O token de acesso do GitHub. Valor padrão é None.
        github_owner (str): O nome do owner do projeto. Valor padrão é None. 
        github_repository (str): O nome do repositório do projeto. Valor padrão é None.
        bug_fix_pull_request_numbers (list[str]): Lista contendo os números das pull requests selecionadas.  Valor padrão [].
    
    Returns:
        bug_fix_commits (list[str]): Lista contendo os hash dos commits de bug-fix.
    """
    bug_fix_commits = []
    
    headers = _github_headers(github_token)
    for pull_request_number in bug_fix_pull_request_numbers:
        releases_url = f"https://api.github.com/repos/{github_owner}/{github_repository}/pulls/{pull_request_number}/commits?&per_page={100}"
        fetched_commits = requests.get(releases_url, headers=headers).json()
        for commit in fetched_commits:
            # Commits de merge (ex.: "Merge branch 'main' into ...") têm mais de um pai e seu
            # diff inclui mudanças de terceiros vindas da main, rotulando arquivos indevidamente.
            if len(commit.get("parents", [])) > 1:
                continue
            bug_fix_commits.append(commit.get("sha"))
    
    return list(set(bug_fix_commits))


def extract_buggy_files(github_token:str = None, github_owner:str = None, 
                        github_repository:str = None, bug_fix_commits:list[str] = [], 
                        file_types:list[str] = [".py"]) -> list[str]:
    """
    Essa função faz a extração de commits de bug-fix associados às pull requests de bug-fix. 
    
    Parameters:
        github_token (str): O token de acesso do GitHub. Valor padrão é None.
        github_owner (str): O nome do owner do projeto. Valor padrão é None. 
        github_repository (str): O nome do repositório do projeto. Valor padrão é None.
        bug_fix_commits (list[str]): Lista contendo os hash dos commits de bug-fix. Valor padrão [].
        file_types (list[str]): Lista de extensão dos tipos de arquivos suportados. Valor padrão [".py"].
    
    Returns:
        buggy_files (list[str]): Lista contendo os arquivos afetados pelos commits de bug-fix.
    """    
    buggy_files = []
    headers = _github_headers(github_token)

    for bug_fix_commit in bug_fix_commits:
        releases_url = f"https://api.github.com/repos/{github_owner}/{github_repository}/commits/{bug_fix_commit}"
        fetched_commit = requests.get(releases_url, headers=headers).json()
        for file in fetched_commit.get("files", []):
            if str(file.get("filename")).endswith(tuple(file_types)):
                buggy_files.append(file.get("filename"))
    
    return buggy_files


def extract_code_metrics_and_labeling(github_owner:str = None, 
                                      github_repository:str = None, release_tag:str = None, 
                                      buggy_files:list[str] = []) -> str:
    """
    Essa função faz a extração das métricas de código e rotulagem nos arquivos da release alvo. 
    
    Parameters:
        github_owner (str): O nome do owner do projeto. Valor padrão é None. 
        github_repository (str): O nome do repositório do projeto. Valor padrão é None.
        release_tag (str): Tag name da release alvo. Valor padrão None.
        buggy_files (list[str]): Lista contendo os arquivos afetados pelos commits de bug-fix.    
    
    Returns:
        code_metrics_data (list[dict]): O conjundo de métricas de código e rótulo por arquivo.  
    """
    local_repo = None
    if os.path.isdir(github_repository) and os.path.isdir(os.path.join(github_repository, '.git')):
        local_repo = git.Repo(github_repository)
    else:
        repo_url = f"https://github.com/{github_owner}/{github_repository}.git"
        local_repo = git.Repo.clone_from(repo_url, github_repository)

    local_repo.git.checkout(release_tag)
    local_repo_path = f"./{github_repository}/"
    code_metrics_data = list(pymetrix.scan_directory(local_repo_path))
    if not code_metrics_data:
        print("Nenhuma métrica foi coletada.")
        return
    
    buggy_files_full_path = set()
    for i in range(len(buggy_files)):
        buggy_files_full_path.add(local_repo_path + buggy_files[i])

    for record in code_metrics_data:
        # Normaliza o separador de caminho (no Windows o os.walk usa '\'), pois os caminhos
        # vindos da GitHub API usam sempre '/'. Sem isso nenhum arquivo casaria com o rótulo.
        record['FILE'] = record['FILE'].replace(os.sep, '/')
        record['BUG'] = 1 if record['FILE'] in buggy_files_full_path else 0 #Aplicando o rótulo
    
    return code_metrics_data

def load_raw_dataset(release_tag:str = None, code_metrics_data:list[dict] = None) -> str:
    """
    Essa função cria um arquivo CSV contendo o conjunto de métricas extraídas por arquivo e seus respectivos rótulos.
    O nome do arquivo é iniciado pela tag alvo.
    
    Parameters:
        release_tag (str): Tag name da release alvo. Valor padrão None.
        code_metrics_data (list[dict]): O conjundo de métricas de código e rótulo por arquivo. Valor padrão None.
    
    Returns:
        dataset_file_path (str): O caminho para o dataset bruto gerado.  
    """
    fieldnames = ['FILE', 'LOC', 'COM', 'BLK', 'NOF', 'NOC', 'APF', 'AMC', 'NER', 'NEH', 'CYC', 'MAD', 'BUG'] 
    valid_prefix = release_tag.replace(".", "_")
    dataset_file_path = f"{valid_prefix}_raw_dataset.csv"
    with open(dataset_file_path, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';', quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in code_metrics_data:
            writer.writerow(row)
    
    return dataset_file_path

def tansform_raw_dataset(dataset_file_path:str = None) -> str:
    """
    Essa função aplica algumas transformações no arquivo CSV (dataset bruto) com o intuito de remover 
    linhas que possuam as seguintes características:
    (1) trazem informações de arquivos irrelevante para a tarefa de predição 
    (e.g., arquivos de exemplos ou de documentação);
    (2) trazem valores zerados para a maioria das métricas; e
    (3) sejam valores muito fora do padrão (outliers).

    Regras aplicadas (ver análise exploratória em analysis/eda.py):
    (a) Escopo: apenas o código do pacote, i.e., arquivos sob "./pandas/pandas/". Ficam de fora
        doc/, asv_bench/ (benchmarks), scripts/, web/, ci/, tooling/, typings/ e setup.py.
    (b) Testes: removidos arquivos em diretórios tests/, test_*.py, *_test.py e conftest.py.
        Testes não são o alvo da predição e são alterados em quase todo bug-fix (o PR
        adiciona o teste de regressão), o que os rotula como "defeituosos" sem que o sejam.
    (c) Infraestrutura de testes: pandas/_testing/, pandas/testing.py, util/_tester.py e
        util/_test_decorators.py, pelo mesmo motivo de (b).
    (d) Código gerado/vendorizado: pandas/_version.py (gerado pelo versioneer) e
        pandas/util/version/ (cópia do pacote "packaging"), não mantidos pelo projeto.
    (e) __init__.py só permanece se tiver lógica (ao menos uma função ou classe); os demais
        apenas reexportam nomes e têm métricas praticamente nulas.
    (f) LOC > 0 (arquivos vazios) e remoção de eventuais caminhos duplicados.
    Outliers NÃO são removidos: os maiores arquivos (core/frame.py, core/generic.py, ...) são
    justamente o núcleo do pacote e os mais propensos a defeitos; a assimetria das métricas
    deve ser tratada na etapa de modelagem (ex.: transformação log), não descartando dados.

    Parameters:
        dataset_file_path (str): O caminho para o dataset bruto gerado. Valor padrão None.
    
    Returns:
        transformed_file_path (str): O caminho para o dataset transformado.  
    """
    transformed_file_path = dataset_file_path.replace("raw", "trf")
    dataset = pandas.read_csv(dataset_file_path,
                              index_col=None, 
                              header=0,
                              delimiter=';')
    
    # Normaliza separadores de caminho (datasets gerados no Windows usam '\').
    dataset["FILE"] = dataset["FILE"].str.replace("\\", "/", regex=False)

    filtered_dataset = dataset[(dataset["FILE"].str.contains("/pandas/doc/|/pandas/tests/")==False)]
    filtered_dataset = filtered_dataset[(filtered_dataset["LOC"] > 0)]
    
    # (a) Apenas arquivos do pacote pandas (./pandas/pandas/...).
    filtered_dataset = filtered_dataset[filtered_dataset["FILE"].str.startswith("./pandas/pandas/")]

    # (b) Arquivos de teste.
    test_files = r"/tests?/|/test_[^/]*\.py$|_test\.py$|/conftest\.py$"
    filtered_dataset = filtered_dataset[~filtered_dataset["FILE"].str.contains(test_files, regex=True)]

    # (c) Infraestrutura de testes.
    test_support = r"/pandas/pandas/_testing/|/pandas/pandas/testing\.py$|/util/_tester\.py$|/util/_test_decorators\.py$"
    filtered_dataset = filtered_dataset[~filtered_dataset["FILE"].str.contains(test_support, regex=True)]

    # (d) Código gerado automaticamente ou vendorizado.
    generated_or_vendored = r"/pandas/pandas/_version\.py$|/pandas/pandas/util/version/"
    filtered_dataset = filtered_dataset[~filtered_dataset["FILE"].str.contains(generated_or_vendored, regex=True)]

    # (e) __init__.py somente quando contém lógica (funções ou classes).
    is_init = filtered_dataset["FILE"].str.endswith("/__init__.py")
    has_logic = (filtered_dataset["NOF"] > 0) | (filtered_dataset["NOC"] > 0)
    filtered_dataset = filtered_dataset[~is_init | has_logic]

    # (f) Caminhos duplicados.
    filtered_dataset = filtered_dataset.drop_duplicates(subset="FILE")

    filtered_dataset.to_csv(transformed_file_path, 
                            sep=';', 
                            encoding='utf-8', 
                            index=False)

    return transformed_file_path

def start(token:str = None, delta:int = 7, window:int = 4) -> None:
    """
    Executa a pipeline completa.

    Janela de coleta escolhida a partir do experimento das Seções 2.3/2.4
    (analysis/windows_experiment.py, resultados em analysis/out/windows_summary.csv):
    delta=7 e window=4, i.e., release alvo releases[7] (v3.0.0 em 26/10/2026) e PRs de bug-fix
    fechados até a publicação de releases[3] (v3.0.4). Critérios: proporção de arquivos com bug
    realista (15%-30%; aqui 26.7%), maior MCC em validação cruzada entre as janelas nessa faixa
    (0.604, ROC-AUC 0.857), e coerência conceitual: v3.0.1..v3.0.4 são as releases de correção
    da release alvo. Janelas que terminam na última release (comportamento original, window=delta)
    rotulam mais de 50% dos arquivos como defeituosos, refletindo ruído e não defeitos da release alvo.
    """
    logger.debug("[Step-1] Extraindo Releases Candidatas")
    releases = extract_releases_matching_semantic_versioning(github_token=token, 
                                                             github_owner="pandas-dev", 
                                                             github_repository="pandas")
    logger.debug(f"\tTotal de releases {len(releases)}: {releases}")
    
    logger.debug("\n[Step-2] Extraindo Relese Alvo e Timeline")
    release, start_date, end_date = extract_post_release_timeline(releases, delta=delta, window=window)
    logger.debug(f"\tRelease alvo {release} no período [{start_date}, {end_date}]")

    logger.debug("\n[Step-3] Extraindo Pull Request de Bug-Fix")
    pull_request_numbers = extract_bug_fix_pull_requests(github_token=token,
                                                         github_owner="pandas-dev", 
                                                         github_repository="pandas",
                                                         closed_since=start_date,
                                                         closed_to=end_date)
    logger.debug(f"\tTotal de pull requests {len(pull_request_numbers)}: {pull_request_numbers}")
    
    logger.debug("\n[Step-4] Extraindo Commits de Bug-Fix")
    bug_fix_commits = extract_bug_fix_commits(github_token=token,
                                              github_owner="pandas-dev", 
                                              github_repository="pandas", 
                                              bug_fix_pull_request_numbers=pull_request_numbers)
    logger.debug(f"\tTotal de commits {len(bug_fix_commits)}: {bug_fix_commits}")
    
    logger.debug("\n[Step-5] Extraindo Arquivos Defeituosos")
    buggy_files = extract_buggy_files(github_token=token,
                                      github_owner="pandas-dev", 
                                      github_repository="pandas",
                                      bug_fix_commits=bug_fix_commits)
    logger.debug(f"\tTotal de arquivos {len(buggy_files)}: {buggy_files}")
    
    logger.debug("\n[Step-6] Extraindo Métricas de Código e Gerando Dataset Rotulado")
    code_metrics = extract_code_metrics_and_labeling(github_owner="pandas-dev",
                                                     github_repository="pandas",
                                                     release_tag=release, 
                                                     buggy_files=buggy_files)
    logger.debug(f"\tTotal de linhas de métricas {len(code_metrics)-1}")

    logger.debug("\n[Step-7] Carregando Dataset Bruto para Arquivo")
    raw_dataset_path = load_raw_dataset(release_tag=release, 
                                        code_metrics_data=code_metrics)
    logger.debug(f"\tNome do dataset criado {raw_dataset_path}")

    logger.debug("\n[Step-8] Transformando Dataset Bruto")
    transformed_dataset_path = tansform_raw_dataset(dataset_file_path=raw_dataset_path)
    logger.debug(f"\tNome do dataset transformado {transformed_dataset_path}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        github_token = str(sys.argv[1])
        start(github_token)
    else:
        print("Você deve prover o token de acesso à GitHub API.")    
