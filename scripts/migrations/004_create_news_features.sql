-- 004_create_news_features.sql
-- Feature Store: armazena features computadas para cada notícia (JSONB flexível)

CREATE TABLE IF NOT EXISTS news_features (
    unique_id VARCHAR(120) PRIMARY KEY REFERENCES news(unique_id) ON DELETE CASCADE,
    features JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Índice GIN para queries em campos específicos do JSONB
-- Ex: SELECT * FROM news_features WHERE features @> '{"sentiment": {"label": "positive"}}'
CREATE INDEX IF NOT EXISTS idx_news_features_gin ON news_features USING GIN (features);

-- Índice para ordenação por data de atualização
CREATE INDEX IF NOT EXISTS idx_news_features_updated_at ON news_features (updated_at DESC);

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_news_features_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_news_features_updated_at
    BEFORE UPDATE ON news_features
    FOR EACH ROW
    EXECUTE FUNCTION update_news_features_updated_at();
