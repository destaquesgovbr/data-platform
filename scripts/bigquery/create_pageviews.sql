-- Pageview events table (streaming insert from portal via Pub/Sub)
CREATE TABLE IF NOT EXISTS dgb_gold.pageviews (
  unique_id STRING NOT NULL,
  session_id STRING,
  referrer STRING,
  user_agent STRING,
  country STRING,
  event_timestamp TIMESTAMP NOT NULL,
  ingested_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(event_timestamp)
CLUSTER BY unique_id
OPTIONS (
  description = 'Portal pageview events for engagement analytics',
  require_partition_filter = true
);

-- Materialized view: daily article view counts
-- (BigQuery scheduled queries or DAG will aggregate this)
-- CREATE MATERIALIZED VIEW dgb_gold.mv_daily_views AS
-- SELECT
--   unique_id,
--   DATE(event_timestamp) AS view_date,
--   COUNT(*) AS view_count,
--   COUNT(DISTINCT session_id) AS unique_sessions
-- FROM dgb_gold.pageviews
-- GROUP BY unique_id, DATE(event_timestamp);
