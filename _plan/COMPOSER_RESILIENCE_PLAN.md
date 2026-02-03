# Plano de Resiliência do Cloud Composer

> **Data**: 2026-02-03
> **Status**: Planejamento
> **Problema**: DAGs desaparecem após redeploys do Composer

---

## Resumo Executivo

O Cloud Composer está sofrendo recriações não planejadas que resultam em perda das DAGs. Isso acontece porque:
1. O bucket de DAGs é **recriado junto com o ambiente** (novo hash)
2. Não há automação para **re-deploy das DAGs** após recriação
3. O `prevent_destroy = false` permite destruições acidentais
4. Não há **monitoramento ou alertas** para detectar recriações

Este plano propõe melhorias em 4 frentes: Prevenção, Automação, Monitoramento e Documentação.

---

## Diagnóstico do Problema

### Arquitetura Atual

```
┌─────────────────────────────────────────────────────────────────┐
│                         Infra Repo                              │
│  terraform-apply.yml                                            │
│        │                                                        │
│        ▼                                                        │
│  ┌──────────────┐                                               │
│  │  Terraform   │──── Pode recriar ────▶ Cloud Composer         │
│  │   Apply      │                           │                   │
│  └──────────────┘                           ▼                   │
│                                    Novo Bucket de DAGs          │
│                                    gs://...-{NOVO_HASH}-bucket  │
│                                                                 │
│                          ❌ Não há comunicação                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   │ (manual)
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data-Platform Repo                         │
│                                                                 │
│  composer-deploy-dags.yaml                                      │
│        │                                                        │
│        ▼                                                        │
│  ┌──────────────┐     ┌──────────────┐                          │
│  │   Descobre   │────▶│   gsutil     │────▶ Deploy DAGs         │
│  │   Bucket     │     │   rsync      │                          │
│  │  (dinâmico)  │     └──────────────┘                          │
│  └──────────────┘                                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Problemas Identificados

| # | Problema | Impacto | Severidade |
|---|----------|---------|------------|
| 1 | `prevent_destroy = false` no Terraform | Composer pode ser destruído por engano | ALTA |
| 2 | Sem trigger automático para re-deploy de DAGs | DAGs somem após recriação | ALTA |
| 3 | Sem alertas de recriação do Composer | Time só descobre quando DAGs somem | MÉDIA |
| 4 | Sem validação periódica de DAGs | Problemas podem passar despercebidos | MÉDIA |
| 5 | Dependência de `ignore_changes` para `ip_allocation_policy` | Workaround frágil | BAIXA |

### Causas de Recriação do Composer

1. **Mudanças em campos imutáveis** (network, subnetwork, name, region)
2. **Bug do provider v6.x** com `ip_allocation_policy` (mitigado com `ignore_changes`)
3. **Terraform destroy acidental** (sem `prevent_destroy = true`)
4. **Upgrade de image_version** que requer recriação
5. **Mudanças em GKE interno** (raro, mas possível)

---

## Soluções Propostas

### Fase 1: Prevenção de Recriações (Prioridade Alta)

#### 1.1 Ativar `prevent_destroy = true`

**Arquivo**: `/infra/terraform/composer.tf`

**Mudança**:
```hcl
lifecycle {
  prevent_destroy = true  # Era false

  ignore_changes = [
    config[0].software_config[0].image_version,
    config[0].node_config[0].ip_allocation_policy,
  ]
}
```

**Benefício**: Terraform recusa destruir o Composer, exigindo remoção manual desta flag para destruições intencionais.

**Risco**: Se precisarmos realmente destruir, teremos que editar o código primeiro.

#### 1.2 Adicionar Validação no Terraform Plan

**Arquivo**: `/infra/.github/workflows/terraform-apply.yml`

**Mudança**: Adicionar step que falha se detectar `must be replaced` para o Composer:

```yaml
- name: Block Composer replacement
  run: |
    if grep -q "google_composer_environment.main must be replaced" terraform/plan_output.txt; then
      echo "::error::BLOQUEADO: Terraform quer recriar o Composer!"
      echo "::error::Isso causará perda das DAGs. Revise o plano."
      exit 1
    fi
```

**Benefício**: CI/CD falha automaticamente se houver tentativa de recriação.

---

### Fase 2: Automação de Re-deploy (Prioridade Alta)

#### 2.1 Cross-Repository Dispatch

Quando o Terraform apply for bem-sucedido E envolver mudanças no Composer, disparar automaticamente o deploy das DAGs.

**Arquivo**: `/infra/.github/workflows/terraform-apply.yml`

**Adicionar após `terraform apply`**:

```yaml
- name: Check if Composer changed
  id: composer_changed
  run: |
    if grep -E "google_composer_environment|composer" terraform/plan_output.txt | grep -q "will be"; then
      echo "changed=true" >> $GITHUB_OUTPUT
    else
      echo "changed=false" >> $GITHUB_OUTPUT
    fi

- name: Trigger DAGs Deploy
  if: steps.composer_changed.outputs.changed == 'true'
  uses: peter-evans/repository-dispatch@v3
  with:
    token: ${{ secrets.CROSS_REPO_PAT }}
    repository: destaquesgovbr/data-platform
    event-type: composer-changed
    client-payload: '{"trigger": "terraform-apply", "ref": "${{ github.sha }}"}'
```

**Arquivo**: `/data-platform/.github/workflows/composer-deploy-dags.yaml`

**Adicionar trigger**:

```yaml
on:
  push:
    branches:
      - main
    paths:
      - 'src/data_platform/dags/**'
  workflow_dispatch:
    inputs:
      test_connections:
        description: 'Test Airflow connections after deploy'
        required: false
        default: false
        type: boolean
  repository_dispatch:
    types: [composer-changed]  # Novo trigger
```

**Requisitos**:
- Criar PAT (Personal Access Token) com scope `repo` para o repo data-platform
- Adicionar como secret `CROSS_REPO_PAT` no repo infra

#### 2.2 Alternativa: Eventarc + Cloud Functions (Mais Robusto)

Se o repository dispatch não for suficiente, criar um trigger baseado em eventos do GCP:

```
Cloud Audit Logs (Composer Create/Update)
         │
         ▼
    Eventarc Trigger
         │
         ▼
    Cloud Function
         │
         ▼
    GitHub API (workflow_dispatch)
```

**Terraform para Eventarc**:
```hcl
resource "google_eventarc_trigger" "composer_changed" {
  name     = "composer-changed-trigger"
  location = var.composer_region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.audit.log.v1.written"
  }

  matching_criteria {
    attribute = "serviceName"
    value     = "composer.googleapis.com"
  }

  matching_criteria {
    attribute = "methodName"
    operator  = "match-path-pattern"
    value     = "google.cloud.orchestration.airflow.service.*.*.CreateEnvironment"
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_service.dag_deployer.name
      region  = var.composer_region
    }
  }
}
```

**Complexidade**: Maior. Recomendo começar com 2.1 (repository dispatch).

---

### Fase 3: Monitoramento e Alertas (Prioridade Média)

#### 3.1 Alerta de Bucket Vazio

Criar alerta que dispara se o bucket de DAGs estiver vazio por mais de 30 minutos.

**Cloud Monitoring Alert Policy**:
```yaml
displayName: "Composer DAGs Bucket Empty"
conditions:
  - displayName: "No DAG files"
    conditionMonitoringQueryLanguage:
      query: |
        fetch gcs_bucket
        | filter bucket_name =~ ".*destaquesgovbr-composer.*"
        | metric 'storage.googleapis.com/storage/object_count'
        | filter metric.type = "text/x-python"
        | every 5m
        | condition val() < 1
      duration: "1800s"  # 30 min
alertStrategy:
  notificationRateLimit:
    period: "3600s"
notificationChannels:
  - "projects/inspire-7-finep/notificationChannels/email-nitai"
```

#### 3.2 Alerta de Recriação do Composer

Baseado em Cloud Audit Logs:

```yaml
displayName: "Composer Environment Recreated"
conditions:
  - displayName: "Composer Create Event"
    conditionMatchedLog:
      filter: |
        resource.type="cloud_composer_environment"
        protoPayload.methodName="google.cloud.orchestration.airflow.service.v1.Environments.CreateEnvironment"
```

#### 3.3 Health Check das DAGs

Workflow agendado para verificar se as DAGs existem:

**Arquivo**: `/data-platform/.github/workflows/composer-health-check.yaml`

```yaml
name: Composer Health Check

on:
  schedule:
    - cron: '0 */6 * * *'  # A cada 6 horas

jobs:
  check-dags:
    runs-on: ubuntu-latest
    steps:
      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ...
          service_account: ...

      - name: Check DAGs exist
        run: |
          DAGS_BUCKET=$(gcloud composer environments describe destaquesgovbr-composer \
            --location=us-central1 \
            --format="value(config.dagGcsPrefix)")

          DAG_COUNT=$(gsutil ls "$DAGS_BUCKET/*.py" 2>/dev/null | wc -l)

          if [ "$DAG_COUNT" -lt 1 ]; then
            echo "::error::ALERTA: Nenhuma DAG encontrada no bucket!"
            exit 1
          fi

          echo "✅ $DAG_COUNT DAGs encontradas no bucket"

      - name: Alert on failure
        if: failure()
        run: |
          # Disparar deploy das DAGs automaticamente
          gh workflow run composer-deploy-dags.yaml --repo destaquesgovbr/data-platform
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

### Fase 4: Documentação e Runbooks (Prioridade Baixa)

#### 4.1 Runbook de Recuperação

Criar documento `/data-platform/docs/runbooks/composer-recovery.md`:

```markdown
# Runbook: Recuperação do Cloud Composer

## Sintomas
- DAGs não aparecem no Airflow UI
- Erros "DAG not found" nas execuções
- Bucket gs://...-bucket/dags está vazio

## Diagnóstico
1. Verificar se Composer foi recriado:
   gcloud logging read "resource.type=cloud_composer_environment AND protoPayload.methodName:Create" --limit 5

2. Comparar bucket atual vs esperado:
   gcloud composer environments describe destaquesgovbr-composer --location=us-central1 --format="value(config.dagGcsPrefix)"

## Recuperação
1. Executar workflow de deploy:
   gh workflow run composer-deploy-dags.yaml --repo destaquesgovbr/data-platform

2. Aguardar 60s para parsing

3. Verificar no Airflow UI
```

#### 4.2 Atualizar CLAUDE.md

Adicionar seção sobre resiliência do Composer com links para:
- Este plano
- Runbook de recuperação
- Documentação dos alertas

---

## Cronograma de Implementação

| Fase | Item | Estimativa | Prioridade |
|------|------|------------|------------|
| 1 | 1.1 prevent_destroy | 15 min | ALTA |
| 1 | 1.2 Validação no plan | 30 min | ALTA |
| 2 | 2.1 Repository dispatch | 1-2h | ALTA |
| 3 | 3.1 Alerta bucket vazio | 1h | MÉDIA |
| 3 | 3.2 Alerta recriação | 30 min | MÉDIA |
| 3 | 3.3 Health check | 1h | MÉDIA |
| 4 | 4.1 Runbook | 30 min | BAIXA |
| 4 | 4.2 Documentação | 30 min | BAIXA |

---

## Arquitetura Proposta (Após Implementação)

```
┌─────────────────────────────────────────────────────────────────┐
│                         Infra Repo                              │
│                                                                 │
│  terraform-apply.yml                                            │
│        │                                                        │
│        ├── Valida: bloqueia recriação do Composer               │
│        │                                                        │
│        ▼                                                        │
│  ┌──────────────┐                                               │
│  │  Terraform   │──── prevent_destroy=true ────▶ Composer       │
│  │   Apply      │                                               │
│  └──────────────┘                                               │
│        │                                                        │
│        │ (se Composer mudou)                                    │
│        ▼                                                        │
│  repository_dispatch ───────────────────────────────────────────┤
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   │ (automático)
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data-Platform Repo                         │
│                                                                 │
│  composer-deploy-dags.yaml ◀─── repository_dispatch trigger     │
│        │                                                        │
│        ▼                                                        │
│  ┌──────────────┐     ┌──────────────┐                          │
│  │   Descobre   │────▶│   gsutil     │────▶ Deploy DAGs         │
│  │   Bucket     │     │   rsync      │                          │
│  └──────────────┘     └──────────────┘                          │
│                                                                 │
│  composer-health-check.yaml (a cada 6h)                         │
│        │                                                        │
│        ├── Verifica DAGs existem                                │
│        └── Se vazio: dispara deploy automaticamente             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      Cloud Monitoring                           │
│                                                                 │
│  ┌─────────────────┐   ┌─────────────────┐                      │
│  │ Alerta: Bucket  │   │ Alerta: Composer│                      │
│  │ DAGs Vazio      │   │ Recriado        │                      │
│  └────────┬────────┘   └────────┬────────┘                      │
│           │                     │                               │
│           └─────────┬───────────┘                               │
│                     ▼                                           │
│               Notificação Email                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Riscos e Mitigações

| Risco | Probabilidade | Impacto | Mitigação |
|-------|---------------|---------|-----------|
| PAT expira sem renovação | Média | Alto | Documentar renovação, alertar 30 dias antes |
| Repository dispatch falha silenciosamente | Baixa | Alto | Health check periódico como backup |
| Alertas muito frequentes (ruído) | Média | Baixo | Ajustar thresholds, usar rate limiting |
| Terraform state corruption | Baixa | Alto | Backups do state, prevent_destroy |

---

## Checklist de Implementação

### Repo Infra (destaquesgovbr/infra)
- [ ] Mudar `prevent_destroy = true` em composer.tf
- [ ] Adicionar validação de recriação no workflow terraform-apply.yml
- [ ] Criar secret `CROSS_REPO_PAT` com PAT para data-platform
- [ ] Adicionar step de repository_dispatch no terraform-apply.yml
- [ ] (Opcional) Criar alert policy no Terraform para Composer recreate

### Repo Data-Platform (destaquesgovbr/data-platform)
- [ ] Adicionar trigger `repository_dispatch` no composer-deploy-dags.yaml
- [ ] Criar workflow composer-health-check.yaml
- [ ] Criar runbook de recuperação
- [ ] Atualizar CLAUDE.md com links

### Cloud Monitoring (Console GCP)
- [ ] Criar alert policy para bucket vazio
- [ ] Criar notification channel (email)
- [ ] Testar alertas

---

## Próximos Passos

1. **Revisar este plano** com stakeholders
2. **Priorizar**: Começar com Fase 1 (prevenção) e Fase 2.1 (repository dispatch)
3. **Criar PRs** separados para cada repo
4. **Testar** em ambiente de desenvolvimento (se disponível)
5. **Documentar** qualquer ajuste necessário

---

## Referências

- [_analysis/composer_recreation_issue.md](../_analysis/composer_recreation_issue.md) - Análise do bug de recriação
- [_plan/dynamic-dags-bucket.md](./dynamic-dags-bucket.md) - Plano do bucket dinâmico (já implementado)
- [GitHub Actions: repository-dispatch](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#repository_dispatch)
- [Cloud Monitoring Alerting](https://cloud.google.com/monitoring/alerts)
- [Eventarc Triggers](https://cloud.google.com/eventarc/docs/overview)
