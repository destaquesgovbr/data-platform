# Integração Typesense Sync no Main Workflow

**Projeto**: DestaquesGovBr Data Platform
**Data**: 2025-12-30
**Status**: 🟡 Pronto para Execução

---

## 📚 Documentação

Este diretório contém toda a documentação necessária para implementar e acompanhar a integração do Typesense sync no main workflow.

### Documentos Principais

| Documento | Propósito | Quando Usar |
|-----------|-----------|-------------|
| **[TS_SYNC_MOVED_TO_MAIN_WORKFL.md](TS_SYNC_MOVED_TO_MAIN_WORKFL.md)** | Plano de execução com tracking detalhado | Durante implementação - marcar checkboxes |
| **[TS_SYNC_EXECUTION_LOG.md](TS_SYNC_EXECUTION_LOG.md)** | Log de cada ação executada | Após cada tarefa - registrar o que foi feito |
| **[TS_SYNC_QUICK_REFERENCE.md](TS_SYNC_QUICK_REFERENCE.md)** | Resumo executivo das mudanças | Consulta rápida - FAQ, cheat sheet |
| **[TS_SYNC_ROLLBACK.md](TS_SYNC_ROLLBACK.md)** | Guia de rollback | Se algo der errado - reverter mudanças |

---

## 🎯 Resumo Executivo

### O Que Estamos Fazendo

Integrar a sincronização diária do Typesense (PostgreSQL → Typesense) no pipeline principal de processamento de notícias.

### Por Que

1. **Consolidação**: Um único pipeline diário ao invés de workflows separados
2. **Consistência**: Garantir que sync sempre roda após enrichment e embeddings
3. **Simplificação**: Remover parâmetro desnecessário (`include_embeddings`)
4. **Manutenibilidade**: Menos workflows para gerenciar

### Mudanças Principais

1. **Código Python**: Remover parâmetro `include_embeddings` (sempre incluir)
2. **Workflows**:
   - ❌ Deletar `typesense-daily-load.yaml`
   - ✏️ Adicionar job `typesense-sync` ao `main-workflow.yaml`
   - 🔄 Renomear e melhorar `typesense-full-reload.yaml`

---

## 🚀 Como Usar Esta Documentação

### Para Executor (Claude ou Humano)

1. **Antes de começar**: Ler [TS_SYNC_MOVED_TO_MAIN_WORKFL.md](TS_SYNC_MOVED_TO_MAIN_WORKFL.md) completamente
2. **Durante execução**:
   - Marcar checkboxes no tracking principal
   - Registrar cada ação no [TS_SYNC_EXECUTION_LOG.md](TS_SYNC_EXECUTION_LOG.md)
3. **Após cada fase**: Commit e teste conforme descrito
4. **Se houver problemas**: Consultar [TS_SYNC_ROLLBACK.md](TS_SYNC_ROLLBACK.md)

### Para Revisor

1. Consultar [TS_SYNC_QUICK_REFERENCE.md](TS_SYNC_QUICK_REFERENCE.md) para entender mudanças
2. Verificar [TS_SYNC_EXECUTION_LOG.md](TS_SYNC_EXECUTION_LOG.md) para ver o que foi feito
3. Revisar checkboxes no [TS_SYNC_MOVED_TO_MAIN_WORKFL.md](TS_SYNC_MOVED_TO_MAIN_WORKFL.md)

### Para Desenvolvedores Futuros

1. **Entender o que mudou**: [TS_SYNC_QUICK_REFERENCE.md](TS_SYNC_QUICK_REFERENCE.md)
2. **Ver histórico**: [TS_SYNC_EXECUTION_LOG.md](TS_SYNC_EXECUTION_LOG.md)
3. **Reverter se necessário**: [TS_SYNC_ROLLBACK.md](TS_SYNC_ROLLBACK.md)

---

## 📋 Checklist Rápido (Antes de Começar)

- [ ] Ler documentação completa
- [ ] Fazer backup do repositório: `git clone ...` em local separado
- [ ] Anotar commit atual: `git rev-parse HEAD > _plan/COMMIT_ANTES_MUDANCAS.txt`
- [ ] Verificar branch está limpa: `git status`
- [ ] Confirmar que está na branch correta: `git branch --show-current`
- [ ] Executar testes atuais: `poetry run pytest`
- [ ] Verificar workflows atuais funcionam: GitHub Actions

---

## 🗂️ Estrutura do Plano

### Fase 1: Refatoração de Código Python (3 arquivos)

**Arquivos modificados**:
- `src/data_platform/managers/postgres_manager.py`
- `src/data_platform/jobs/typesense/sync_job.py`
- `src/data_platform/cli.py`

**Mudança**: Remover parâmetro `include_embeddings` (sempre incluir embeddings)

**Impacto**: Baixo - Não afeta workflows

**Duração estimada**: 30 min

### Fase 2: Workflow de Manutenção (1 arquivo)

**Arquivos modificados**:
- `.github/workflows/typesense-full-reload.yaml` → `typesense-maintenance-sync.yaml`

**Mudança**: Renomear e adicionar mais opções (batch_size, max_records, operation_type)

**Impacto**: Baixo - Workflow manual

**Duração estimada**: 20 min

### Fase 3: Integração no Main Workflow (2 arquivos)

**Arquivos modificados**:
- `.github/workflows/main-workflow.yaml` - Adicionar job `typesense-sync`
- `.github/workflows/typesense-daily-load.yaml` - **DELETAR**

**Mudança**: Integrar sync no pipeline principal, deletar workflow independente

**Impacto**: Alto - Muda pipeline de produção

**Duração estimada**: 30 min

### Testes e Validação

**Duração estimada**: 40 min

**Total**: ~2 horas

---

## 📊 Status Atual

Consultar [TS_SYNC_MOVED_TO_MAIN_WORKFL.md](TS_SYNC_MOVED_TO_MAIN_WORKFL.md) seção "Status Geral" para progresso atualizado.

**Última atualização**: 2025-12-30

---

## 🔗 Links Úteis

### Arquivos Relevantes do Projeto

**Código Python**:
- [src/data_platform/cli.py](../src/data_platform/cli.py)
- [src/data_platform/managers/postgres_manager.py](../src/data_platform/managers/postgres_manager.py)
- [src/data_platform/jobs/typesense/sync_job.py](../src/data_platform/jobs/typesense/sync_job.py)

**Workflows**:
- [.github/workflows/main-workflow.yaml](../.github/workflows/main-workflow.yaml)
- [.github/workflows/typesense-full-reload.yaml](../.github/workflows/typesense-full-reload.yaml)
- [.github/workflows/typesense-daily-load.yaml](../.github/workflows/typesense-daily-load.yaml)

### Documentação Relacionada

- [bateria-testes-integracao.md](./bateria-testes-integracao.md) - Testes de integração do pipeline

---

## ⚠️ Avisos Importantes

### Breaking Changes

1. **Código Python**: `include_embeddings` parâmetro removido
   - Código que passa `include_embeddings=False` vai quebrar
   - Fix: Remover argumento (embeddings sempre incluídos agora)

2. **Horário do sync**: Muda de 10h UTC para 4h UTC
   - Sync agora roda dentro do main-workflow diário
   - Comunicar ao time sobre mudança de horário

3. **Workflow deletado**: `typesense-daily-load.yaml` não existe mais
   - Scripts que invocam este workflow vão quebrar
   - Fix: Usar `typesense-maintenance-sync.yaml` ao invés

### Riscos

- **Pipeline de produção afetado**: Mudanças na Fase 3 afetam pipeline principal
- **Mitigação**: Testar cada fase, fazer rollback se necessário

---

## 📞 Suporte

### Em Caso de Problemas

1. **Durante execução**: Consultar [TS_SYNC_ROLLBACK.md](TS_SYNC_ROLLBACK.md)
2. **Problemas com código**: Ver [TS_SYNC_EXECUTION_LOG.md](TS_SYNC_EXECUTION_LOG.md) para histórico
3. **Dúvidas rápidas**: [TS_SYNC_QUICK_REFERENCE.md](TS_SYNC_QUICK_REFERENCE.md) FAQ

### Contatos

- **Issues**: GitHub Issues do projeto
- **Executor**: Claude Sonnet 4.5
- **Revisor**: _pending_

---

## ✅ Critérios de Sucesso

- [ ] Todas as tarefas do tracking marcadas como concluídas
- [ ] 3 commits criados (1 por fase)
- [ ] 3 testes de validação passando
- [ ] Main-workflow executa com sucesso incluindo typesense-sync
- [ ] Pipeline-summary reporta status de 7 jobs (incluindo typesense-sync)
- [ ] CLI `sync-typesense` funciona sem `--include-embeddings`
- [ ] Workflow `typesense-maintenance-sync.yaml` funciona com novos inputs
- [ ] Workflow `typesense-daily-load.yaml` não existe mais

---

## 📅 Timeline

| Fase | Duração | Status | Início | Fim |
|------|---------|--------|--------|-----|
| Preparação | 10 min | ⬜ | _pending_ | _pending_ |
| Fase 1 | 30 min | ⬜ | _pending_ | _pending_ |
| Fase 2 | 20 min | ⬜ | _pending_ | _pending_ |
| Fase 3 | 30 min | ⬜ | _pending_ | _pending_ |
| Testes | 40 min | ⬜ | _pending_ | _pending_ |
| **Total** | **2h 10min** | **⬜** | _pending_ | _pending_ |

---

## 🎓 Aprendizados e Melhorias

### Após Conclusão

- [ ] Documentar lições aprendidas
- [ ] Atualizar este README com insights
- [ ] Arquivar documentos de planejamento
- [ ] Criar post-mortem se houve problemas

### Feedback Loop

- [ ] O que funcionou bem?
- [ ] O que poderia ser melhorado?
- [ ] Como evitar problemas similares no futuro?

---

**Última Atualização**: 2025-12-30
**Versão**: 1.0
**Status**: 🟡 Documentação Completa - Aguardando Execução

---

## 🚦 Próximo Passo

➡️ Abrir [TS_SYNC_MOVED_TO_MAIN_WORKFL.md](TS_SYNC_MOVED_TO_MAIN_WORKFL.md) e começar pela Fase 1, Tarefa 1.1
