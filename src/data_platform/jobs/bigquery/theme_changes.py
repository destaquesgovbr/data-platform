"""MERGE de dgb_gold.fato_noticias a partir da auditoria de temas (news_theme_changes).

A migração 034 (tema 26) e a reclassificação por LLM do DS-1 registram cada mudança de tema
em `news_theme_changes`. Este job leva para o BigQuery o estado ATUAL de tema (códigos e
rótulos de l1, l2 e most_specific, os mesmos joins do sync diário) de todo artigo que
aparece na auditoria das campanhas, numa tabela de staging (WRITE_TRUNCATE), e faz MERGE no
fato só onde código ou rótulo diverge.

O estado vem de `news` e não das colunas new_* da auditoria: se o artigo mudou de novo
depois (worker ao vivo, rollback), o fato fica igual ao Postgres. Reexecutável: roda na D0
(depois da 034 e da BigQuery 002) e na D1 (depois da reclassificação por LLM). O dry-run
grava só a staging e conta as linhas do fato que mudariam.
"""

import logging
from collections.abc import Sequence

import pandas as pd

logger = logging.getLogger(__name__)

DATASET_ID = "dgb_gold"
FATO_TABLE = "fato_noticias"
STAGING_TABLE = "_stg_news_theme_changes"
DEFAULT_CAMPAIGNS: tuple[str, ...] = ("tema26", "tema26-rollback")

THEME_COLUMNS: tuple[str, ...] = (
    "theme_l1_code",
    "theme_l1_label",
    "theme_l2_code",
    "theme_l2_label",
    "most_specific_theme_code",
    "most_specific_theme_label",
)

THEME_CHANGES_STATE_QUERY = """
    SELECT
        n.unique_id,
        t1.code AS theme_l1_code,
        t1.label AS theme_l1_label,
        t2.code AS theme_l2_code,
        t2.label AS theme_l2_label,
        tm.code AS most_specific_theme_code,
        tm.label AS most_specific_theme_label
    FROM news n
    JOIN (
        SELECT DISTINCT unique_id FROM news_theme_changes WHERE campaign = ANY(%s)
    ) c ON c.unique_id = n.unique_id
    LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
    LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
    LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id
    ORDER BY n.unique_id
"""


def _diff_predicate() -> str:
    return "\n        OR ".join(
        f"COALESCE(f.{column}, '') != COALESCE(s.{column}, '')" for column in THEME_COLUMNS
    )


def _tables(project_id: str) -> tuple[str, str]:
    return (
        f"`{project_id}.{DATASET_ID}.{FATO_TABLE}`",
        f"`{project_id}.{DATASET_ID}.{STAGING_TABLE}`",
    )


def build_merge_sql(project_id: str) -> str:
    fato, staging = _tables(project_id)
    assignments = ",\n        ".join(f"{column} = s.{column}" for column in THEME_COLUMNS)
    return f"""MERGE {fato} AS f
USING {staging} AS s
ON f.unique_id = s.unique_id
WHEN MATCHED AND (
        {_diff_predicate()}
) THEN UPDATE SET
        {assignments}
"""


def build_diff_count_sql(project_id: str) -> str:
    fato, staging = _tables(project_id)
    return f"""SELECT COUNT(*)
FROM {fato} AS f
JOIN {staging} AS s ON f.unique_id = s.unique_id
WHERE {_diff_predicate()}
"""


def fetch_theme_changes_state(db_url: str, campaigns: Sequence[str]) -> pd.DataFrame:
    """Estado atual de tema (Postgres) dos artigos que aparecem na auditoria das campanhas."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        df = pd.read_sql_query(THEME_CHANGES_STATE_QUERY, engine, params=(list(campaigns),))
    finally:
        engine.dispose()
    logger.info(f"{len(df)} artigos na auditoria das campanhas {list(campaigns)}")
    return df


def merge_theme_changes(
    db_url: str,
    project_id: str,
    campaigns: Sequence[str] = DEFAULT_CAMPAIGNS,
    dry_run: bool = False,
) -> dict:
    """Staging do estado atual + MERGE no fato (no dry-run, só staging e contagem)."""
    if not campaigns:
        raise ValueError("informe ao menos uma campanha da auditoria")

    stats = {
        "campaigns": list(campaigns),
        "staged": 0,
        "fato_rows_to_update": 0,
        "merged": 0,
        "dry_run": dry_run,
    }
    df = fetch_theme_changes_state(db_url, campaigns)
    if df.empty:
        logger.info("Auditoria vazia para as campanhas: nada a levar ao BigQuery")
        return stats

    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        schema=[
            bigquery.SchemaField("unique_id", "STRING", mode="REQUIRED"),
            *(bigquery.SchemaField(column, "STRING") for column in THEME_COLUMNS),
        ],
    )
    staging_ref = f"{project_id}.{DATASET_ID}.{STAGING_TABLE}"
    client.load_table_from_dataframe(
        df[["unique_id", *THEME_COLUMNS]], staging_ref, job_config=job_config
    ).result()
    stats["staged"] = len(df)

    ((to_update,),) = list(client.query(build_diff_count_sql(project_id)).result())
    stats["fato_rows_to_update"] = int(to_update)

    if not dry_run:
        job = client.query(build_merge_sql(project_id))
        job.result()
        stats["merged"] = int(job.num_dml_affected_rows or 0)

    logger.info(f"MERGE do fato a partir da auditoria: {stats}")
    return stats
