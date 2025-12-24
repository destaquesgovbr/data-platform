# DestaquesGovBr Data Platform

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 15](https://img.shields.io/badge/postgresql-15-blue.svg)](https://www.postgresql.org/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

> **Status**: 🚧 Em desenvolvimento - Fase 1: Infraestrutura ✅ | Fase 2: PostgresManager 🚧
>
> Plataforma de dados para agregação, enriquecimento e disponibilização de notícias governamentais brasileiras.

📚 **[Ver Documentação Completa](docs/README.md)** | 🗃️ **[Dataset Público](https://huggingface.co/datasets/nitaibezerra/govbrnews)**

---

## 🎯 Sobre o Projeto

A **Data Platform** centraliza toda a infraestrutura de dados do [DestaquesGovBr](https://destaques.gov.br), incluindo:

- 📰 Coleta de notícias de ~160 sites governamentais (gov.br)
- 🤖 Enriquecimento com IA (classificação temática, sumários)
- 🗄️ Armazenamento e gerenciamento de dados
- 🔄 Sincronização com HuggingFace (dados abertos)
- 🔍 Indexação para busca (Typesense)

### Migração em Andamento

Este projeto está migrando de **HuggingFace Dataset** (usado como banco de dados) para **PostgreSQL** (Cloud SQL) como fonte de verdade.

**Progresso**:
- [x] Fase 0: Setup Inicial
- [x] Fase 1: Infraestrutura (Cloud SQL provisionado ✅)
- [ ] Fase 2: PostgresManager
- [ ] Fase 3: Migração de Dados
- [ ] Fase 4: Dual-Write
- [ ] Fase 5: PostgreSQL Primary
- [ ] Fase 6: Consumidores

Ver detalhes em [_plan/README.md](_plan/README.md) e [_plan/PROGRESS.md](_plan/PROGRESS.md).

---

## 📂 Estrutura do Repositório

```
data-platform/
├── docs/                   # 📚 Documentação
│   ├── architecture/       # Arquitetura do sistema
│   ├── database/           # Schemas e migrações
│   └── development/        # Guias de desenvolvimento
├── _plan/                  # 📋 Documentação da migração
├── src/data_platform/      # 🐍 Código Python
│   ├── managers/           # Gerenciadores de storage (PostgreSQL, HF)
│   ├── jobs/               # Jobs de processamento
│   ├── models/             # Modelos Pydantic
│   └── dags/               # DAGs Airflow (futuro)
├── tests/                  # 🧪 Testes unitários e integração
├── scripts/                # 🛠️ Scripts de migração e manutenção
└── pyproject.toml          # Dependências e configuração
```

---

## 🚀 Quick Start

### Pré-requisitos

- Python 3.11+
- Poetry ou pip
- PostgreSQL (para testes locais)

### Instalação

```bash
# Clonar repositório
git clone https://github.com/destaquesgovbr/data-platform.git
cd data-platform

# Instalar dependências com Poetry
poetry install

# OU com pip
pip install -e .
```

### Executar Testes

```bash
# Todos os testes
poetry run pytest

# Com cobertura
poetry run pytest --cov=data_platform

# Apenas unitários
poetry run pytest tests/unit/
```

---

## 🗄️ Arquitetura de Dados

### Schema PostgreSQL

- **`agencies`**: Dados mestres de agências governamentais (158 registros)
- **`themes`**: Taxonomia hierárquica de temas (3 níveis)
- **`news`**: Notícias (~300k registros)
- **`sync_log`**: Log de sincronizações

Ver schema completo em [_plan/SCHEMA.md](_plan/SCHEMA.md).

### Fluxo de Dados (Alvo)

```
┌─────────────────┐
│ Scrapers        │
│ (Gov.br + EBC)  │
└────────┬────────┘
         ↓
┌────────────────────┐
│ PostgreSQL         │ ← Fonte de verdade
│ (Cloud SQL)        │
└────────┬───────────┘
         │
    ┌────┴────┬──────────────┐
    ↓         ↓              ↓
┌─────────┐ ┌──────────┐  ┌────────────┐
│HuggingFace│ │Typesense │  │Portal Web │
│(dados    │ │(busca)   │  │(Next.js)  │
│ abertos) │ │          │  │           │
└─────────┘ └──────────┘  └────────────┘
```

---

## 🛠️ Desenvolvimento

### Padrões de Código

- **Type hints**: Obrigatórios em todas as funções
- **Docstrings**: Formato Google
- **Formatação**: Black (linha máxima 100)
- **Linting**: Ruff
- **Type checking**: MyPy

### Exemplo

```python
def insert(self, data: OrderedDict, allow_update: bool = False) -> int:
    """
    Insere registros no banco.

    Args:
        data: Dados a inserir (OrderedDict)
        allow_update: Se True, atualiza registros existentes

    Returns:
        Número de registros inseridos/atualizados

    Raises:
        ValueError: Se data estiver vazio
    """
    ...
```

### Rodar Linters

```bash
# Black (formatação)
poetry run black src/ tests/

# Ruff (linting)
poetry run ruff check src/ tests/

# MyPy (type checking)
poetry run mypy src/
```

---

## 📚 Documentação

### Documentação Principal

📖 **[Ver Documentação Completa em docs/](docs/README.md)**

| Documento | Descrição |
|-----------|-----------|
| [docs/README.md](./docs/README.md) | Índice completo da documentação |
| [docs/architecture/overview.md](./docs/architecture/overview.md) | Arquitetura do sistema |
| [docs/database/schema.md](./docs/database/schema.md) | Schemas das tabelas |
| [docs/database/migrations.md](./docs/database/migrations.md) | Guia de setup e migrações |
| [docs/development/setup.md](./docs/development/setup.md) | Setup do ambiente de desenvolvimento |

### Documentação da Migração

| Documento | Descrição |
|-----------|-----------|
| [_plan/README.md](./_plan/README.md) | Plano completo de migração (6 fases) |
| [_plan/PROGRESS.md](./_plan/PROGRESS.md) | Log de progresso |
| [_plan/DECISIONS.md](./_plan/DECISIONS.md) | Decisões arquiteturais (ADRs) |
| [_plan/CHECKLIST.md](./_plan/CHECKLIST.md) | Checklist de verificação por fase |
| [_plan/CONTEXT.md](./_plan/CONTEXT.md) | Contexto técnico para LLMs |

---

## 🔗 Repositórios Relacionados

- [destaquesgovbr/infra](https://github.com/destaquesgovbr/infra) - Terraform (privado)
- [destaquesgovbr/scraper](https://github.com/destaquesgovbr/scraper) - Scrapers
- [destaquesgovbr/portal](https://github.com/destaquesgovbr/portal) - Frontend
- [destaquesgovbr/typesense](https://github.com/destaquesgovbr/typesense) - Search

---

## 📊 Dados Abertos

O dataset completo está disponível no HuggingFace:

- **Dataset completo**: [nitaibezerra/govbrnews](https://huggingface.co/datasets/nitaibezerra/govbrnews)
- **Dataset reduzido**: [nitaibezerra/govbrnews-reduced](https://huggingface.co/datasets/nitaibezerra/govbrnews-reduced)

---

## 🤝 Como Contribuir

### Para LLMs (Claude, GPT, etc)

1. Leia [_plan/CONTEXT.md](_plan/CONTEXT.md)
2. Verifique [_plan/PROGRESS.md](_plan/PROGRESS.md)
3. Consulte [_plan/DECISIONS.md](_plan/DECISIONS.md)
4. Siga [_plan/CHECKLIST.md](_plan/CHECKLIST.md)
5. Atualize PROGRESS.md ao completar tarefas

### Para Desenvolvedores

1. Fork o repositório
2. Crie uma branch (`git checkout -b feature/nova-feature`)
3. Faça suas alterações seguindo os padrões
4. Adicione testes
5. Rode linters e testes
6. Commit (`git commit -m 'feat: adiciona nova feature'`)
7. Push (`git push origin feature/nova-feature`)
8. Abra um Pull Request

---

## 📝 Licença

MIT License - ver [LICENSE](LICENSE) para detalhes.

---

## 📞 Contato

- **Projeto**: DestaquesGovBr
- **Repositório**: [github.com/destaquesgovbr/data-platform](https://github.com/destaquesgovbr/data-platform)
- **Dados**: [huggingface.co/datasets/nitaibezerra/govbrnews](https://huggingface.co/datasets/nitaibezerra/govbrnews)

---

*Última atualização: 2024-12-24*
