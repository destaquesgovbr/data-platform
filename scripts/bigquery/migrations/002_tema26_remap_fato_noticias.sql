-- Tema 26 "Defesa Civil e Gestão de Desastres" em dgb_gold.fato_noticias (DP-2, D0).
-- Ref: migração Postgres 034_tema26_defesa_civil.py (data-platform, PR do DP-2).
--
-- Remap determinístico por código, igual ao da 034: 19.03* -> 26.01*, 19.04* -> 26.02*,
-- com a hierarquia refeita a partir de uma âncora. O fato só tem theme_l1, theme_l2 e
-- most_specific_theme (código + rótulo); o most_specific faz o papel do L3 (no Postgres,
-- most_specific = coalesce(l3, l2, l1) em 100% do corpus):
--   - âncora = most_specific, a menos que ele e o L2 apontem para L1 diferentes depois do
--     remap E o par L1-L2 seja coerente (pai do L2 = L1): aí o par decide;
--   - novos L1/L2/most_specific = cadeia da âncora remapeada.
-- Ex.: (19, 19.03, 19.03.03) -> (26, 26.01, 26.01.03); (15, 19.04, 19.04.04) -> (26, 26.02,
-- 26.02.04); (19, 19.02, 19.03.01) -> (19, 19.02, 19.02).
-- Rótulos do 26 inline (dim_temas só ganha o 26 no próximo sync_pg_to_bigquery); os demais
-- vêm da própria linha ou de dim_temas.
--
-- Rodar depois da 034 aplicada. A reclassificação por LLM (D1) entra pelo MERGE a partir
-- da auditoria (`data-platform bq-merge-theme-changes`), que também reconcilia com o
-- estado exato do Postgres. Forward-only; reexecutar é no-op (nada mais casa com 19.03/19.04).
UPDATE `inspire-7-finep.dgb_gold.fato_noticias` AS f
SET
    theme_l1_code = s.new_theme_l1_code,
    theme_l1_label = s.new_theme_l1_label,
    theme_l2_code = s.new_theme_l2_code,
    theme_l2_label = s.new_theme_l2_label,
    most_specific_theme_code = s.new_most_specific_theme_code,
    most_specific_theme_label = s.new_most_specific_theme_label
FROM (
    WITH
    rotulos_26 AS (
        SELECT code, label
        FROM UNNEST([
            STRUCT('26' AS code, 'Defesa Civil e Gestão de Desastres' AS label),
            STRUCT('26.01' AS code, 'Defesa Civil' AS label),
            STRUCT('26.01.01' AS code, 'Preparação para Desastres' AS label),
            STRUCT('26.01.02' AS code, 'Planejamento de Evacuação' AS label),
            STRUCT('26.01.03' AS code, 'Resposta a Desastres' AS label),
            STRUCT('26.01.04' AS code, 'Monitoramento de Riscos Naturais' AS label),
            STRUCT('26.01.05' AS code, 'Gestão de Abrigos' AS label),
            STRUCT('26.02' AS code, 'Situações de Emergência' AS label),
            STRUCT('26.02.01' AS code, 'Resgate e Salvamento' AS label),
            STRUCT('26.02.02' AS code, 'Logística de Emergência' AS label),
            STRUCT('26.02.03' AS code, 'Ações Humanitárias' AS label),
            STRUCT('26.02.04' AS code, 'Reconstrução Pós-Desastre' AS label),
            STRUCT('26.02.05' AS code, 'Assistência a Deslocados Internos' AS label)
        ])
    ),

    dim AS (
        SELECT code, ANY_VALUE(label) AS label
        FROM `inspire-7-finep.dgb_gold.dim_temas`
        GROUP BY code
    ),

    alvo AS (
        SELECT
            unique_id,
            theme_l1_code AS l1,
            theme_l2_code AS l2,
            most_specific_theme_code AS ms,
            ANY_VALUE(theme_l1_label) AS l1_label,
            ANY_VALUE(theme_l2_label) AS l2_label,
            ANY_VALUE(most_specific_theme_label) AS ms_label
        FROM `inspire-7-finep.dgb_gold.fato_noticias`
        WHERE
            REGEXP_CONTAINS(COALESCE(theme_l1_code, ''), r'^19\.0[34](\.0[1-5])?$')
            OR REGEXP_CONTAINS(COALESCE(theme_l2_code, ''), r'^19\.0[34](\.0[1-5])?$')
            OR REGEXP_CONTAINS(COALESCE(most_specific_theme_code, ''), r'^19\.0[34](\.0[1-5])?$')
        GROUP BY unique_id, l1, l2, ms
    ),

    remapeado AS (
        SELECT
            *,
            REGEXP_REPLACE(
                REGEXP_REPLACE(l1, r'^19\.03', '26.01'), r'^19\.04', '26.02'
            ) AS l1n,
            REGEXP_REPLACE(
                REGEXP_REPLACE(l2, r'^19\.03', '26.01'), r'^19\.04', '26.02'
            ) AS l2n,
            REGEXP_REPLACE(
                REGEXP_REPLACE(ms, r'^19\.03', '26.01'), r'^19\.04', '26.02'
            ) AS msn
        FROM alvo
    ),

    com_regra AS (
        SELECT
            *,
            msn IS NOT NULL
            AND (
                l2n IS NULL
                OR REGEXP_EXTRACT(msn, r'^[^.]+') = REGEXP_EXTRACT(l2n, r'^[^.]+')
                OR NOT COALESCE(REGEXP_EXTRACT(l2, r'^(.*)\.') = l1, FALSE)
            ) AS usa_ms
        FROM remapeado
    ),

    ancorado AS (
        SELECT
            *,
            COALESCE(IF(usa_ms, msn, l2n), l1n) AS ancora
        FROM com_regra
    ),

    novo AS (
        SELECT
            *,
            REGEXP_EXTRACT(ancora, r'^[^.]+') AS new_l1,
            REGEXP_EXTRACT(ancora, r'^[^.]+\.[^.]+') AS new_l2
        FROM ancorado
    )

    SELECT
        n.unique_id,
        n.l1,
        n.l2,
        n.ms,
        n.new_l1 AS new_theme_l1_code,
        n.new_l2 AS new_theme_l2_code,
        n.ancora AS new_most_specific_theme_code,
        COALESCE(r1.label, IF(n.new_l1 = n.l1, n.l1_label, NULL), d1.label)
            AS new_theme_l1_label,
        COALESCE(r2.label, IF(n.new_l2 = n.l2, n.l2_label, NULL), d2.label)
            AS new_theme_l2_label,
        COALESCE(
            rm.label,
            CASE n.ancora
                WHEN n.ms THEN n.ms_label
                WHEN n.l2 THEN n.l2_label
                WHEN n.l1 THEN n.l1_label
            END,
            dm.label
        ) AS new_most_specific_theme_label
    FROM novo AS n
    LEFT JOIN rotulos_26 AS r1 ON n.new_l1 = r1.code
    LEFT JOIN rotulos_26 AS r2 ON n.new_l2 = r2.code
    LEFT JOIN rotulos_26 AS rm ON n.ancora = rm.code
    LEFT JOIN dim AS d1 ON n.new_l1 = d1.code
    LEFT JOIN dim AS d2 ON n.new_l2 = d2.code
    LEFT JOIN dim AS dm ON n.ancora = dm.code
) AS s
WHERE
    f.unique_id = s.unique_id
    AND COALESCE(f.theme_l1_code, '') = COALESCE(s.l1, '')
    AND COALESCE(f.theme_l2_code, '') = COALESCE(s.l2, '')
    AND COALESCE(f.most_specific_theme_code, '') = COALESCE(s.ms, '');
