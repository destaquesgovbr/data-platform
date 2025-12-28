# Registro de Decisões

> Documentação das decisões tomadas durante o planejamento da migração.

## Decisões Confirmadas

### 1. Docker-compose Only (Local)

**Decisão**: Usar apenas docker-compose para desenvolvimento local. Descartar `run-typesense-server.sh`.

**Justificativa**:
- Produção usa systemd na VM GCP, não Docker
- O script shell era apenas para conveniência local
- Docker-compose já está configurado no data-platform

**Data**: 2025-12-28

---

### 2. Descartar typesense_sync.py Existente

**Decisão**: Deletar `src/data_platform/jobs/embeddings/typesense_sync.py` e usar código do repo typesense.

**Justificativa**:
- O código do typesense repo é mais completo e testado
- typesense_sync.py foi criado antes da estrutura do repo typesense
- Evita duplicação de lógica

**Data**: 2025-12-28

---

### 3. Dockerfiles em Subdiretórios

**Decisão**: Organizar Dockerfiles em `docker/postgres/` e `docker/typesense/`.

**Justificativa**:
- Melhor organização para múltiplos containers
- Facilita manutenção separada
- Padrão comum em monorepos

**Data**: 2025-12-28

---

### 4. Descartar web-ui/

**Decisão**: Não migrar o diretório `web-ui/` do repo typesense.

**Justificativa**:
- Interface web não é necessária no data-platform
- Portal já tem sua própria interface de busca
- Reduz complexidade da migração

**Data**: 2025-12-28

---

### 5. Remover Leitura do HuggingFace

**Decisão**: Não copiar `dataset.py`. Ler dados apenas do PostgreSQL.

**Justificativa**:
- PostgreSQL é a fonte única de verdade
- HuggingFace era usado apenas para testes/desenvolvimento
- Simplifica o código e elimina dependência externa

**Data**: 2025-12-28

---

### 6. Renomear docker-build.yaml

**Decisão**: Renomear para `postgres-docker-build.yaml`.

**Justificativa**:
- Distinguir claramente do `typesense-docker-build.yaml`
- Nome reflete o propósito (build do container PostgreSQL)
- Evita confusão entre workflows

**Data**: 2025-12-28

---

### 7. CLAUDE.md Único

**Decisão**: Manter apenas um CLAUDE.md na raiz do repositório.

**Justificativa**:
- Evita informações duplicadas/desatualizadas
- Facilita manutenção
- Contexto unificado para o LLM

**Data**: 2025-12-28

---

### 8. Adicionar Campo content_embedding

**Decisão**: Incluir campo `content_embedding` (float[], 768 dimensões) no schema do Typesense.

**Justificativa**:
- Necessário para busca semântica
- Embeddings gerados pelo pipeline de processamento
- 768 dimensões corresponde ao modelo usado (BGE-M3 ou similar)

**Data**: 2025-12-28

---

### 9. Mover Dockerfile Existente

**Decisão**: Mover `Dockerfile` da raiz para `docker/postgres/Dockerfile`.

**Justificativa**:
- Consistência com nova organização
- Separa claramente os containers
- Workflow precisa ser atualizado com novo path

**Data**: 2025-12-28

---

## Decisões Pendentes

> Adicione aqui decisões que ainda precisam ser tomadas durante a execução.

---

## Arquivos Descartados (Não Migrar)

| Arquivo | Motivo |
|---------|--------|
| `web-ui/` | Interface web não necessária |
| `run-typesense-server.sh` | Usar docker-compose |
| `MCP-ANALYSIS.md` | Documento de análise temporário |
| `MCP-SERVER-STATUS.md` | Status temporário |
| `init-typesense.py` | Script de inicialização obsoleto |
| `test_init_typesense.py` | Teste do script obsoleto |
| `DEBUG_PLAN.md` | Documento de debug temporário |
| `WEEKLY_INDEX_OPTIMIZATION.md` | Análise específica não necessária |
| `dataset.py` | Leitura do HuggingFace descartada |
| `CLAUDE.md` (do typesense) | Manter apenas o da raiz |
| `typesense_sync.py` (do data-platform) | Substituído pelo código do typesense |
