#!/bin/bash
# Setup PostgreSQL local para teste de migração
# Restaura dump, aplica migration 004, e prepara dados para teste

set -e

echo "🗄️  Setup PostgreSQL Local para Teste de Migração"
echo "=================================================="
echo ""

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configuração
DB_NAME="govbrnews_test"
DUMP_FILE="../../data_dump/Cloud_SQL_Export_2026-06-15 (16_44_06).sql"

# Detectar usuário PostgreSQL disponível
if psql -U "$USER" -l > /dev/null 2>&1; then
    DB_USER="$USER"
elif psql -U postgres -l > /dev/null 2>&1; then
    DB_USER="postgres"
else
    echo -e "${RED}❌ Nenhum usuário PostgreSQL encontrado${NC}"
    echo "Crie um usuário com: sudo -u postgres createuser -s $USER"
    exit 1
fi

echo "📋 Configuração:"
echo "  Database: $DB_NAME"
echo "  User: $DB_USER"
echo "  Dump: $DUMP_FILE"
echo ""

# Verificar se dump existe
if [ ! -f "$DUMP_FILE" ]; then
    echo -e "${RED}❌ Dump não encontrado: $DUMP_FILE${NC}"
    exit 1
fi

# Verificar se PostgreSQL está rodando
if ! pg_isready -q; then
    echo -e "${RED}❌ PostgreSQL não está rodando${NC}"
    echo "Inicie com: sudo systemctl start postgresql"
    exit 1
fi

echo -e "${GREEN}✅ PostgreSQL está rodando${NC}"
echo ""

# Criar banco de testes (se não existir)
echo "🔧 Criando banco de testes..."
if psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo -e "${YELLOW}⚠️  Banco $DB_NAME já existe${NC}"
    read -p "Deseja recriar? (isso apagará todos os dados) [y/N]: " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Dropando banco existente..."
        dropdb -U "$DB_USER" "$DB_NAME" || true
        createdb -U "$DB_USER" "$DB_NAME"
        echo -e "${GREEN}✅ Banco recriado${NC}"
    else
        echo "Usando banco existente"
    fi
else
    createdb -U "$DB_USER" "$DB_NAME"
    echo -e "${GREEN}✅ Banco $DB_NAME criado${NC}"
fi
echo ""

# Ativar pgvector
echo "🔧 Ativando extensão pgvector..."
psql -U "$DB_USER" "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" > /dev/null
echo -e "${GREEN}✅ pgvector ativado${NC}"
echo ""

# Restaurar dump
echo "📦 Restaurando dump (isso pode demorar 10-15 minutos)..."
echo "  Dump size: $(du -h "$DUMP_FILE" | cut -f1)"
echo ""

# Restaurar (com ou sem pv)
if command -v pv &> /dev/null; then
    # Com progress bar
    pv "$DUMP_FILE" | psql -U "$DB_USER" "$DB_NAME" > /dev/null 2>&1
    RESTORE_STATUS=$?
else
    # Sem progress bar (mas funciona!)
    echo "  (pv não instalado, restaurando sem progress bar...)"
    psql -U "$DB_USER" "$DB_NAME" < "$DUMP_FILE" > /dev/null 2>&1
    RESTORE_STATUS=$?
fi

if [ $RESTORE_STATUS -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ Dump restaurado com sucesso${NC}"
else
    echo ""
    echo -e "${RED}❌ Erro ao restaurar dump (exit code: $RESTORE_STATUS)${NC}"
    echo "Tente manualmente: psql -U $DB_USER $DB_NAME < \"$DUMP_FILE\""
    exit 1
fi
echo ""

# Verificar dados
echo "🔍 Verificando dados restaurados..."
psql -U "$DB_USER" "$DB_NAME" << 'EOF'
\echo '  Tables:'
SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;

\echo ''
\echo '  News count:'
SELECT COUNT(*) as total_news FROM news;

\echo ''
\echo '  Embedding status:'
SELECT
    CASE
        WHEN embedding_model_version IS NULL AND content_embedding IS NULL THEN 'no_embedding'
        WHEN embedding_model_version IS NULL THEN 'legacy_unnamed'
        ELSE embedding_model_version
    END as status,
    COUNT(*) as count
FROM news
GROUP BY status
ORDER BY count DESC;
EOF

echo ""
echo -e "${GREEN}✅ Dados verificados${NC}"
echo ""

# Aplicar migration 004
echo "🔄 Aplicando Migration 004 (BGE-M3)..."
psql -U "$DB_USER" "$DB_NAME" < ../../scripts/migrations/004_add_bge_m3_columns.sql

echo ""
echo -e "${GREEN}✅ Migration aplicada${NC}"
echo ""

# Verificar schema atualizado
echo "🔍 Verificando schema atualizado..."
psql -U "$DB_USER" "$DB_NAME" << 'EOF'
\echo '  Colunas da tabela news relacionadas a embeddings:'
SELECT
    column_name,
    data_type,
    CASE
        WHEN data_type = 'USER-DEFINED' THEN udt_name
        ELSE ''
    END as vector_info
FROM information_schema.columns
WHERE table_name = 'news'
  AND column_name LIKE '%embedding%'
ORDER BY column_name;

\echo ''
\echo '  Status pós-migration:'
SELECT
    embedding_model_version,
    COUNT(*) as count,
    CASE WHEN content_embedding IS NULL THEN 'NULL' ELSE 'SET' END as new_embedding,
    CASE WHEN content_embedding_legacy IS NULL THEN 'NULL' ELSE 'SET' END as legacy_embedding
FROM news
GROUP BY embedding_model_version, content_embedding IS NULL, content_embedding_legacy IS NULL
ORDER BY count DESC;
EOF

echo ""
echo "=================================================="
echo -e "${GREEN}🎉 Setup completo!${NC}"
echo ""
echo "📋 Próximos passos:"
echo ""
echo "1. Exportar artigos para migração:"
echo "   psql $DB_NAME < dump_articles_for_migration.sql"
echo ""
echo "2. Converter para Parquet:"
echo "   python csv_to_parquet.py /tmp/artigos_para_migrar.csv --sample 1000"
echo ""
echo "3. Testar migração de embeddings:"
echo "   python migrate_to_bge_m3.py generate \\"
echo "       --input artigos_para_migrar.parquet \\"
echo "       --output embeddings_test.parquet"
echo ""
echo "4. Upload de volta para o banco:"
echo "   export DATABASE_URL='postgresql:///$DB_NAME'"
echo "   python migrate_to_bge_m3.py upload \\"
echo "       --input embeddings_test.parquet \\"
echo "       --database-url \$DATABASE_URL"
echo ""
echo "Database connection:"
echo "  psql $DB_NAME"
echo "  export DATABASE_URL='postgresql:///$DB_NAME'"
