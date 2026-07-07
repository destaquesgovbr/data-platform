#!/bin/bash
# Script de teste rápido da migração com sample pequeno
# Uso: ./test_local.sh

set -e  # Exit on error

echo "🧪 Teste Local de Migração de Embeddings"
echo "========================================"
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar dependências
echo "📦 Verificando dependências..."
if ! python -c "import pandas" 2>/dev/null; then
    echo -e "${RED}❌ pandas não instalado${NC}"
    echo "Instale com: pip install -r requirements.txt"
    exit 1
fi

if ! python -c "import torch" 2>/dev/null; then
    echo -e "${RED}❌ torch não instalado${NC}"
    echo "Instale com: pip install -r requirements.txt"
    exit 1
fi

if ! python -c "import sentence_transformers" 2>/dev/null; then
    echo -e "${RED}❌ sentence-transformers não instalado${NC}"
    echo "Instale com: pip install -r requirements.txt"
    exit 1
fi

echo -e "${GREEN}✅ Dependências OK${NC}"
echo ""

# Verificar GPU
echo "🔍 Verificando GPU..."
if python -c "import torch; print('CUDA available:', torch.cuda.is_available())" | grep -q "True"; then
    GPU_NAME=$(python -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null)
    echo -e "${GREEN}✅ GPU disponível: $GPU_NAME${NC}"
    DEVICE="cuda"
    BATCH_SIZE=128
else
    echo -e "${YELLOW}⚠️  GPU não disponível, usando CPU (será mais lento)${NC}"
    DEVICE="cpu"
    BATCH_SIZE=8
fi
echo ""

# Verificar se existe dump
if [ ! -f "sample_test.parquet" ]; then
    echo "📋 Criando sample de teste..."
    echo ""

    # Criar sample fake se não existir dump real
    python << 'EOF'
import pandas as pd
import numpy as np

# Criar sample fake para teste
data = {
    'id': range(1, 101),
    'unique_id': [f'test-{i:04d}' for i in range(1, 101)],
    'title': [f'Título de Teste {i}' for i in range(1, 101)],
    'summary': [f'Resumo de teste {i} com informações importantes.' for i in range(1, 101)],
    'content': [f'Conteúdo completo do artigo {i}...' for i in range(1, 101)],
}

df = pd.DataFrame(data)
df.to_parquet('sample_test.parquet', index=False)
print(f"✅ Criado sample_test.parquet com {len(df)} artigos")
EOF
else
    echo -e "${GREEN}✅ Usando sample_test.parquet existente${NC}"
fi
echo ""

# Rodar migração
echo "🚀 Executando migração de teste..."
echo "   Device: $DEVICE"
echo "   Batch size: $BATCH_SIZE"
echo ""

python migrate_to_bge_m3.py generate \
    --input sample_test.parquet \
    --output sample_test_embeddings.parquet \
    --device "$DEVICE" \
    --batch-size "$BATCH_SIZE"

echo ""
echo "✅ Migração concluída!"
echo ""

# Verificar resultado
echo "🔍 Verificando resultado..."
python << 'EOF'
import pandas as pd
import numpy as np

df = pd.read_parquet('sample_test_embeddings.parquet')
print(f"Total embeddings: {len(df)}")
print(f"Colunas: {list(df.columns)}")

# Verificar primeira embedding
first_emb = df.iloc[0]['embedding']
print(f"\nPrimeira embedding:")
print(f"  Tipo: {type(first_emb)}")
print(f"  Dimensão: {len(first_emb)}")
print(f"  Primeiros 5 valores: {first_emb[:5]}")

# Verificar se todas têm dimensão 1024
dims = [len(emb) for emb in df['embedding']]
unique_dims = set(dims)
print(f"\nDimensões únicas: {unique_dims}")

if unique_dims == {1024}:
    print("✅ Todas embeddings têm dimensão 1024 (BGE-M3)")
else:
    print(f"❌ Erro: esperado dimensão 1024, encontrado {unique_dims}")
EOF

echo ""
echo "========================================"
echo -e "${GREEN}🎉 Teste concluído com sucesso!${NC}"
echo ""
echo "Arquivos gerados:"
echo "  - sample_test.parquet (input)"
echo "  - sample_test_embeddings.parquet (output)"
echo "  - migration.log (logs)"
echo ""
echo "Próximos passos:"
echo "  1. Fazer dump real do PostgreSQL"
echo "  2. Rodar migração completa na EC2 L4"
echo "  3. Upload para produção"
