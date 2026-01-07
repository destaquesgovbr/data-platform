# Plano: Tornar DAGS_BUCKET Dinâmico no Workflow de Deploy

## Problema

O bucket do Composer está **hardcoded** no workflow:
```yaml
DAGS_BUCKET: gs://us-central1-destaquesgovbr--30208ee3-bucket/dags
```

Quando o Composer é recriado (por qualquer motivo), o GCP gera um novo bucket com hash diferente, quebrando o deploy.

## Causa Raiz

- O Cloud Composer **auto-gera** o bucket de DAGs - não é possível definir um nome fixo
- O nome segue o padrão: `gs://{REGION}-{ENV_NAME}--{HASH}-bucket/dags`
- O hash (`30208ee3`, `a02910d4`, etc.) muda a cada recriação do ambiente

## Solução

Obter o bucket **dinamicamente** via `gcloud` antes do deploy.

## Implementação

### Arquivo a Modificar
- `.github/workflows/composer-deploy-dags.yaml`

### Mudanças

**1. Remover DAGS_BUCKET das variáveis de ambiente globais:**
```yaml
env:
  PROJECT_ID: inspire-7-finep
  COMPOSER_ENVIRONMENT: destaquesgovbr-composer
  COMPOSER_REGION: us-central1
  # REMOVER: DAGS_BUCKET: gs://us-central1-destaquesgovbr--30208ee3-bucket/dags
  DAGS_LOCAL_PATH: src/data_platform/dags
```

**2. Adicionar step para obter bucket dinamicamente (após "Set up Cloud SDK"):**
```yaml
- name: Get Composer DAGs bucket
  id: composer
  run: |
    DAGS_BUCKET=$(gcloud composer environments describe ${{ env.COMPOSER_ENVIRONMENT }} \
      --location=${{ env.COMPOSER_REGION }} \
      --format="value(config.dagGcsPrefix)")
    echo "dags_bucket=$DAGS_BUCKET" >> $GITHUB_OUTPUT
    echo "DAGs bucket: $DAGS_BUCKET"
```

**3. Atualizar referências para usar o output:**
- `${{ env.DAGS_BUCKET }}` → `${{ steps.composer.outputs.dags_bucket }}`

**Steps afetados:**
- "Deploy DAGs to GCS" (linha 120-126)
- "Verify deployment" (linha 128-131)

## Benefícios

1. **Resiliência** - Deploy funciona mesmo após recriação do Composer
2. **Imutabilidade** - Infraestrutura pode ser recriada sem atualizar código
3. **Multi-ambiente** - Facilita deploy em dev/staging/prod
4. **Single source of truth** - Configuração vem direto do GCP

## Alternativa Considerada (Descartada)

**Usar Terraform output** - Exigiria acesso ao state do Terraform durante o workflow, adicionando complexidade. A abordagem via `gcloud` é mais simples e direta.

## Testes

1. Executar workflow manualmente
2. Verificar no log que o bucket foi descoberto corretamente
3. Confirmar que DAGs foram deployados no bucket correto
