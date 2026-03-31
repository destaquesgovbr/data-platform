# Plano: Gerar Thumbnail Automatico para Noticias de Video (Issue #21)

## Contexto

Noticias da TV Brasil/EBC que sao videos possuem `video_url` mas nao possuem `image_url`. Isso faz com que aparecam sem thumbnail na listagem de noticias do portal, prejudicando a experiencia visual. A solucao cria um servico que extrai o primeiro frame do video via ffmpeg, salva no GCS e atualiza o registro da noticia.

**Repositorio**: `data-platform`
**Issue**: destaquesgovbr/data-platform#21

---

## 1. Compreensao do Problema

### Situacao Atual
- O **EBC Scraper** (`scraper/src/govbr_scraper/scrapers/ebc_webscraper.py`) extrai `video_url` de `<video><source type="video/mp4">` para conteudo TV Brasil
- O campo `image_url` fica NULL quando o artigo nao tem imagem embutida no HTML
- O **feature_worker** computa `has_video: true` e `has_image: false` para esses artigos
- No portal e no Typesense, esses artigos aparecem sem thumbnail

### Comportamento Esperado
- Artigos com `video_url` e sem `image_url` devem ter um thumbnail gerado automaticamente
- O thumbnail e extraido do primeiro frame do video (JPEG, 640x360)
- A imagem e armazenada no GCS com URL publica
- O campo `image_url` e atualizado no PostgreSQL
- O processo e idempotente (nao regera se ja existe)

---

## 2. Escopo

### Incluido
- Novo worker Cloud Run: `thumbnail_worker` (FastAPI, Pub/Sub triggered)
- Extracao de frame via ffmpeg (subprocess)
- Upload para GCS com URL publica
- Atualizacao de `image_url` no PostgreSQL e `has_image` no feature store
- DAG Airflow para backfill de artigos existentes
- Dockerfile com ffmpeg
- Features no registry: `thumbnail_generated`, `thumbnail_failed`
- Configuracoes no `config.py`
- Testes unitarios e de integracao

### NAO incluido
- Extracao de video_url para artigos gov.br (issue separada)
- Processamento de video (transcoding, streaming)
- CDN ou cache layer para thumbnails
- Mudancas no portal/frontend
- Mudancas no repositorio scraper
- Infraestrutura Terraform (Cloud Run service, Pub/Sub subscription, GCS policy) - sera tratada no repo infra

---

## 3. Analise Tecnica

### Componentes Afetados

| Componente | Arquivo | Tipo de Mudanca |
|---|---|---|
| Thumbnail Extractor | `src/data_platform/workers/thumbnail_worker/extractor.py` | **Novo** |
| Thumbnail Storage | `src/data_platform/workers/thumbnail_worker/storage.py` | **Novo** |
| Thumbnail Handler | `src/data_platform/workers/thumbnail_worker/handler.py` | **Novo** |
| Thumbnail App | `src/data_platform/workers/thumbnail_worker/app.py` | **Novo** |
| Batch Job | `src/data_platform/jobs/thumbnail/batch.py` | **Novo** |
| DAG Backfill | `src/data_platform/dags/generate_video_thumbnails.py` | **Novo** |
| Dockerfile | `docker/thumbnail-worker/Dockerfile` | **Novo** |
| Config | `src/data_platform/config.py` | Modificado |
| Feature Registry | `feature_registry.yaml` | Modificado |

### Fluxo Atual vs Proposto

**Atual (artigo com video sem imagem)**:
```
EBC Scraper → PostgreSQL (video_url=X, image_url=NULL)
    → Pub/Sub dgb.news.enriched
    → Feature Worker: has_video=true, has_image=false
    → Typesense: artigo sem thumbnail
```

**Proposto**:
```
EBC Scraper → PostgreSQL (video_url=X, image_url=NULL)
    → Pub/Sub dgb.news.enriched
    → Feature Worker: has_video=true, has_image=false
    → Thumbnail Worker:
        1. Fetch artigo (video_url, image_url)
        2. Elegivel? (video_url != NULL AND image_url == NULL)
        3. ffmpeg: extrai frame 1 → JPEG 640x360
        4. Upload GCS: thumbnails/{unique_id}.jpg
        5. UPDATE news SET image_url = URL
        6. UPSERT news_features: has_image=true, thumbnail_generated=true
    → Typesense Sync: artigo COM thumbnail
```

### Dependencias

- **ffmpeg**: Necessario no container Docker (apt-get install ffmpeg)
- **google-cloud-storage**: Ja e dependencia do projeto (pyproject.toml)
- **PostgresManager**: Reutiliza metodos existentes (`update`, `upsert_features`, `get_by_unique_id`)
- **Pub/Sub**: Subscription `dgb.news.enriched` (mesma topic do feature_worker)

---

## 4. Proposta de Solucao

### Estrategia Geral

Criar um **Cloud Run worker** seguindo exatamente o padrao do `feature_worker`:
- FastAPI app com endpoints `/health` e `/process`
- Triggered por Pub/Sub push (`dgb.news.enriched`)
- Singleton lazy `PostgresManager`
- Retorna 200 sempre (ACK) para evitar retry infinito em mensagens "poison"

A logica e separada em 3 modulos com responsabilidades distintas:
1. **extractor.py** - Wrapper puro de ffmpeg (subprocess), sem estado
2. **storage.py** - Upload GCS + verificacao de existencia
3. **handler.py** - Orquestracao (fetch → check → extract → upload → update)

### Justificativa Tecnica

- **Worker separado** (vs estender feature_worker): ffmpeg e uma dependencia pesada (~80MB). Manter no feature_worker aumentaria desnecessariamente o tamanho de todos os containers. Separacao tambem respeita SRP.
- **Pub/Sub trigger** (vs DAG-only): Processa artigos novos em tempo real (~15s), nao apenas em batch. DAG serve apenas para backfill.
- **ffmpeg via subprocess** (vs biblioteca Python como opencv): ffmpeg e mais leve, mais estavel, e a ferramenta padrao para extracao de frames. Nao precisa compilar opencv.
- **GCS direto** (vs Cloud Functions intermediario): Simplicidade. O worker ja tem acesso ao GCS e ao PostgreSQL.

---

## 5. Estrategia TDD

### 5.1 Casos de Teste

#### extractor.py
| Caso | Tipo |
|---|---|
| Extrai JPEG bytes do primeiro frame | Happy path |
| Timeout do ffmpeg levanta ThumbnailExtractionError | Edge case |
| URL invalida levanta ThumbnailExtractionError | Erro |
| Exit code != 0 levanta ThumbnailExtractionError | Erro |
| Comando ffmpeg usa dimensoes corretas | Validacao |
| Bytes retornados tem header JPEG valido | Validacao |

#### storage.py
| Caso | Tipo |
|---|---|
| build_thumbnail_gcs_path retorna path correto | Happy path |
| upload_thumbnail retorna URL publica | Happy path |
| upload_thumbnail seta content-type image/jpeg | Validacao |
| thumbnail_exists retorna True quando blob existe | Happy path |
| thumbnail_exists retorna False quando nao existe | Happy path |

#### handler.py
| Caso | Tipo |
|---|---|
| Gera thumbnail para artigo elegivel | Happy path |
| Skip artigo que ja tem image_url | Edge case |
| Skip artigo sem video_url | Edge case |
| Artigo nao encontrado retorna not_found | Erro |
| Idempotente: GCS tem thumbnail mas DB nao → so atualiza DB | Edge case |
| Erro de extracao marca thumbnail_failed=true | Erro |
| Nao reprocessa artigos com thumbnail_failed=true | Edge case |

#### app.py
| Caso | Tipo |
|---|---|
| POST /process decodifica envelope Pub/Sub | Happy path |
| POST /process retorna 400 para JSON invalido | Erro |
| POST /process retorna 400 sem unique_id | Erro |
| GET /health retorna 200 | Happy path |

#### batch.py
| Caso | Tipo |
|---|---|
| fetch retorna artigos com video sem imagem | Happy path |
| fetch exclui artigos com thumbnail_failed | Edge case |
| process_batch retorna summary correto | Happy path |

### 5.2 Ciclos TDD

#### Ciclo 1: extractor.py (funcoes puras, sem I/O de DB)

**RED**: `test_build_ffmpeg_command_includes_dimensions`
```python
def test_build_ffmpeg_command_includes_dimensions():
    cmd = build_ffmpeg_command("http://example.com/video.mp4", 640, 360)
    assert "scale=640:360" in " ".join(cmd)
    assert "-vframes" in cmd
```
Falha: funcao `build_ffmpeg_command` nao existe.

**GREEN**: Implementar `build_ffmpeg_command` que retorna a lista de argumentos:
```python
["ffmpeg", "-i", url, "-vframes", "1", "-vf", f"scale={w}:{h}", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]
```

**RED**: `test_extract_first_frame_returns_jpeg_bytes`
```python
def test_extract_first_frame_returns_jpeg_bytes(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value = CompletedProcess(args=[], returncode=0, stdout=FAKE_JPEG_BYTES)
    result = extract_first_frame("http://example.com/video.mp4")
    assert result.image_bytes[:2] == b'\xff\xd8'  # JPEG magic bytes
```
Falha: funcao `extract_first_frame` nao existe.

**GREEN**: Implementar `extract_first_frame` com `subprocess.run(cmd, capture_output=True, timeout=timeout)`.

**RED**: `test_extract_first_frame_timeout_raises_error`
```python
def test_extract_first_frame_timeout_raises_error(mocker):
    mocker.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=30))
    with pytest.raises(ThumbnailExtractionError, match="timeout"):
        extract_first_frame("http://example.com/video.mp4")
```

**GREEN**: Adicionar try/except para `TimeoutExpired` e `CalledProcessError`.

**REFACTOR**: Extrair constantes (JPEG magic bytes, timeout default) e adicionar docstrings.

#### Ciclo 2: storage.py (mock GCS)

**RED**: `test_build_thumbnail_gcs_path`
```python
def test_build_thumbnail_gcs_path():
    path = build_thumbnail_gcs_path("minha-noticia_abc123")
    assert path == "thumbnails/minha-noticia_abc123.jpg"
```

**GREEN**: Implementar funcao pura de string.

**RED**: `test_upload_thumbnail_calls_gcs_with_correct_params`
```python
def test_upload_thumbnail_calls_gcs_with_correct_params(mocker):
    mock_client = mocker.Mock()
    mock_bucket = mocker.Mock()
    mock_blob = mocker.Mock()
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    url = upload_thumbnail("my-bucket", "article_123", b"jpeg_data", gcs_client=mock_client)

    mock_blob.upload_from_string.assert_called_once_with(b"jpeg_data", content_type="image/jpeg")
    assert "storage.googleapis.com" in url
```

**GREEN**: Implementar com DI do gcs_client.

**REFACTOR**: Adicionar `cache_control` no upload e `make_public()`.

#### Ciclo 3: handler.py (orquestracao)

**RED**: `test_handler_generates_thumbnail_for_eligible_article`
```python
def test_handler_generates_thumbnail_for_eligible_article():
    mock_pg = Mock()
    mock_pg.get_by_unique_id.return_value = News(video_url="http://v.mp4", image_url=None, ...)
    mock_extractor = Mock(return_value=ThumbnailExtractionResult(image_bytes=b"jpeg", ...))
    mock_uploader = Mock(return_value="https://storage.googleapis.com/bucket/thumbnails/x.jpg")
    mock_exists = Mock(return_value=False)

    result = handle_thumbnail_generation("uid_123", mock_pg, "bucket",
        extractor_fn=mock_extractor, uploader_fn=mock_uploader, exists_fn=mock_exists)

    assert result["status"] == "generated"
    mock_pg.update.assert_called_once()
    mock_pg.upsert_features.assert_called_once()
```

**GREEN**: Implementar handler com DI para extractor, uploader e exists.

**RED**: `test_handler_skips_article_with_existing_image`
```python
def test_handler_skips_article_with_existing_image():
    mock_pg = Mock()
    mock_pg.get_by_unique_id.return_value = News(video_url="http://v.mp4", image_url="http://img.jpg", ...)

    result = handle_thumbnail_generation("uid_123", mock_pg, "bucket")
    assert result["status"] == "skipped"
```

**GREEN**: Adicionar check de elegibilidade no inicio do handler.

**RED** (idempotencia): `test_handler_updates_db_when_gcs_has_thumbnail`

**GREEN**: Checar `thumbnail_exists` antes de extrair. Se existe, pular extracao e so atualizar DB.

**RED** (erro): `test_handler_marks_failed_on_extraction_error`

**GREEN**: Catch `ThumbnailExtractionError`, setar `thumbnail_failed: true` via `upsert_features`.

**REFACTOR**: Extrair `_is_eligible(article)` como predicado puro.

#### Ciclo 4: app.py

**RED**: `test_health_endpoint`
```python
def test_health_endpoint():
    from fastapi.testclient import TestClient
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
```

**GREEN**: Copiar padrao do feature_worker/app.py, trocar handler.

#### Ciclo 5: batch.py

**RED**: `test_fetch_articles_needing_thumbnails`
```python
def test_fetch_articles_needing_thumbnails(mocker):
    mock_engine = mocker.Mock()
    mock_df = pd.DataFrame({"unique_id": ["a1"], "video_url": ["http://v.mp4"]})
    mocker.patch("pandas.read_sql_query", return_value=mock_df)

    articles = fetch_articles_needing_thumbnails(mock_engine, batch_size=10)
    assert len(articles) == 1
```

**GREEN**: Implementar query SQL com filtros.

### 5.3 Testabilidade

- **Dependency Injection**: `handler.py` recebe `extractor_fn`, `uploader_fn`, `exists_fn` como callables, facilitando substituicao por mocks
- **Funcoes puras**: `build_ffmpeg_command`, `build_thumbnail_gcs_path` sao funcoes puras sem side effects
- **GCS client injection**: `storage.py` recebe `gcs_client` como parametro opcional (default: `storage.Client()`)
- **PostgresManager como interface**: Handler recebe `pg` como parametro, nao instancia internamente
- **Separacao de I/O**: extractor.py isola o subprocess, storage.py isola o GCS, handler.py orquestra

---

## 6. Plano de Implementacao (passo a passo)

### Etapa 1: Configuracao e Registry
1. Adicionar settings de thumbnail em `config.py`
2. Adicionar features `thumbnail_generated` e `thumbnail_failed` em `feature_registry.yaml`
3. **Teste**: `test_feature_registry.py` existente ja valida a estrutura

### Etapa 2: Extractor (RED → GREEN → REFACTOR)
1. Escrever `tests/unit/test_thumbnail_extractor.py` (todos os testes do Ciclo 1)
2. Rodar testes — todos falham (RED)
3. Implementar `src/data_platform/workers/thumbnail_worker/extractor.py`
4. Rodar testes — todos passam (GREEN)
5. Refatorar: constantes, docstrings (REFACTOR)

### Etapa 3: Storage (RED → GREEN → REFACTOR)
1. Escrever `tests/unit/test_thumbnail_storage.py` (Ciclo 2)
2. Rodar testes — todos falham (RED)
3. Implementar `src/data_platform/workers/thumbnail_worker/storage.py`
4. Rodar testes — todos passam (GREEN)
5. Refatorar

### Etapa 4: Handler (RED → GREEN → REFACTOR)
1. Escrever `tests/unit/test_thumbnail_handler.py` (Ciclo 3)
2. Rodar testes — todos falham (RED)
3. Implementar `src/data_platform/workers/thumbnail_worker/handler.py`
4. Rodar testes — todos passam (GREEN)
5. Refatorar: extrair `_is_eligible`

### Etapa 5: FastAPI App (RED → GREEN)
1. Escrever `tests/unit/test_thumbnail_app.py` (Ciclo 4)
2. Implementar `src/data_platform/workers/thumbnail_worker/app.py`
3. Criar `__init__.py` files

### Etapa 6: Batch Job (RED → GREEN)
1. Escrever `tests/unit/test_thumbnail_batch.py` (Ciclo 5)
2. Implementar `src/data_platform/jobs/thumbnail/batch.py`

### Etapa 7: DAG Airflow
1. Implementar `src/data_platform/dags/generate_video_thumbnails.py`
2. Escrever teste de importacao do DAG

### Etapa 8: Docker
1. Criar `docker/thumbnail-worker/Dockerfile` (copiar feature-worker + ffmpeg)

### Etapa 9: Verificacao Final
1. Rodar suite completa: `pytest`
2. Verificar linting: `ruff check src/data_platform/workers/thumbnail_worker/`
3. Verificar types: `mypy src/data_platform/workers/thumbnail_worker/`
4. Verificar formatacao: `black --check src/data_platform/workers/thumbnail_worker/`

---

## 7. Boas Praticas

| Principio | Aplicacao |
|---|---|
| **SRP** | Cada modulo tem uma responsabilidade: extractor (ffmpeg), storage (GCS), handler (orquestracao) |
| **OCP** | Handler aceita funcoes injetadas, extensivel sem modificacao |
| **DIP** | Handler depende de abstractions (callables), nao de implementacoes concretas |
| **Baixo acoplamento** | Extractor nao conhece GCS; Storage nao conhece PostgreSQL; Handler orquestra ambos |
| **Alta coesao** | Cada modulo agrupa funcionalidades relacionadas |
| **Observabilidade** | Logging via loguru em cada etapa (fetch, extract, upload, update) |
| **Tratamento de erros** | ThumbnailExtractionError especifica; thumbnail_failed no feature store para evitar retries infinitos |
| **Idempotencia** | Verifica GCS + DB antes de processar; nao regera se ja existe |

---

## 8. Estrategia de Testes

| Tipo | Escopo | Qtd Estimada |
|---|---|---|
| **Unitarios** | extractor, storage, handler, batch (com mocks) | ~20 testes |
| **Unitarios (app)** | FastAPI endpoints (TestClient) | ~4 testes |
| **Unitarios (registry)** | Validacao YAML (ja existente, auto-valida novas features) | 0 novos |
| **Integracao** | Handler com PostgreSQL real (test container) | ~3 testes |
| **Edge cases** | Timeout, URL quebrada, video grande, GCS ja existente | Incluidos nos unitarios |
| **Regressao** | Feature worker nao e afetado, testes existentes continuam passando | 0 novos |

---

## 9. Riscos e Pontos de Atencao

| Risco | Probabilidade | Impacto | Mitigacao |
|---|---|---|---|
| Video URL inacessivel (404, timeout) | Alta | Baixo | `thumbnail_failed: true` evita retry infinito |
| ffmpeg nao consegue decodificar formato | Media | Baixo | Catch generico + log + feature flag |
| GCS bucket sem permissao publica | Media | Alto | Documentar requisito de infra; URL nao sera acessivel |
| Cloud Composer nao tem ffmpeg | N/A | N/A | DAG chama Cloud Run worker via HTTP, nao roda ffmpeg localmente |
| Aumento de custo GCS | Baixa | Baixo | JPEG 640x360 ~= 30-50KB por thumbnail; milhares de artigos = poucos MB |
| Latencia no pipeline | Baixa | Baixo | ffmpeg extrai 1 frame em <2s; upload GCS <1s |
| Subscription Pub/Sub duplicada | Baixa | Medio | Configurar no Terraform com filtro ou subscription separada |

---

## 10. Criterios de Aceite

- [ ] Artigos com `video_url IS NOT NULL AND image_url IS NULL` tem thumbnail gerado automaticamente
- [ ] Thumbnail e JPEG 640x360 extraido do primeiro frame via ffmpeg
- [ ] Imagem armazenada em `gs://{bucket}/thumbnails/{unique_id}.jpg` com acesso publico
- [ ] Campo `image_url` atualizado no PostgreSQL com URL publica do GCS
- [ ] Feature `thumbnail_generated: true` registrada no `news_features`
- [ ] Processo idempotente: nao regera se thumbnail ja existe no GCS
- [ ] Artigos com falha marcados com `thumbnail_failed: true` (nao reprocessados)
- [ ] Worker responde em `/health` e processa via `/process` (Pub/Sub push)
- [ ] DAG de backfill processa artigos existentes em batches
- [ ] Todos os testes passam (`pytest`)
- [ ] Codigo passa no linting (`ruff`), formatacao (`black`) e type check (`mypy`)

---

## Verificacao

```bash
# Rodar testes
cd /l/disk0/mauriciom/Workspace/destaquesgovbr/data-platform
poetry run pytest tests/unit/test_thumbnail_*.py -v

# Rodar suite completa
poetry run pytest

# Linting e formatacao
poetry run ruff check src/data_platform/workers/thumbnail_worker/ src/data_platform/jobs/thumbnail/
poetry run black --check src/data_platform/workers/thumbnail_worker/ src/data_platform/jobs/thumbnail/
poetry run mypy src/data_platform/workers/thumbnail_worker/ src/data_platform/jobs/thumbnail/
```

---

## Arquivos Criticos (referencia)

| Arquivo | Motivo |
|---|---|
| `src/data_platform/workers/feature_worker/app.py` | Template para o novo worker (FastAPI + Pub/Sub) |
| `src/data_platform/workers/feature_worker/handler.py` | Template para handler (fetch + process + upsert) |
| `src/data_platform/workers/feature_worker/features.py` | Template para funcoes puras de computacao |
| `src/data_platform/managers/postgres_manager.py` | Metodos `update()`, `upsert_features()`, `get_by_unique_id()` |
| `src/data_platform/config.py` | Adicionar settings de thumbnail |
| `src/data_platform/dags/verify_news_integrity.py` | Template para DAG com fetch/process/save |
| `docker/feature-worker/Dockerfile` | Template para Dockerfile (+ ffmpeg) |
| `feature_registry.yaml` | Adicionar novas features |
| `tests/unit/test_feature_registry.py` | Validacao automatica do registry |
