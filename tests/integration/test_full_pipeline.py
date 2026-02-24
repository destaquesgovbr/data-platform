"""
Teste de integração completo do pipeline data-platform.

Este teste executa o fluxo completo end-to-end:
1. Criação de schema e dados mestre (agencies, themes)
2. Upload para Cogfy (AI enrichment)
3. Enrich com temas do Cogfy
4. Geração de embeddings via API Cloud Run
5. Carga full no Typesense (com embeddings)

Note: Scraping moved to standalone scraper repo.

Requisitos:
- Docker containers rodando (PostgreSQL + Typesense)
- COGFY_API_KEY configurado
- Cloud Run API de embeddings acessível

Execução:
    poetry run pytest tests/integration/test_full_pipeline.py -v -s
"""

import os
import shutil
import subprocess
import time
from collections.abc import Generator

import psycopg2
import psycopg2.extensions
import pytest
import requests  # type: ignore[import-untyped]

# Skip all tests: scraping was extracted to standalone scraper repo,
# this end-to-end test needs to be redesigned to seed data independently.
pytestmark = pytest.mark.skip(reason="Needs redesign after scraper extraction (no local scraping)")

# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://destaquesgovbr_dev:dev_password@localhost:5433/destaquesgovbr_dev"
)
START_DATE = "2025-12-20"
END_DATE = "2025-12-23"

# Typesense
TYPESENSE_HOST = "localhost"
TYPESENSE_PORT = "8108"
TYPESENSE_API_KEY = "local_dev_key_12345"
TYPESENSE_PROTOCOL = "http"

# Tempo de espera para processamento Cogfy (segundos)
COGFY_WAIT_TIME = 120  # 2 minutos


# ==============================================================================
# FIXTURES
# ==============================================================================
@pytest.fixture(scope="module")  # type: ignore[untyped-decorator]
def docker_services() -> Generator[None, None, None]:
    """
    Inicia containers Docker antes dos testes.

    - Limpa containers existentes
    - Inicia PostgreSQL e Typesense frescos
    - Aguarda serviços ficarem prontos

    Em CI (GitHub Actions), assume que os containers já estão rodando como services.
    """
    print("\n" + "=" * 70)
    print("FASE 0: Preparando ambiente Docker")
    print("=" * 70)

    # Detectar se está em CI
    is_ci = os.getenv("CI") == "true" or os.getenv("GITHUB_ACTIONS") == "true"

    if not is_ci:
        # Detectar comando docker compose disponível
        docker_compose_cmd = get_docker_compose_command()

        # Limpar containers existentes
        print("🔧 Parando e removendo containers existentes...")
        subprocess.run(docker_compose_cmd + ["down", "-v"], check=True, cwd=os.getcwd())

        # Iniciar containers limpos
        print("🚀 Iniciando PostgreSQL e Typesense...")
        subprocess.run(docker_compose_cmd + ["up", "-d"], check=True, cwd=os.getcwd())
    else:
        print("ℹ️  Running in CI - using existing service containers...")

    # Aguardar PostgreSQL
    print("⏳ Aguardando PostgreSQL ficar pronto...")
    print(f"   DATABASE_URL: {DATABASE_URL}")
    for i in range(30):  # Máximo 30 segundos
        try:
            if is_ci:
                # Em CI, testar conexão direta ao PostgreSQL
                import psycopg2

                conn = psycopg2.connect(DATABASE_URL)
                conn.close()
                print("✅ PostgreSQL pronto!")
                break
            else:
                # Local, usar docker exec
                result = subprocess.run(
                    [
                        "docker",
                        "exec",
                        "destaquesgovbr-postgres",
                        "pg_isready",
                        "-U",
                        "destaquesgovbr_dev",
                    ],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    print("✅ PostgreSQL pronto!")
                    break
        except (subprocess.TimeoutExpired, Exception) as e:
            if i == 0:  # Print error only once
                print(f"   Tentando conectar... (erro: {e})")
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL não ficou pronto em 30 segundos")

    # Aguardar Typesense
    print("⏳ Aguardando Typesense ficar pronto...")
    for _i in range(30):  # Máximo 30 segundos
        try:
            response = requests.get(f"http://{TYPESENSE_HOST}:{TYPESENSE_PORT}/health", timeout=2)
            if response.status_code == 200:
                print("✅ Typesense pronto!")
                break
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("Typesense não ficou pronto em 30 segundos")

    print("\n✅ Ambiente Docker preparado com sucesso!\n")

    yield

    # Cleanup opcional - manter containers rodando para inspeção
    # subprocess.run(["docker-compose", "down"], check=True)


@pytest.fixture(scope="module")  # type: ignore[untyped-decorator]
def env_vars() -> Generator[None, None, None]:
    """Configura variáveis de ambiente para todos os testes."""
    original_env = os.environ.copy()

    os.environ.update(
        {
            "DATABASE_URL": DATABASE_URL,
            "TYPESENSE_HOST": TYPESENSE_HOST,
            "TYPESENSE_PORT": TYPESENSE_PORT,
            "TYPESENSE_API_KEY": TYPESENSE_API_KEY,
            "TYPESENSE_PROTOCOL": TYPESENSE_PROTOCOL,
            "STORAGE_BACKEND": "postgres",
            "STORAGE_READ_FROM": "postgres",
        }
    )

    yield

    # Restaurar env vars originais
    os.environ.clear()
    os.environ.update(original_env)


# ==============================================================================
# HELPER FUNCTIONS
# ==============================================================================
def run_cli_command(
    command_list: list[str], description: str = ""
) -> subprocess.CompletedProcess[str]:
    """
    Executa comando CLI do data-platform.

    Args:
        command_list: Lista com comando e argumentos
        description: Descrição da operação para logging
    """
    if description:
        print(f"\n📋 {description}")

    full_command = ["poetry", "run", "data-platform"] + command_list
    print(f"   Executando: {' '.join(full_command)}")

    result = subprocess.run(
        full_command,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutos timeout
    )

    if result.stdout:
        print(f"   STDOUT: {result.stdout[:500]}")  # Primeiros 500 chars

    if result.returncode != 0:
        print(f"   ❌ ERRO (exit code {result.returncode})")
        if result.stderr:
            print(f"   STDERR: {result.stderr}")
        raise subprocess.CalledProcessError(
            result.returncode, full_command, result.stdout, result.stderr
        )

    print("   ✅ Sucesso")
    return result


def get_db_connection() -> psycopg2.extensions.connection:
    """Retorna conexão com PostgreSQL."""
    return psycopg2.connect(DATABASE_URL)


def count_news(conn: psycopg2.extensions.connection | None = None, where_clause: str = "") -> int:
    """Conta notícias no PostgreSQL."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True

    cur = conn.cursor()
    query = f"SELECT COUNT(*) FROM news {where_clause}"
    cur.execute(query)
    count = cur.fetchone()[0]
    cur.close()

    if close_conn:
        conn.close()

    return count  # type: ignore[no-any-return]


def get_docker_compose_command() -> list[str]:
    """
    Returns the appropriate docker compose command for the environment.

    Modern Docker uses 'docker compose' (plugin), legacy uses 'docker-compose' (standalone).
    Checks for modern command first, then falls back to legacy.
    """
    # Try modern 'docker compose' first
    if shutil.which("docker"):
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
        )
        if result.returncode == 0:
            return ["docker", "compose"]

    # Fall back to legacy 'docker-compose'
    if shutil.which("docker-compose"):
        return ["docker-compose"]

    raise RuntimeError("Neither 'docker compose' nor 'docker-compose' found")


# ==============================================================================
# TESTES
# ==============================================================================
def test_01_populate_master_data(docker_services: None, env_vars: None) -> None:
    """
    FASE 1: Popula dados mestre (agencies e themes).
    """
    print("\n" + "=" * 70)
    print("FASE 1: Populando dados mestre")
    print("=" * 70)

    # Check if schema already exists (created by docker init.sql)
    print("\n🗄️  Verificando schema do banco de dados...")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'agencies')"
    )
    schema_exists = cur.fetchone()[0]
    cur.close()
    conn.close()

    if schema_exists:
        print("✅ Schema já existe (criado pelo Docker init.sql)")
    else:
        print("🔧 Criando schema do banco de dados...")
        with open("scripts/create_schema.sql") as f:
            schema_sql = f.read()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(schema_sql)
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Schema criado")

    # Popular agencies
    print("\n📊 Populando agencies...")
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "scripts/populate_agencies.py",
            "--source",
            "test-data/agencies.yaml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Falha ao popular agencies: {result.stderr}"
    print("✅ Agencies populadas")

    # Popular themes
    print("\n📊 Populando themes...")
    result = subprocess.run(
        [
            "poetry",
            "run",
            "python",
            "scripts/populate_themes.py",
            "--source",
            "test-data/themes_tree_enriched_full.yaml",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Falha ao popular themes: {result.stderr}"
    print("✅ Themes populadas")

    # Validar
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM agencies")
    agencies_count = cur.fetchone()[0]
    assert agencies_count > 0, "Nenhuma agency foi inserida"
    print(f"   📈 Total de agencies: {agencies_count}")

    cur.execute("SELECT COUNT(*) FROM themes")
    themes_count = cur.fetchone()[0]
    assert themes_count > 0, "Nenhum theme foi inserido"
    print(f"   📈 Total de themes: {themes_count}")

    cur.close()
    conn.close()

    print("\n✅ FASE 1 COMPLETA: Dados mestre carregados")


def test_02_upload_cogfy(docker_services: None, env_vars: None) -> None:
    """
    FASE 2: Upload de notícias para Cogfy (AI enrichment).

    Requer COGFY_API_KEY configurado.
    """
    print("\n" + "=" * 70)
    print("FASE 2: Upload para Cogfy")
    print("=" * 70)

    # Verificar que COGFY_API_KEY está configurado
    if not os.getenv("COGFY_API_KEY"):
        pytest.fail(
            "COGFY_API_KEY não configurado. Configure com: export COGFY_API_KEY=<sua-chave>"
        )

    run_cli_command(
        ["upload-cogfy", "--start-date", START_DATE, "--end-date", END_DATE],
        "Enviando notícias para Cogfy",
    )

    print("\n✅ FASE 2 COMPLETA: Upload para Cogfy finalizado")
    print(f"\n⏸️  AGUARDANDO: Cogfy processará as notícias (~{COGFY_WAIT_TIME // 60} minutos)")
    print("   O Cogfy usa LLM para classificar temas e gerar resumos...")

    # Aguardar processamento do Cogfy
    print(f"\n⏳ Aguardando {COGFY_WAIT_TIME} segundos para processamento Cogfy...")
    for i in range(COGFY_WAIT_TIME // 60):
        time.sleep(60)
        remaining = COGFY_WAIT_TIME // 60 - i - 1
        print(f"   ⏱️  {remaining} minutos restantes...")

    print("\n✅ Tempo de espera completo. Prosseguindo para enrich...")


def test_03_enrich_themes(docker_services: None, env_vars: None) -> None:
    """
    FASE 3: Enrich com temas classificados pelo Cogfy.
    """
    print("\n" + "=" * 70)
    print("FASE 3: Enrich themes (baixar de Cogfy)")
    print("=" * 70)

    # Verificar que COGFY_API_KEY está configurado
    if not os.getenv("COGFY_API_KEY"):
        pytest.fail("COGFY_API_KEY não configurado")

    run_cli_command(
        ["enrich", "--start-date", START_DATE, "--end-date", END_DATE],
        "Baixando temas enriquecidos do Cogfy",
    )

    # Validar enriquecimento
    conn = get_db_connection()
    cur = conn.cursor()

    # Contar notícias com tema
    cur.execute("SELECT COUNT(*) FROM news WHERE most_specific_theme_id IS NOT NULL")
    enriched_count = cur.fetchone()[0]

    # Contar notícias com summary
    cur.execute("SELECT COUNT(*) FROM news WHERE summary IS NOT NULL AND summary != ''")
    summary_count = cur.fetchone()[0]

    total = count_news(conn)

    cur.close()
    conn.close()

    print("\n📊 Resultados do enriquecimento:")
    print(f"   Total de notícias: {total}")
    print(f"   Com tema classificado: {enriched_count} ({enriched_count / total * 100:.1f}%)")
    print(f"   Com AI summary: {summary_count} ({summary_count / total * 100:.1f}%)")

    assert enriched_count > 0, "Nenhuma notícia foi enriquecida com temas"

    print("\n✅ FASE 3 COMPLETA: Enriquecimento finalizado")


def test_04_generate_embeddings(docker_services: None, env_vars: None) -> None:
    """
    FASE 4: Geração de embeddings semânticos via API Cloud Run.

    Requer API de embeddings rodando (Cloud Run).
    """
    print("\n" + "=" * 70)
    print("FASE 4: Geração de embeddings")
    print("=" * 70)

    run_cli_command(
        [
            "generate-embeddings",
            "--start-date",
            START_DATE,
            "--end-date",
            END_DATE,
            "--batch-size",
            "32",
        ],
        "Gerando embeddings via API Cloud Run",
    )

    # Validar embeddings
    conn = get_db_connection()
    cur = conn.cursor()

    # Contar notícias com embedding
    cur.execute("SELECT COUNT(*) FROM news WHERE content_embedding IS NOT NULL")
    embeddings_count = cur.fetchone()[0]

    total = count_news(conn)

    cur.close()
    conn.close()

    print("\n📊 Resultados dos embeddings:")
    print(f"   Total de notícias: {total}")
    print(f"   Com embeddings: {embeddings_count} ({embeddings_count / total * 100:.1f}%)")

    assert embeddings_count > 0, "Nenhum embedding foi gerado"

    print("\n✅ FASE 4 COMPLETA: Embeddings gerados")


def test_05_sync_typesense_full(docker_services: None, env_vars: None) -> None:
    """
    FASE 5: Sync full para Typesense (com embeddings).

    - Deleta collection 'news' existente
    - Recria collection com schema atualizado
    - Popula com todas as notícias do PostgreSQL
    """
    print("\n" + "=" * 70)
    print("FASE 5: Sync full Typesense")
    print("=" * 70)

    # Deletar collection existente
    print("\n🗑️  Deletando collection 'news' (se existir)...")
    try:
        subprocess.run(
            [
                "poetry",
                "run",
                "data-platform",
                "typesense-delete",
                "--collection-name",
                "news",
                "--confirm",
            ],
            capture_output=True,
            timeout=30,
        )
        print("   ✅ Collection deletada")
    except subprocess.SubprocessError:
        print("   ℹ️  Collection não existia ou já foi deletada")

    # Sync full (embeddings are always included now)
    run_cli_command(
        [
            "sync-typesense",
            "--start-date",
            START_DATE,
            "--end-date",
            END_DATE,
            "--full-sync",
        ],
        "Executando sync full (recria collection e popula)",
    )

    # Validar dados no Typesense
    print("\n📊 Validando dados no Typesense...")

    # Testar busca
    response = requests.get(
        f"http://{TYPESENSE_HOST}:{TYPESENSE_PORT}/collections/news/documents/search",
        params={"q": "educação", "query_by": "title"},
        headers={"X-TYPESENSE-API-KEY": TYPESENSE_API_KEY},
        timeout=10,
    )

    assert response.status_code == 200, f"Erro ao buscar no Typesense: {response.status_code}"

    data = response.json()
    found = data.get("found", 0)
    print(f"   🔍 Busca por 'educação': {found} resultados encontrados")

    # Listar collections
    print("\n📋 Listando collections...")
    result = subprocess.run(
        ["poetry", "run", "data-platform", "typesense-list"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    print(f"   {result.stdout}")

    print("\n✅ FASE 5 COMPLETA: Typesense populado")


def test_06_validate_final_state(docker_services: None, env_vars: None) -> None:
    """
    FASE 6: Validação final do estado completo do sistema.

    Verifica:
    - PostgreSQL tem notícias com todos os enriquecimentos
    - Typesense está acessível e tem dados
    - Embeddings foram gerados
    - Temas foram enriquecidos
    """
    print("\n" + "=" * 70)
    print("FASE 6: Validação final")
    print("=" * 70)

    conn = get_db_connection()
    cur = conn.cursor()

    # Estatísticas gerais
    cur.execute("SELECT COUNT(*) FROM news")
    total_news = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM news WHERE most_specific_theme_id IS NOT NULL")
    with_themes = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM news WHERE summary IS NOT NULL AND summary != ''")
    with_summary = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM news WHERE content_embedding IS NOT NULL")
    with_embeddings = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM agencies")
    total_agencies = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM themes")
    total_themes = cur.fetchone()[0]

    # Estatísticas por agency
    cur.execute("""
        SELECT agency_key, COUNT(*) as count
        FROM news
        GROUP BY agency_key
        ORDER BY count DESC
    """)
    by_agency = cur.fetchall()

    cur.close()
    conn.close()

    # Imprimir relatório
    print("\n" + "=" * 70)
    print("📊 RELATÓRIO FINAL")
    print("=" * 70)
    print("\n🗄️  POSTGRESQL:")
    print(f"   Total de notícias: {total_news}")
    print(f"   Com temas: {with_themes} ({with_themes / total_news * 100:.1f}%)")
    print(f"   Com AI summary: {with_summary} ({with_summary / total_news * 100:.1f}%)")
    print(f"   Com embeddings: {with_embeddings} ({with_embeddings / total_news * 100:.1f}%)")
    print(f"   Total de agencies: {total_agencies}")
    print(f"   Total de themes: {total_themes}")

    print("\n📈 DISTRIBUIÇÃO POR AGENCY:")
    for agency, count in by_agency:
        print(f"   {agency}: {count} notícias")

    print("\n🔍 TYPESENSE:")
    # Testar acesso ao Typesense
    try:
        response = requests.get(
            f"http://{TYPESENSE_HOST}:{TYPESENSE_PORT}/collections/news/documents/search",
            params={"q": "*", "per_page": "1"},
            headers={"X-TYPESENSE-API-KEY": TYPESENSE_API_KEY},
            timeout=5,
        )
        data = response.json()
        ts_found = data.get("found", 0)
        print(f"   Total de documentos: {ts_found}")
        print("   Status: ✅ Acessível")
    except Exception as e:
        print(f"   Status: ❌ Erro: {e}")

    print("\n⏱️  PERÍODO TESTADO:")
    print(f"   Início: {START_DATE}")
    print(f"   Fim: {END_DATE}")
    print("   Note: Scraping handled by standalone scraper repo")

    print("\n" + "=" * 70)
    print("✅ BATERIA DE TESTES COMPLETA!")
    print("=" * 70)

    # Asserções finais
    assert total_news > 0, "Sistema vazio - nenhuma notícia"
    assert with_themes > 0, "Nenhuma notícia foi enriquecida com temas"
    assert with_embeddings > 0, "Nenhum embedding foi gerado"
    assert total_agencies > 0, "Nenhuma agency foi carregada"
    assert total_themes > 0, "Nenhum theme foi carregado"


# ==============================================================================
# EXECUÇÃO STANDALONE
# ==============================================================================
if __name__ == "__main__":
    print("""
    ════════════════════════════════════════════════════════════════════════
    BATERIA DE TESTES - DATA PLATFORM
    ════════════════════════════════════════════════════════════════════════

    Este script testa o pipeline completo:
    1. Populate master data (agencies, themes)
    2. Upload para Cogfy
    3. Enrich themes
    4. Generate embeddings
    5. Sync Typesense
    6. Validação final

    Requisitos:
    - Docker containers rodando
    - COGFY_API_KEY configurado
    - Cloud Run API de embeddings acessível

    Execute com:
        poetry run pytest tests/integration/test_full_pipeline.py -v -s

    ════════════════════════════════════════════════════════════════════════
    """)
