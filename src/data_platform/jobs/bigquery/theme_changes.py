"""MERGE de dgb_gold.fato_noticias a partir da auditoria de temas (news_theme_changes).

A migração 034 (tema 26) e a reclassificação por LLM do DS-1 registram cada mudança de tema
em `news_theme_changes`, uma linha por artigo em cada campanha. Contrato de 22/10: só duas
campanhas, `tema26-llm-d1` (o LLM da D1, source `llm:<model_id>`) e `tema26-034` (a 034,
source `migration-034`), lidas do changed_at mais recente para o mais antigo.

Modo normal (D0, depois da 034 e da BigQuery 002; D1, depois da reclassificação por LLM):
lê os artigos com linha NÃO revertida nas duas campanhas, ordenados pela mudança mais
recente, e leva ao BigQuery o estado ATUAL de tema deles (códigos e rótulos de l1, l2 e
most_specific, os mesmos joins do sync diário) numa tabela de staging (WRITE_TRUNCATE); o
MERGE no fato só toca onde código ou rótulo diverge. O estado vem de `news`, não das colunas
new_* da auditoria, para o fato ficar igual ao Postgres; `diverges_from_audit` conta os
artigos cujo estado atual difere do novo da mudança mais recente (o esperado é 0).

Modo `reverted` (depois do rollback da 034, que só marca reverted_at): lê os artigos com
linha revertida nas duas campanhas, mais toda linha do fato que ainda aponta para o 26
(ex.: artigo que o worker classificou no 26 depois do DS-1, desfeito pelo mapa inverso
sem auditoria), e leva o estado atual deles.

As stats trazem os artigos por campanha (`by_campaign`): no dry-run da D1, `tema26-llm-d1`
tem de aparecer com a contagem do run. Reexecutável; o dry-run grava só a staging e conta as
linhas do fato que mudariam.
"""

import logging
from collections.abc import Sequence

import pandas as pd

logger = logging.getLogger(__name__)

DATASET_ID = "dgb_gold"
FATO_TABLE = "fato_noticias"
STAGING_TABLE = "_stg_news_theme_changes"
# As duas campanhas do contrato (as mesmas THEME26_CAMPAIGNS da migração 034), na ordem em
# que o rollback desfaz: no empate de changed_at, a do LLM é a mais recente.
LLM_CAMPAIGN = "tema26-llm-d1"
THEME26_CAMPAIGNS: tuple[str, ...] = (LLM_CAMPAIGN, "tema26-034")

THEME_COLUMNS: tuple[str, ...] = (
    "theme_l1_code",
    "theme_l1_label",
    "theme_l2_code",
    "theme_l2_label",
    "most_specific_theme_code",
    "most_specific_theme_label",
)

_STATE_COLUMNS = """
        n.unique_id,
        t1.code AS theme_l1_code,
        t1.label AS theme_l1_label,
        t2.code AS theme_l2_code,
        t2.label AS theme_l2_label,
        tm.code AS most_specific_theme_code,
        tm.label AS most_specific_theme_label"""

_THEME_JOINS = """
    LEFT JOIN themes t1 ON n.theme_l1_id = t1.id
    LEFT JOIN themes t2 ON n.theme_l2_id = t2.id
    LEFT JOIN themes tm ON n.most_specific_theme_id = tm.id"""

# Params: (campanhas, campanha do LLM). A mudança mais recente de cada artigo (DISTINCT ON),
# e os artigos do mais recente para o mais antigo.
THEME_CHANGES_STATE_QUERY = f"""
    WITH u AS (
        SELECT DISTINCT ON (unique_id)
            unique_id, changed_at, new_l1_code, new_l2_code, new_most_specific_code
        FROM news_theme_changes
        WHERE campaign = ANY(%s) AND reverted_at IS NULL
        ORDER BY unique_id, changed_at DESC, (campaign = %s) DESC, id DESC
    )
    SELECT{_STATE_COLUMNS},
        (t1.code IS DISTINCT FROM u.new_l1_code
            OR t2.code IS DISTINCT FROM u.new_l2_code
            OR tm.code IS DISTINCT FROM u.new_most_specific_code) AS diverges_from_audit
    FROM u
    JOIN news n ON n.unique_id = u.unique_id{_THEME_JOINS}
    ORDER BY u.changed_at DESC, n.unique_id
"""

# Params: (campanhas,). Depois do rollback da 034.
REVERTED_STATE_QUERY = f"""
    SELECT{_STATE_COLUMNS}
    FROM news n
    JOIN (
        SELECT DISTINCT unique_id FROM news_theme_changes
        WHERE campaign = ANY(%s) AND reverted_at IS NOT NULL
    ) c ON c.unique_id = n.unique_id{_THEME_JOINS}
    ORDER BY n.unique_id
"""

# Params: (unique_ids,). Linhas do fato no 26 fora da auditoria (modo reverted).
STATE_BY_IDS_QUERY = f"""
    SELECT{_STATE_COLUMNS}
    FROM news n{_THEME_JOINS}
    WHERE n.unique_id = ANY(%s)
    ORDER BY n.unique_id
"""


def campaign_counts_query(reverted: bool = False) -> str:
    """Artigos distintos por campanha, com o mesmo filtro de reverted_at do modo."""
    filtro = "reverted_at IS NOT NULL" if reverted else "reverted_at IS NULL"
    return f"""
    SELECT campaign, COUNT(DISTINCT unique_id) AS articles
    FROM news_theme_changes
    WHERE campaign = ANY(%s) AND {filtro}
    GROUP BY campaign
    ORDER BY campaign
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


def build_fato_26_ids_sql(project_id: str) -> str:
    """unique_id das linhas do fato com algum código no 26 (modo reverted)."""
    fato, _ = _tables(project_id)
    predicate = "\n   OR ".join(
        f"REGEXP_CONTAINS(COALESCE({column}, ''), r'^26(\\.|$)')"
        for column in ("theme_l1_code", "theme_l2_code", "most_specific_theme_code")
    )
    return f"""SELECT DISTINCT unique_id
FROM {fato}
WHERE {predicate}
"""


def _read(db_url: str, sql: str, params: tuple) -> pd.DataFrame:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    engine = create_engine(db_url, poolclass=NullPool)
    try:
        return pd.read_sql_query(sql, engine, params=params)
    finally:
        engine.dispose()


def fetch_theme_changes_state(
    db_url: str, campaigns: Sequence[str] = THEME26_CAMPAIGNS, reverted: bool = False
) -> pd.DataFrame:
    """Estado atual de tema (Postgres) dos artigos com linha ativa (ou revertida) na auditoria."""
    if reverted:
        df = _read(db_url, REVERTED_STATE_QUERY, (list(campaigns),))
    else:
        df = _read(db_url, THEME_CHANGES_STATE_QUERY, (list(campaigns), LLM_CAMPAIGN))
    estado = "revertidas" if reverted else "ativas"
    logger.info(f"{len(df)} artigos com linhas {estado} nas campanhas {list(campaigns)}")
    return df


def fetch_state_by_ids(db_url: str, unique_ids: Sequence[str]) -> pd.DataFrame:
    """Estado atual de tema (Postgres) dos unique_id pedidos (os que existem em news)."""
    return _read(db_url, STATE_BY_IDS_QUERY, (list(unique_ids),))


def count_by_campaign(
    db_url: str, campaigns: Sequence[str] = THEME26_CAMPAIGNS, reverted: bool = False
) -> dict[str, int]:
    """Artigos distintos por campanha, linhas ativas (ou revertidas), para o log e o dry-run."""
    df = _read(db_url, campaign_counts_query(reverted=reverted), (list(campaigns),))
    return {str(row.campaign): int(row.articles) for row in df.itertuples(index=False)}


def fetch_fato_26_ids(client, project_id: str) -> list[str]:
    return [row[0] for row in client.query(build_fato_26_ids_sql(project_id)).result()]


def merge_theme_changes(
    db_url: str,
    project_id: str,
    campaigns: Sequence[str] = THEME26_CAMPAIGNS,
    reverted: bool = False,
    dry_run: bool = False,
) -> dict:
    """Staging do estado atual + MERGE no fato (no dry-run, só staging e contagem)."""
    if not campaigns:
        raise ValueError("informe ao menos uma campanha da auditoria")

    stats = {
        "campaigns": list(campaigns),
        "reverted": reverted,
        "by_campaign": count_by_campaign(db_url, campaigns, reverted=reverted),
        "diverges_from_audit": None,
        "fato_26_unique_ids": None,
        "staged": 0,
        "fato_rows_to_update": 0,
        "merged": 0,
        "dry_run": dry_run,
    }
    logger.info(f"Artigos por campanha na auditoria: {stats['by_campaign']}")
    df = fetch_theme_changes_state(db_url, campaigns, reverted=reverted)

    client = None
    if reverted:
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id)
        ids_26 = fetch_fato_26_ids(client, project_id)
        stats["fato_26_unique_ids"] = len(ids_26)
        extra = sorted(set(ids_26) - set(df["unique_id"]))
        if extra:
            df = pd.concat([df, fetch_state_by_ids(db_url, extra)], ignore_index=True)
    else:
        divergent = df["diverges_from_audit"] if "diverges_from_audit" in df else []
        stats["diverges_from_audit"] = int(sum(bool(value) for value in divergent))
        if stats["diverges_from_audit"]:
            logger.warning(
                f"{stats['diverges_from_audit']} artigos com estado atual diferente da mudança "
                "mais recente da auditoria (o fato segue o Postgres)"
            )

    if df.empty:
        logger.info("Nada a levar ao BigQuery para as campanhas")
        return stats

    from google.cloud import bigquery

    client = client or bigquery.Client(project=project_id)
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
