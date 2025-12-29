"""
DAG de teste para validar conexão PostgreSQL cross-region.

Testa:
- Conexão postgres_default do Secret Manager
- Latência de queries (us-central1 → southamerica-east1)
- Acesso a Airflow Variables do Secret Manager
"""
from datetime import datetime, timedelta
import time

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.models import Variable


default_args = {
    'owner': 'data-platform',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


def test_postgres_connection(**context):
    """Testa conexão PostgreSQL e mede latência."""
    print("=" * 60)
    print("Teste de Conexão PostgreSQL Cross-Region")
    print("us-central1 (Composer) → southamerica-east1 (Cloud SQL)")
    print("=" * 60)

    # Inicializar hook
    hook = PostgresHook(postgres_conn_id='postgres_default')

    # Teste 1: Conexão básica
    print("\n[1/4] Testando conexão básica...")
    start = time.time()
    conn = hook.get_conn()
    latency_connect = (time.time() - start) * 1000
    print(f"✓ Conexão estabelecida em {latency_connect:.2f}ms")

    # Teste 2: Query simples
    print("\n[2/4] Testando query simples (SELECT 1)...")
    start = time.time()
    result = hook.get_first("SELECT 1 as test")
    latency_query = (time.time() - start) * 1000
    print(f"✓ Query executada em {latency_query:.2f}ms")
    print(f"  Resultado: {result}")

    # Teste 3: Metadata do banco
    print("\n[3/4] Verificando metadata do banco...")
    start = time.time()
    version = hook.get_first("SELECT version()")
    latency_version = (time.time() - start) * 1000
    print(f"✓ Versão PostgreSQL obtida em {latency_version:.2f}ms")
    print(f"  {version[0][:60]}...")

    # Teste 4: Listar tabelas
    print("\n[4/4] Listando tabelas disponíveis...")
    start = time.time()
    tables = hook.get_records("""
        SELECT schemaname, tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY schemaname, tablename
        LIMIT 10
    """)
    latency_tables = (time.time() - start) * 1000
    print(f"✓ Lista de tabelas obtida em {latency_tables:.2f}ms")
    print(f"  Encontradas {len(tables)} tabelas (primeiras 10):")
    for schema, table in tables:
        print(f"    - {schema}.{table}")

    # Resumo de latências
    print("\n" + "=" * 60)
    print("RESUMO DE LATÊNCIAS (us-central1 → southamerica-east1)")
    print("=" * 60)
    print(f"Conexão:       {latency_connect:.2f}ms")
    print(f"SELECT 1:      {latency_query:.2f}ms")
    print(f"Version():     {latency_version:.2f}ms")
    print(f"Listar tabelas: {latency_tables:.2f}ms")
    print(f"Média:         {(latency_connect + latency_query + latency_version + latency_tables) / 4:.2f}ms")
    print("=" * 60)

    # Push metrics to XCom
    context['ti'].xcom_push(key='latency_connect_ms', value=latency_connect)
    context['ti'].xcom_push(key='latency_query_ms', value=latency_query)
    context['ti'].xcom_push(key='latency_version_ms', value=latency_version)
    context['ti'].xcom_push(key='latency_tables_ms', value=latency_tables)

    conn.close()
    print("\n✓ Teste concluído com sucesso!")


def test_secret_manager_variables(**context):
    """Testa acesso a Airflow Variables do Secret Manager."""
    print("=" * 60)
    print("Teste de Acesso ao Secret Manager (Airflow Variables)")
    print("=" * 60)

    # Listar variáveis disponíveis (sem revelar valores)
    test_vars = [
        'typesense_host',
        'postgres_db',
        'gcp_project_id',
        'gcp_region'
    ]

    found_vars = []
    for var_name in test_vars:
        try:
            value = Variable.get(var_name, default_var=None)
            if value:
                # Mascarar valor para não expor em logs
                masked_value = value[:10] + "..." if len(value) > 10 else value
                print(f"✓ {var_name}: {masked_value}")
                found_vars.append(var_name)
            else:
                print(f"✗ {var_name}: Não encontrada")
        except Exception as e:
            print(f"✗ {var_name}: Erro - {str(e)}")

    print("=" * 60)
    print(f"Total: {len(found_vars)}/{len(test_vars)} variáveis encontradas")
    print("=" * 60)

    # Push to XCom
    context['ti'].xcom_push(key='variables_found', value=found_vars)


# Definir DAG
with DAG(
    'test_postgres_connection',
    default_args=default_args,
    description='Testa conexão PostgreSQL cross-region e Secret Manager',
    schedule=None,  # Manual only
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=['test', 'postgres', 'validation'],
) as dag:

    test_db = PythonOperator(
        task_id='test_postgres_connection',
        python_callable=test_postgres_connection,
    )

    test_secrets = PythonOperator(
        task_id='test_secret_manager_variables',
        python_callable=test_secret_manager_variables,
    )

    test_db >> test_secrets
