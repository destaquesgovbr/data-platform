# Correção: Campo editorial_lead no Scraper EBC

**Data**: 2026-02-05
**Issue**: [#23](https://github.com/destaquesgovbr/data-platform/issues/23)
**Arquivos modificados**:
- `src/data_platform/scrapers/ebc_webscraper.py`
- `src/data_platform/scrapers/ebc_scrape_manager.py`
- `tests/unit/test_ebc_scraper.py` (novo)

---

## Resumo

Durante a análise da issue #23, foi identificado que o scraper da EBC (TV Brasil) já extraía o nome do programa (ex: "Caminhos da Reportagem"), porém esse dado era **atribuído ao campo errado** (`source`) e posteriormente **descartado** na conversão de dados, nunca sendo persistido.

---

## O Problema

### 1. Extração correta, campo errado

O scraper extraía corretamente o elemento `<h4 class="txtNoticias">` que contém o nome do programa, mas atribuía ao campo `source`:

```python
# ebc_webscraper.py (ANTES)
author_elem = soup.find('h4', class_='txtNoticias')
if author_elem:
    link_elem = author_elem.find('a')
    if link_elem:
        news_data['source'] = link_elem.get_text(strip=True)  # "Caminhos da Reportagem"
```

### 2. Campo descartado na conversão

O campo `source` não era mapeado na função de conversão, resultando na perda do dado:

```python
# ebc_scrape_manager.py (ANTES)
converted_item = {
    "title": item.get("title", "").strip(),
    "url": item.get("url", "").strip(),
    "editorial_lead": None,  # Hardcoded como None!
    "content": item.get("content", "").strip(),
    # ... outros campos
    # "source" NÃO estava aqui - dado perdido!
}
```

### 3. Campo não existe no schema

O campo `source` não existe no modelo de dados (`News`, `NewsInsert`), nem no PostgreSQL, HuggingFace ou Typesense. Por isso o dado era silenciosamente ignorado.

---

## Fluxo do Problema (Antes)

```
HTML da TV Brasil
    │
    ▼
<h4 class="txtNoticias">
  <a href="/caminhos-da-reportagem">Caminhos da Reportagem</a>
</h4>
    │
    ▼
ebc_webscraper.py
    │ Extrai para news_data['source'] = "Caminhos da Reportagem"
    ▼
ebc_scrape_manager.py
    │ converted_item NÃO inclui 'source'
    │ editorial_lead = None (hardcoded)
    ▼
PostgreSQL / HuggingFace / Typesense
    │
    ▼
editorial_lead = NULL  ❌ Dado perdido!
```

---

## A Solução

### 1. Corrigir a atribuição no webscraper

```python
# ebc_webscraper.py (DEPOIS)
editorial_elem = soup.find('h4', class_='txtNoticias')
if editorial_elem:
    link_elem = editorial_elem.find('a')
    if link_elem:
        news_data['editorial_lead'] = link_elem.get_text(strip=True)
    else:
        news_data['editorial_lead'] = editorial_elem.get_text(strip=True)

news_data['source'] = ''  # TV Brasil não tem campo de autor
```

### 2. Passar o campo na conversão

```python
# ebc_scrape_manager.py (DEPOIS)
editorial_lead = item.get("editorial_lead", "").strip() or None

converted_item = {
    ...
    "editorial_lead": editorial_lead,  # Agora usa o valor extraído
    ...
}
```

---

## Fluxo Corrigido (Depois)

```
HTML da TV Brasil
    │
    ▼
<h4 class="txtNoticias">
  <a href="/caminhos-da-reportagem">Caminhos da Reportagem</a>
</h4>
    │
    ▼
ebc_webscraper.py
    │ Extrai para news_data['editorial_lead'] = "Caminhos da Reportagem"
    ▼
ebc_scrape_manager.py
    │ converted_item['editorial_lead'] = "Caminhos da Reportagem"
    ▼
PostgreSQL / HuggingFace / Typesense
    │
    ▼
editorial_lead = "Caminhos da Reportagem"  ✅ Dado persistido!
```

---

## Validação

### Teste com URL real

```
URL: https://tvbrasil.ebc.com.br/caminhos-da-reportagem/2026/01/foz-do-iguacu-crimes-na-fronteira-mais-movimentada-do-brasil

Resultado:
- Title: "Foz do Iguaçu: crimes na fronteira mais movimentada do Brasil"
- Editorial Lead: "Caminhos da Reportagem" ✅
- Agency: "tvbrasil"
- Tags: ["Caminhos da Reportagem", "Foz do Iguaçu", "fronteira"]
```

### Testes unitários

9 testes criados e passando:
- `test_tvbrasil_extracts_editorial_lead_from_link`
- `test_tvbrasil_extracts_editorial_lead_without_link`
- `test_tvbrasil_source_is_empty`
- `test_agencia_brasil_editorial_lead_is_empty`
- `test_news_data_includes_editorial_lead_field`
- `test_convert_ebc_to_govbr_format_preserves_editorial_lead`
- `test_convert_ebc_to_govbr_format_handles_empty_editorial_lead`
- `test_convert_ebc_to_govbr_format_handles_missing_editorial_lead`
- `test_preprocess_data_includes_editorial_lead_in_columns`

---

## Impacto

| Aspecto | Antes | Depois |
|---------|-------|--------|
| **TV Brasil - editorial_lead** | `NULL` | Nome do programa (ex: "Caminhos da Reportagem") |
| **TV Brasil - source** | Nome do programa (descartado) | `""` (vazio) |
| **Agência Brasil - editorial_lead** | `NULL` | `NULL` (não possui) |
| **Agência Brasil - source** | Nome do autor (descartado) | Nome do autor (descartado)* |

*Nota: O campo `source` da Agência Brasil (ex: "Pedro Peduzzi - Repórter da Agência Brasil") continua sendo extraído mas não persistido, pois não existe no schema. Se necessário, pode ser adicionado em uma issue futura.

---

## Onde o editorial_lead é persistido

O campo `editorial_lead` já estava integrado em todo o pipeline:

| Storage | Arquivo | Status |
|---------|---------|--------|
| **PostgreSQL** | `postgres_manager.py` | ✅ Coluna existe |
| **HuggingFace** | `sync_postgres_to_huggingface.py` | ✅ Incluído no schema |
| **Typesense** | `collection.py` | ✅ Campo searchable |
| **Modelo Pydantic** | `news.py` | ✅ `Optional[str]` |

A única pendência era a extração correta no scraper EBC.

---

## Comparação com Gov.br

Para referência, nos sites gov.br o `editorial_lead` é extraído de:
- `<p class="nitfSubtitle">` (estrutura SECOM)
- Exemplos: "COP30 E O BRASIL", "ECONOMIA"

No TV Brasil, equivale ao nome do programa que aparece acima do título.

---

## Próximos Passos

1. ✅ Correção implementada
2. ✅ Testes criados
3. ⏳ Code review
4. ⏳ Merge para main
5. ⏳ Deploy em produção
6. ⏳ Re-scrape de artigos antigos da TV Brasil (se necessário)
