-- =============================================================================
-- BigQuery Gold Layer — Table Definitions
-- Dataset: dgb_gold
-- =============================================================================

-- Fact table: one row per news article with denormalized dimensions and features
CREATE TABLE IF NOT EXISTS dgb_gold.fato_noticias (
  unique_id STRING NOT NULL,
  title STRING,
  url STRING,

  -- Agency (denormalized)
  agency_key STRING,
  agency_name STRING,

  -- Theme hierarchy (denormalized)
  theme_l1_code STRING,
  theme_l1_label STRING,
  theme_l2_code STRING,
  theme_l2_label STRING,
  most_specific_theme_code STRING,
  most_specific_theme_label STRING,

  -- Timestamps
  published_at TIMESTAMP NOT NULL,
  extracted_at TIMESTAMP,
  synced_at TIMESTAMP NOT NULL,

  -- Features (from news_features JSONB)
  word_count INT64,
  char_count INT64,
  paragraph_count INT64,
  has_image BOOL,
  has_video BOOL,
  sentiment_score FLOAT64,
  sentiment_label STRING,
  publication_hour INT64,
  publication_dow INT64,
  readability_flesch FLOAT64
)
PARTITION BY DATE(published_at)
CLUSTER BY agency_key, theme_l1_code;


-- Dimension: agencies
CREATE TABLE IF NOT EXISTS dgb_gold.dim_agencias (
  agency_key STRING NOT NULL,
  agency_name STRING,
  agency_type STRING,
  parent_key STRING
);


-- Dimension: themes (hierarchical)
CREATE TABLE IF NOT EXISTS dgb_gold.dim_temas (
  code STRING NOT NULL,
  label STRING,
  full_name STRING,
  level INT64,
  parent_code STRING
);


-- External table over Bronze raw data in GCS
-- Note: BigQuery does not support multiple wildcards, so we use a single * at the end.
-- The Bronze Writer stores files at bronze/news/YYYY/MM/DD/{id}.json but BQ
-- treats nested paths under a single wildcard correctly.
CREATE OR REPLACE EXTERNAL TABLE dgb_gold.raw_news_bronze
OPTIONS (
  format = 'JSON',
  uris = ['gs://inspire-7-finep-dgb-data-lake/bronze/news/*.json']
);
