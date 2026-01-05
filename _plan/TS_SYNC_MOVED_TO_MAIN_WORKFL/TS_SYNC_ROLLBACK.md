# Rollback Guide: Typesense Sync Integration

**Propósito**: Instruções para reverter as mudanças caso algo dê errado.

---

## 🔙 Estratégia de Rollback

### Opção 1: Rollback Completo (Git Revert)

**Quando usar**: Se todas as 3 fases foram aplicadas e há problemas graves.

```bash
# Identificar commits das 3 fases
git log --oneline -10

# Reverter Fase 3 (workflows)
git revert <commit-hash-fase-3>

# Reverter Fase 2 (maintenance workflow)
git revert <commit-hash-fase-2>

# Reverter Fase 1 (código Python)
git revert <commit-hash-fase-1>

# Push
git push origin main
```

**Resultado**: Código e workflows voltam ao estado anterior.

---

### Opção 2: Rollback Parcial (Por Fase)

#### Reverter apenas Fase 3 (Manter refatorações)

**Cenário**: typesense-sync no main-workflow tem problemas, mas código Python está OK.

```bash
# Recriar typesense-daily-load.yaml do histórico
git show <commit-antes-fase-3>:.github/workflows/typesense-daily-load.yaml > .github/workflows/typesense-daily-load.yaml

# Remover typesense-sync do main-workflow
# (Editar .github/workflows/main-workflow.yaml manualmente)
# Remover:
#   - Job typesense-sync (linhas ~288-~350)
#   - typesense-sync do needs do pipeline-summary
#   - typesense-sync do status report
#   - typesense-sync da validação do if

# Commit
git add .github/workflows/
git commit -m "revert: remove typesense-sync from main workflow

Restore typesense-daily-load.yaml and remove typesense-sync integration
from main-workflow due to [REASON].

Refs: #issue-number"

git push origin main
```

**Resultado**: Volta ao modelo anterior (sync independente às 10h UTC).

#### Reverter apenas Fase 2 (Renomear de volta)

**Cenário**: Problemas com novo workflow de manutenção.

```bash
# Renomear de volta
git mv .github/workflows/typesense-maintenance-sync.yaml .github/workflows/typesense-full-reload.yaml

# Restaurar conteúdo original
git show <commit-antes-fase-2>:.github/workflows/typesense-full-reload.yaml > .github/workflows/typesense-full-reload.yaml

# Commit
git add .github/workflows/typesense-full-reload.yaml
git commit -m "revert: restore original typesense-full-reload workflow

Rollback maintenance-sync enhancements due to [REASON].

Refs: #issue-number"

git push origin main
```

**Resultado**: Workflow de manutenção volta ao estado original.

#### Reverter apenas Fase 1 (include_embeddings de volta)

**Cenário**: Problemas com remoção de `include_embeddings` (muito improvável).

```bash
# Reverter commits específicos
git revert <commit-hash-fase-1>

# Ou restaurar arquivos individualmente
git checkout <commit-antes-fase-1> -- src/data_platform/managers/postgres_manager.py
git checkout <commit-antes-fase-1> -- src/data_platform/jobs/typesense/sync_job.py
git checkout <commit-antes-fase-1> -- src/data_platform/cli.py

# Commit
git add src/data_platform/
git commit -m "revert: restore include_embeddings parameter

Rollback include_embeddings removal due to [REASON].

Refs: #issue-number"

git push origin main
```

**Resultado**: Parâmetro `include_embeddings` volta a existir.

---

## 🚨 Rollback de Emergência (Produção Quebrada)

### Cenário: Pipeline de produção falhando após Fase 3

**Sintoma**: Main-workflow falhando no job `typesense-sync`.

**Solução Rápida (5 minutos)**:

```bash
# 1. Editar main-workflow.yaml
vim .github/workflows/main-workflow.yaml

# 2. Comentar job typesense-sync (adicionar # em todas as linhas do job)
#  typesense-sync:
#    name: Sync to Typesense
#    ...

# 3. Remover typesense-sync do needs do pipeline-summary
# De:
needs: [setup-dates, scraper, ebc-scraper, upload-to-cogfy, enrich-themes, generate-embeddings, typesense-sync]
# Para:
needs: [setup-dates, scraper, ebc-scraper, upload-to-cogfy, enrich-themes, generate-embeddings]

# 4. Remover typesense-sync do status report e validação
# (Remover linhas que mencionam typesense-sync)

# 5. Commit emergencial
git add .github/workflows/main-workflow.yaml
git commit -m "hotfix: disable typesense-sync job temporarily

Pipeline failing at typesense-sync step. Disabling temporarily
while investigating issue.

Refs: #emergency-issue"

git push origin main

# 6. Disparar workflow manualmente para verificar
gh workflow run main-workflow.yaml
```

**Tempo de recuperação**: ~5 minutos (tempo de CI/CD para deploy)

**Próximos passos**:
1. Investigar causa do problema no typesense-sync
2. Fixar issue
3. Reativar job (descomentar)
4. Monitorar

---

## 📝 Checklist de Rollback

### Antes de Reverter

- [ ] Identificar qual fase causou o problema
- [ ] Documentar sintomas e logs de erro
- [ ] Decidir escopo do rollback (completo, parcial, emergencial)
- [ ] Avisar time sobre rollback iminente
- [ ] Ter backup dos commits (hashes registrados)

### Durante Rollback

- [ ] Executar comandos de rollback apropriados
- [ ] Verificar git status após cada mudança
- [ ] Testar localmente se possível
- [ ] Criar commit de rollback descritivo
- [ ] Push para remote

### Depois de Reverter

- [ ] Verificar que workflows voltaram ao normal
- [ ] Monitorar próxima execução do pipeline
- [ ] Documentar causa raiz do problema
- [ ] Planejar fix para tentar novamente
- [ ] Atualizar EXECUTION_LOG.md com informações do rollback

---

## 🔍 Diagnóstico Rápido

### Como saber qual fase causou o problema?

| Sintoma | Provável Causa | Rollback Sugerido |
|---------|----------------|-------------------|
| CLI `sync-typesense` quebrado | Fase 1 (Python) | Reverter Fase 1 |
| Workflow "Typesense Maintenance Sync" não funciona | Fase 2 (Workflow manutenção) | Reverter Fase 2 |
| Main-workflow falhando no typesense-sync | Fase 3 (Main workflow) | Rollback emergencial ou Fase 3 |
| Pipeline completo travado | Fase 3 (Main workflow) | Rollback emergencial |
| Tests falhando | Fase 1 (Python) | Reverter Fase 1 |

---

## 🧪 Testes Após Rollback

### Após Reverter Fase 1

```bash
# Verificar que include_embeddings voltou
poetry run data-platform sync-typesense --help | grep include-embeddings

# Deve mostrar:
# --include-embeddings / --no-include-embeddings
```

### Após Reverter Fase 2

```bash
# Verificar que workflow original voltou
gh workflow list | grep "Typesense Full Data Reload"

# Verificar que novo workflow não existe
gh workflow list | grep "Typesense Maintenance Sync"
# (Não deve retornar nada)
```

### Após Reverter Fase 3

```bash
# Verificar que daily-load existe
gh workflow list | grep "Typesense Daily Incremental Load"

# Verificar jobs do main-workflow
gh api repos/destaquesgovbr/data-platform/actions/workflows/main-workflow.yaml | jq '.jobs'
# typesense-sync NÃO deve aparecer
```

---

## 📞 Contatos de Emergência

### Se o rollback não funcionar

1. **Revert do revert**: `git revert HEAD` (desfaz rollback)
2. **Force push histórico limpo**: `git reset --hard <commit-antes-mudanças> && git push --force`
   - ⚠️ **PERIGOSO**: Só fazer se ninguém mais trabalhou no repo
3. **Abrir issue no GitHub**: Documentar problema e pedir ajuda
4. **Restaurar backup manual**: Se existe backup do código

---

## 🎯 Prevenção de Problemas

### Antes de Aplicar o Plano

- [ ] Fazer backup local: `git clone` do repo em diretório separado
- [ ] Anotar commit hash atual: `git rev-parse HEAD`
- [ ] Testar mudanças localmente antes de push
- [ ] Fazer cada fase em PR separado (ao invés de direto na main)
- [ ] Pedir review de outro desenvolvedor

### Durante Aplicação

- [ ] Commitar cada fase separadamente (não fazer tudo de uma vez)
- [ ] Testar após cada commit
- [ ] Monitorar workflows após push
- [ ] Manter EXECUTION_LOG.md atualizado

---

## 📚 Referências de Commits

### Commits do Plano Original

| Fase | Commit Hash | Data | Mensagem |
|------|-------------|------|----------|
| Fase 1 | `_pending_` | _date_ | refactor: remove include_embeddings parameter |
| Fase 2 | `_pending_` | _date_ | feat: enhance typesense maintenance workflow |
| Fase 3 | `_pending_` | _date_ | feat: integrate typesense sync into main workflow |

### Commits de Rollback (se aplicável)

| Data | Commit Hash | Escopo | Razão |
|------|-------------|--------|-------|
| _date_ | `_pending_` | _scope_ | _reason_ |

---

## 📋 Template de Mensagem de Rollback

```
revert: [título descritivo do que foi revertido]

[Descrição detalhada do problema que motivou o rollback]

Symptoms:
- [Sintoma 1]
- [Sintoma 2]

Root cause:
[Causa raiz identificada ou "under investigation"]

Impact:
- [Impacto no sistema]
- [Impacto nos usuários]

Rollback scope:
[Completo / Fase X / Emergencial]

Next steps:
1. [Próximo passo 1]
2. [Próximo passo 2]

Refs: #issue-number
Reverts: commit-hash-do-original
```

---

## ✅ Checklist de Sucesso do Rollback

- [ ] Código revertido para estado funcional
- [ ] Workflows executando sem erros
- [ ] Testes passando
- [ ] Documentação atualizada (EXECUTION_LOG.md)
- [ ] Time notificado sobre rollback
- [ ] Post-mortem agendado
- [ ] Fix planejado para tentar novamente

---

**Última Atualização**: 2025-12-30
**Status**: Pronto para uso
**Severidade**: CRÍTICO (usar apenas se necessário)
