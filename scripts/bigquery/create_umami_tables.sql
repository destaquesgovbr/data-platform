-- Umami Analytics tables for BigQuery
-- Populated by DAG: sync_umami_to_bigquery

-- Pageviews (event_type=1) enriched with session data
CREATE TABLE IF NOT EXISTS dgb_gold.umami_pageviews (
  event_id STRING NOT NULL,
  session_id STRING NOT NULL,
  visit_id STRING,
  created_at TIMESTAMP NOT NULL,
  url_path STRING,
  url_query STRING,
  page_title STRING,
  referrer_domain STRING,
  referrer_path STRING,
  hostname STRING,
  utm_source STRING,
  utm_medium STRING,
  utm_campaign STRING,
  -- Session data (denormalized)
  browser STRING,
  os STRING,
  device STRING,
  country STRING,
  region STRING,
  city STRING,
  language STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY url_path
OPTIONS (
  description = 'Umami pageview events enriched with session data'
);

-- Custom events (event_type=2) with event_data as JSON
CREATE TABLE IF NOT EXISTS dgb_gold.umami_events (
  event_id STRING NOT NULL,
  session_id STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  event_name STRING NOT NULL,
  url_path STRING,
  hostname STRING,
  -- Event data (pivoted from key-value pairs)
  event_data JSON,
  -- Session data (denormalized)
  browser STRING,
  os STRING,
  device STRING,
  country STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY event_name
OPTIONS (
  description = 'Umami custom events with event_data as JSON'
);
