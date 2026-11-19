# Runbook: Airflow próprio (VM `destaquesgovbr-airflow`)

> **Última atualização**: 2026-11-18
> **Substitui**: o runbook do Cloud Composer, desligado na Fase 7 da migração
> (`infra/_plan/migrar-composer-para-airflow-proprio.md`)
> **Severidade**: P1. Sem o Airflow não há scraping (`scrape_agencies` e `scrape_ebc`) nem DAGs batch.

Operação das DAGs no Airflow próprio. A infraestrutura da VM (imagem, compose, alertas, Ops Agent,
parse) está documentada em `infra/airflow/README.md`. Este runbook cobre o dia a dia de quem opera
as DAGs.

---

## Visão geral

| Item | Valor |
|------|-------|
| VM | `destaquesgovbr-airflow` (e2-standard-2, `southamerica-east1-a`, sem IP público) |
| Airflow | 3.1.8 em docker compose em `/opt/airflow`, `LocalExecutor` (as tasks rodam no container do scheduler), sem triggerer |
| UI e REST API | <https://airflow.dgb.app.gov.br>, atrás de um LB HTTPS com IAP. Dentro do Airflow todo mundo é admin (`SimpleAuthManager` com `all_admins`) |
| Bucket | `gs://destaquesgovbr-airflow`: `dags/<repo>/`, `plugins/<pacote>/` e `logs/` |
| Metastore | Postgres 16 local, no disco de dados da VM (snapshot diário) |
| Variables e Connections | Secret Manager (`airflow-variables-*`, `airflow-connections-*`), pelo secrets backend |
| Fuso | crons em `America/Sao_Paulo` (`core.default_timezone`). `run_id`, `logical_date` e nomes de log aparecem em UTC: `scheduled__2026-11-18T21:00:00+00:00` é o run das 18:00 BRT |

Containers (projeto compose `airflow`):

| Serviço (`docker compose`) | Container | Função |
|----------------------------|-----------|--------|
| `airflow-scheduler` | `airflow-airflow-scheduler-1` | Agenda e **executa** as tasks |
| `airflow-apiserver` | `airflow-airflow-apiserver-1` | UI e REST API (porta 8080, só para o LB) |
| `airflow-dag-processor` | `airflow-airflow-dag-processor-1` | Parse das DAGs |
| `postgres` | `airflow-postgres-1` | Metastore |
| `dag-sync` | `airflow-dag-sync-1` | Espelha `gs://destaquesgovbr-airflow/{dags,plugins}` nos volumes a cada 60 s |
| `airflow-init` | — | Roda `airflow db migrate` e sai |

A UI mostra o Triggerer em vermelho de propósito: o compose não tem triggerer (nenhuma DAG é
deferrable).

**A VM é GitOps.** Compose, env e startup-script vêm do Terraform (repo `infra`,
`terraform/airflow.tf` e `terraform/templates/airflow/`). Não edite nada na VM: o
`airflow-reconcile` sobrescreve a cada mudança de metadata, e os volumes de DAGs e plugins são
somente leitura. Mudança de configuração é PR no `infra`.

---

## Diagnóstico rápido

| Sintoma | Primeiro passo |
|---------|----------------|
| Alerta **"Airflow sem heartbeat"** no Telegram | [Heartbeat](#alerta-airflow-sem-heartbeat): VM ligada? `docker compose ps`? `airflow_heartbeat` despausada? |
| DAG não aparece na UI ou sumiu | `dags list-import-errors`, depois o arquivo no bucket e o log do `dag-sync` ([Como as DAGs chegam](#como-as-dags-chegam-na-vm)) |
| DAG não roda no horário | Pausada? Run anterior travado (`max_active_runs=1`)? Scheduler saudável? |
| Task falhou | Log da task na UI ou no GCS ([Logs](#onde-estão-os-logs)); depois `tasks clear` |
| UI não abre (erro do IAP) | Sem `roles/iap.httpsResourceAccessor` para a sua conta: pedir no repo `infra` |
| UI dá 502/503 | `airflow-apiserver` caído ou reiniciando (mudança de env/compose recria os containers por ~1–2 min) |
| Alertas de memória, disco ou Ops Agent | `infra/airflow/README.md`, seção "Alertas" |

---

## Acesso

### UI

<https://airflow.dgb.app.gov.br>. O IAP libera quem tem `roles/iap.httpsResourceAccessor` no
backend (IAM do IAP em `terraform/airflow-lb.tf` do `infra`).

### SSH (só via IAP)

```bash
gcloud compute ssh destaquesgovbr-airflow --zone=southamerica-east1-a \
  --tunnel-through-iap --project=inspire-7-finep
```

O túnel exige `roles/iap.tunnelResourceAccessor` na instância, que só os admins do Airflow têm;
`roles/editor` não basta (erro 4033).

Na VM, para inspecionar:

```bash
cd /opt/airflow
sudo docker compose ps                                   # estado e health de cada serviço
sudo docker compose logs --since 30m airflow-scheduler   # ou airflow-dag-processor, dag-sync...
sudo docker compose logs -f --tail 50 dag-sync
sudo docker stats --no-stream                            # memória por container
```

### Airflow CLI (dentro do scheduler)

```bash
cd /opt/airflow
alias af='sudo docker compose exec airflow-scheduler airflow'
af dags list                      # dag_id, arquivo, owner, is_paused
af dags list-import-errors        # deve ser vazio
```

Sem abrir sessão, do seu computador (`-T`: sem TTY):

```bash
gcloud compute ssh destaquesgovbr-airflow --zone=southamerica-east1-a \
  --tunnel-through-iap --project=inspire-7-finep \
  --command='cd /opt/airflow && sudo docker compose exec -T airflow-scheduler airflow dags list-import-errors'
```

A REST API (`/api/v2`) também passa pelo IAP. Para scripts, o caminho mais simples é a CLI por SSH;
o `streamlit-infra-health` é o exemplo de cliente que atravessa o IAP e pega o token do Airflow em
`/auth/token`.

---

## Comandos do dia a dia

Todos com o alias `af` acima.

```bash
# Runs de uma DAG (--state queued|running|success|failed)
af dags list-runs sync_pg_to_bigquery --state failed

# Estado de um run
af dags state sync_pg_to_bigquery 'scheduled__2026-11-18T10:00:00+00:00'

# Próximo run que o scheduler vai criar (logical date, em UTC). Com a DAG pausada e a data já
# no passado, é o run que sai NA HORA ao despausar (ver "Catch-up ao despausar").
af dags next-execution sync_pg_to_bigquery

# Pausar / despausar
af dags pause compute_trending
af dags unpause compute_trending

# Disparar um run manual (com params, se a DAG tiver)
af dags trigger compute_trending
af dags trigger aggregate_engagement --conf '{"flesch_lookback_days": null}'

# Variable efetiva (Secret Manager primeiro, depois metastore)
af variables get thumbnail_worker_url
```

### Refazer tasks (`tasks clear`)

`tasks clear` apaga o estado das task instances e o scheduler roda de novo. **Sempre passe `-s` e
`-e`**: sem eles o comando pega todos os runs da DAG. As datas filtram pela `logical_date` do run;
para um run só, use a mesma data nos dois, com fuso:

```bash
# Só as tasks com falha do run das 07:00 BRT de 18/11 (-f), sem perguntar (-y)
af tasks clear sync_pg_to_bigquery -s 2026-11-18T07:00:00-03:00 -e 2026-11-18T07:00:00-03:00 -f -y

# Uma task específica (-t é regex; -d inclui as que dependem dela)
af tasks clear aggregate_engagement -t '^fill_flesch_ptbr$' -s 2026-11-18T08:00:00-03:00 -e 2026-11-18T08:00:00-03:00 -y
```

Sem `-y` o comando lista o que vai limpar e pede confirmação; use assim na primeira vez. Na UI o
equivalente é **Clear** no run ou na task (com "Only failed"). Runs manuais disparados sem
`--logical-date` têm `logical_date` vazia e não casam com `-s`/`-e`: limpe esses pela UI.

Antes de limpar uma task que **terminou com sucesso**, confira na tabela abaixo se a DAG aguenta
rodar duas vezes o mesmo período.

### Reiniciar um serviço

Os containers têm `restart: always`. Se o scheduler estiver vivo mas parado (sem agendar nada, sem
erro claro), reiniciar só ele:

```bash
sudo docker compose restart airflow-scheduler
```

Com `LocalExecutor` as tasks em execução morrem junto e ficam para retry (ou `failed`). Reiniciar
não muda configuração; qualquer mudança no compose ou no env é PR no `infra`.

---

## DAGs do data-platform: o que aguenta rodar de novo

Todas têm `catchup=False`. Schedules e detalhes em [docs/dags/README.md](../dags/README.md).

| DAG | Rodar de novo o mesmo período | Por quê |
|-----|-------------------------------|---------|
| `compute_trending`, `compute_entity_trending`, `compute_clusters`, `aggregate_engagement`, `project_entity_graph`, `verify_news_integrity`, `generate_video_thumbnails` | Pode | Recalculam e sobrescrevem (upsert) |
| `ner_backfill`, `canonicalize_backfill`, `enrichment_backfill` | Pode, com custo | Retomáveis: a seleção exclui o que já foi feito e o governador de cota para o run. Cada run gasta cota de LLM. `ner_backfill` e `enrichment_backfill` usam o mesmo Cloud Run Job |
| `sync_pg_to_bigquery`, `sync_umami_to_bigquery` | **Não** | `WRITE_APPEND` sem deduplicação: o mesmo dia carregado duas vezes duplica as linhas no BigQuery |

### Refazer um backfill (`ner_backfill`, `canonicalize_backfill`, `enrichment_backfill`)

Os três disparam Cloud Run Jobs e são retomáveis, então refazer é seguro:

- **Run com falha:** `tasks clear` do run com `-f` (ou Clear na UI). Antes, veja no log da task
  se a falha foi do Job (log do Cloud Run Job) ou do operador.
- **Run extra fora do horário:** `af dags trigger <dag>`. Com `max_active_runs=1` ele espera o run
  em andamento. Evite disparar `ner_backfill` e `enrichment_backfill` ao mesmo tempo (mesmo Job e
  mesmo banco) e prefira as janelas noturnas, fora do pico do worker ao vivo.
- **`enrichment_backfill` com outros params** (campanha, datas, modelo): ensaie com `dry_run`, que
  só seleciona e lista, e depois rode de verdade com os mesmos params:

  ```bash
  af dags trigger enrichment_backfill --conf '{"select": "theme-code", "theme_code": "19", "date_from": "2026-01-01", "date_to": "2026-11-01", "dry_run": true}'
  ```

  Os params e os valores aceitos estão no `doc_md` da DAG (UI → DAG → Docs) e em
  `src/data_platform/dags/enrichment_backfill.py`. Valor fora do schema dos Params é recusado no
  disparo; combinação inválida (ex.: `date_to` antes de `date_from`) falha na primeira task.
- `ner_backfill` e `canonicalize_backfill` não têm params: o tamanho de cada run vem das Variables
  (`ner_run_limit`, `canon_run_limit` etc., no Secret Manager).

### Refazer um dia das DAGs `WRITE_APPEND`

`sync_pg_to_bigquery` (07:00 BRT) carrega em `dgb_gold.fato_noticias` as notícias do dia anterior
à `logical_date` do run (`published_at` em `[D-1, D)`). `sync_umami_to_bigquery` (09:00 BRT) faz o
mesmo com `dgb_gold.umami_pageviews` e `dgb_gold.umami_events` (`created_at`). Cada carga é um load
job: ou entra o dia inteiro, ou nada.

Antes de refazer, confira se o dia já está lá. Linhas a mais que ids distintos = dia duplicado:

```sql
SELECT DATE(published_at) AS dia, COUNT(*) AS linhas, COUNT(DISTINCT unique_id) AS artigos
FROM `inspire-7-finep.dgb_gold.fato_noticias`
WHERE DATE(published_at) BETWEEN '2026-11-14' AND '2026-11-18'
GROUP BY dia ORDER BY dia;

SELECT DATE(created_at) AS dia, COUNT(*) AS linhas, COUNT(DISTINCT event_id) AS eventos
FROM `inspire-7-finep.dgb_gold.umami_pageviews`   -- e umami_events
WHERE DATE(created_at) BETWEEN '2026-11-14' AND '2026-11-18'
GROUP BY dia ORDER BY dia;
```

Então:

- **Run do dia falhou na task de carga** (`sync_facts`, `sync_pageviews`, `sync_events`): o dia não
  entrou. `tasks clear` só das tasks com falha (`-f`) daquele run.
- **Dia sem run nenhum** (ex.: o Airflow ficou fora): crie só os runs que faltam, com a
  `logical_date` do horário (o dia carregado é o anterior a ela). `--reprocess-behavior none` (o
  padrão) pula as datas que já têm run, e `--dry-run` mostra quais seriam criadas:

  ```bash
  af backfill create --dag-id sync_pg_to_bigquery \
    --from-date 2026-11-16T07:00:00-03:00 --to-date 2026-11-18T07:00:00-03:00 \
    --reprocess-behavior none --dry-run
  ```

  Sem `--dry-run` os runs aparecem na UI (aba Backfills) e rodam pelo scheduler.
- **Dia já carregado e é preciso recarregar** (dados corrigidos na origem): apague o dia no
  BigQuery antes (`DELETE ... WHERE DATE(published_at) = '<dia>'`, conferindo antes com o `SELECT`
  acima) e só então refaça o run.
- **Não dispare** essas DAGs com `af dags trigger` sem `--logical-date`: o run manual não tem
  `logical_date`, a DAG usa a hora atual e carrega "ontem", o mesmo dia que o run agendado de hoje
  carrega (ou já carregou).

---

## Catch-up ao despausar

Todas as DAGs dos repos têm `catchup=False`, e o Airflow 3 usa o `CronTriggerTimetable` para crons.
Com isso:

- **Ao despausar uma DAG que perdeu horários enquanto estava pausada, o scheduler roda NA HORA o
  horário mais recente que passou** (um run só; os anteriores são pulados). Se o despause cair
  logo depois de um horário, antes do próximo parse da DAG (até 3 min), pode sair também o horário
  anterior a ele.
- **DAG nova**: nasce pausada (`dags_are_paused_at_creation=True`). Ao despausar pela primeira vez
  roda na hora o horário mais recente que já passou, mesmo sem nunca ter rodado.
- Despausar antes de qualquer horário perdido não dispara nada: o próximo run sai no horário.

Para as DAGs que aguentam rodar de novo isso é inofensivo. Para as `WRITE_APPEND` pode duplicar um
dia, se ele já foi carregado por outro caminho (run manual, backfill ou `tasks clear`):

1. Veja qual run vai sair: `af dags next-execution sync_pg_to_bigquery`. Se a data já passou, é
   ela. O dia carregado é o anterior a essa data.
2. Confira esse dia no BigQuery com o `SELECT` acima.
3. Se o dia **não** está lá, despause: o run cobre o buraco.
4. Se o dia **já** está lá, ou apague o dia no BigQuery antes de despausar, ou despause só depois
   do próximo horário da DAG passar (o run imediato passa a ser o desse horário, que carrega um dia
   ainda não carregado). Foi o que se fez na virada do Composer (Fase 5).

O mesmo vale ao recriar o metastore (VM nova sem o disco de dados): todas as DAGs voltam pausadas
e sem histórico.

---

## Como as DAGs chegam na VM

```
push na main (repo da DAG)
  └─ workflow de deploy (reusable-workflows/airflow-deploy-dags.yml@v3)
       └─ gcloud storage rsync → gs://destaquesgovbr-airflow/{plugins/<pacote>,dags/<repo>}/
            └─ dag-sync (a cada 60 s) → volumes /opt/airflow/{dags,plugins} (somente leitura)
                 └─ dag-processor (refresh do bundle a cada 60 s; reparse a cada ≤180 s)
```

- **Arquivo novo** aparece em até ~2 min (até 60 s do dag-sync + até 60 s do refresh do bundle).
- **Mudança numa DAG existente** vale em até ~4 min (60 s do dag-sync + até 180 s do
  `min_file_process_interval`).
- DAG nova nasce **pausada**: despause na UI depois de conferir o catch-up acima.
- O rsync apaga no destino o que saiu do repo. Uma DAG cujo arquivo sumiu vira *stale* e some da UI;
  runs já enfileirados dela ficam órfãos (marque como `failed` na UI). Pause as DAGs antes de
  removê-las.

Subpastas do bucket e quem publica:

| Caminho no bucket | Repo | Workflow |
|-------------------|------|----------|
| `dags/data-platform/`, `plugins/data_platform/`, `plugins/pyphen/` | `data-platform` | `composer-deploy-dags.yaml` (nome histórico; publica só no bucket do Airflow próprio) |
| `dags/scraper/` | `scraper` | `composer-deploy-dags.yaml` |
| `dags/clipping/` | `clipping` | `deploy-dags.yaml` |
| `dags/data-publishing/`, `plugins/data_publishing/` | `data-publishing` | `composer-deploy-dags.yaml` |
| `dags/platform/` (`airflow_heartbeat`) | `infra` | `airflow-image.yml` |

### DAG sumiu ou não aparece

```bash
af dags list-import-errors                                   # erro de import no parse?
gcloud storage ls gs://destaquesgovbr-airflow/dags/data-platform/ --project=inspire-7-finep
sudo docker compose exec airflow-scheduler ls /opt/airflow/dags/data-platform /opt/airflow/plugins
sudo docker compose logs --since 15m dag-sync                # "dag-sync: falha no rsync ..."
```

- Arquivo fora do bucket: publique de novo pelo workflow do repo
  (`gh workflow run composer-deploy-dags.yaml --repo destaquesgovbr/data-platform`).
- No bucket mas não no container: problema no `dag-sync` (credencial da VM, rede). Veja o log dele.
- No container mas com import error: corrija no repo. Erros de import típicos são pacote faltando
  na imagem (`infra/airflow/requirements.txt`) ou módulo que não foi copiado para os plugins (job
  `deploy-plugins` do `composer-deploy-dags.yaml`).

---

## Onde estão os logs

| O quê | Onde |
|-------|------|
| Log de cada task | UI (DAG → run → task → Logs) e `gs://destaquesgovbr-airflow/logs/` (30 dias) |
| Saída dos containers (scheduler, api-server, dag-processor, postgres, dag-sync) | Cloud Logging, log `gcplogs-docker-driver`, recurso `gce_instance`; também `sudo docker compose logs` na VM |
| syslog da VM (OOM killer, dockerd, `airflow-reconcile`) | Cloud Logging, log `syslog` |
| Heartbeat | Cloud Logging, log `airflow-heartbeat` |

Log de task no GCS: `dag_id=<dag>/run_id=<run_id>/task_id=<task>/[map_index=<n>/]attempt=<n>.log`.

```bash
gcloud storage ls 'gs://destaquesgovbr-airflow/logs/dag_id=sync_pg_to_bigquery/**' \
  --project=inspire-7-finep | tail -5
gcloud storage cat 'gs://destaquesgovbr-airflow/logs/dag_id=sync_pg_to_bigquery/run_id=scheduled__2026-11-18T10:00:00+00:00/task_id=sync_facts/attempt=1.log' \
  --project=inspire-7-finep
```

Saída de um container (as entradas não têm severity; filtre pelo texto):

```bash
gcloud logging read \
  'logName="projects/inspire-7-finep/logs/gcplogs-docker-driver" AND jsonPayload.container.name="/airflow-airflow-scheduler-1"' \
  --project=inspire-7-finep --freshness=1h --limit=100 \
  --format='value(timestamp,jsonPayload.message)'
```

---

## Alerta "Airflow sem heartbeat"

A DAG `airflow_heartbeat` (repo `infra`, `airflow/dags/platform/`, a cada 15 min, nasce
despausada) grava uma entrada no log `airflow-heartbeat`. O alerta dispara depois de 45 min sem
entrada e chega no Telegram por `dgb.ops.alerts` e o alert-relay. Ele pega VM parada, scheduler
morto, executor travado e task sem credencial.

1. **A VM está ligada?**

   ```bash
   gcloud compute instances describe destaquesgovbr-airflow --zone=southamerica-east1-a \
     --project=inspire-7-finep --format='value(status)'
   ```

   Se não for `RUNNING`, é caso de admin do `infra` (ligar a VM; nada se recria fora do Terraform).
2. **Os containers estão de pé?** `sudo docker compose ps`: `airflow-scheduler`,
   `airflow-apiserver` e `airflow-dag-processor` precisam estar `Up (healthy)`.
3. **O scheduler está em loop de erro?** `sudo docker compose logs --since 1h airflow-scheduler`.
   Caso conhecido do Airflow 3.1: task **mapeada** com `retry_exponential_backoff=True` derruba o
   loop do scheduler quando entra em retry. Pause a DAG, marque o run como `failed` e corrija a DAG
   (em task mapeada, só `retry_delay` fixo).
4. **A `airflow_heartbeat` está despausada e rodando?** `af dags list-runs airflow_heartbeat`. Se
   os runs falham, o log da task diz o motivo (em geral credencial ou Cloud Logging).
5. **As entradas chegam?**

   ```bash
   gcloud logging read 'logName="projects/inspire-7-finep/logs/airflow-heartbeat"' \
     --project=inspire-7-finep --freshness=1h --limit=5 --format='value(timestamp)'
   ```

Depois de normalizar, o scraping se recupera sozinho na próxima execução de 2 h (a janela da
`scrape_agencies` cobre o dia). Para quedas mais longas, veja "Recuperar o período perdido" no
`docs/runbook.md` do repo `scraper`, e as DAGs `WRITE_APPEND` deste repo na seção acima.

---

## Referências

- `infra/airflow/README.md`: imagem, operação da VM, Ops Agent, alertas de memória e disco, parse
- `infra/_plan/migrar-composer-para-airflow-proprio.md`: plano da migração do Composer
- `scraper/docs/runbook.md`: operação do `scrape_agencies` e recuperação de períodos
- [DAGs do data-platform](../dags/README.md)
- [Convenção de deploy das DAGs](../architecture/decentralized-dags.md)
