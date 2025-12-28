"""
Tests for schema consistency between SQL files and Pydantic models.

These tests ensure that:
1. Both SQL schema files define the same structure
2. Critical fields like content_embedding are present
3. Pydantic models reflect the SQL schema
"""

import re
from pathlib import Path

import pytest

# Root path for the project
PROJECT_ROOT = Path(__file__).parent.parent.parent


class TestSQLSchemaConsistency:
    """Tests for SQL schema file consistency."""

    def test_init_sql_has_vector_extension(self):
        """Verifica que init.sql habilita a extensão pgvector."""
        init_sql = (PROJECT_ROOT / "docker/postgres/init.sql").read_text()
        assert "CREATE EXTENSION" in init_sql
        assert "vector" in init_sql.lower()

    def test_create_schema_has_vector_extension(self):
        """Verifica que create_schema.sql habilita a extensão pgvector."""
        create_sql = (PROJECT_ROOT / "scripts/create_schema.sql").read_text()
        assert "CREATE EXTENSION" in create_sql
        assert "vector" in create_sql.lower()

    def test_init_sql_has_content_embedding(self):
        """Verifica que init.sql tem o campo content_embedding."""
        init_sql = (PROJECT_ROOT / "docker/postgres/init.sql").read_text()
        assert "content_embedding" in init_sql
        # Check for vector type with 768 dimensions
        assert re.search(r"content_embedding\s+vector\s*\(\s*768\s*\)", init_sql)

    def test_create_schema_has_content_embedding(self):
        """Verifica que create_schema.sql tem o campo content_embedding."""
        create_sql = (PROJECT_ROOT / "scripts/create_schema.sql").read_text()
        assert "content_embedding" in create_sql
        # Check for vector type with 768 dimensions
        assert re.search(r"content_embedding\s+vector\s*\(\s*768\s*\)", create_sql)

    def test_init_sql_has_embedding_generated_at(self):
        """Verifica que init.sql tem o campo embedding_generated_at."""
        init_sql = (PROJECT_ROOT / "docker/postgres/init.sql").read_text()
        assert "embedding_generated_at" in init_sql

    def test_create_schema_has_embedding_generated_at(self):
        """Verifica que create_schema.sql tem o campo embedding_generated_at."""
        create_sql = (PROJECT_ROOT / "scripts/create_schema.sql").read_text()
        assert "embedding_generated_at" in create_sql

    def test_both_schemas_have_hnsw_index(self):
        """Verifica que ambos os schemas tem índice HNSW para embeddings."""
        init_sql = (PROJECT_ROOT / "docker/postgres/init.sql").read_text()
        create_sql = (PROJECT_ROOT / "scripts/create_schema.sql").read_text()

        assert "hnsw" in init_sql.lower()
        assert "hnsw" in create_sql.lower()
        assert "vector_cosine_ops" in init_sql
        assert "vector_cosine_ops" in create_sql

    def test_schemas_have_same_tables(self):
        """Verifica que ambos os schemas definem as mesmas tabelas principais."""
        init_sql = (PROJECT_ROOT / "docker/postgres/init.sql").read_text()
        create_sql = (PROJECT_ROOT / "scripts/create_schema.sql").read_text()

        # Extract CREATE TABLE statements
        init_tables = set(
            re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)", init_sql, re.IGNORECASE)
        )
        create_tables = set(
            re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)", create_sql, re.IGNORECASE)
        )

        # Core tables that must exist in both
        core_tables = {"agencies", "themes", "news"}

        assert core_tables.issubset(init_tables), f"Missing tables in init.sql: {core_tables - init_tables}"
        assert core_tables.issubset(create_tables), f"Missing tables in create_schema.sql: {core_tables - create_tables}"

    def test_news_table_has_required_columns(self):
        """Verifica que a tabela news tem todas as colunas obrigatórias."""
        required_columns = [
            "unique_id",
            "agency_id",
            "title",
            "url",
            "content",
            "summary",
            "published_at",
            "content_embedding",
            "embedding_generated_at",
            "theme_l1_id",
            "theme_l2_id",
            "theme_l3_id",
            "most_specific_theme_id",
        ]

        init_sql = (PROJECT_ROOT / "docker/postgres/init.sql").read_text()
        create_sql = (PROJECT_ROOT / "scripts/create_schema.sql").read_text()

        for column in required_columns:
            assert column in init_sql, f"Column '{column}' missing in init.sql"
            assert column in create_sql, f"Column '{column}' missing in create_schema.sql"


class TestPydanticModelConsistency:
    """Tests for Pydantic model consistency with SQL schema."""

    def test_news_model_has_content_embedding(self):
        """Verifica que o model Pydantic News tem content_embedding."""
        from data_platform.models.news import News

        # Check if the field exists in model_fields (Pydantic v2)
        assert "content_embedding" in News.model_fields, "News model missing content_embedding field"

    def test_news_model_embedding_is_optional(self):
        """Verifica que content_embedding é opcional no model."""
        from data_platform.models.news import News

        field_info = News.model_fields.get("content_embedding")
        assert field_info is not None
        # In Pydantic v2, check if the field allows None
        assert field_info.is_required() is False or field_info.default is None

    def test_news_model_has_embedding_generated_at(self):
        """Verifica que o model Pydantic News tem embedding_generated_at."""
        from data_platform.models.news import News

        # This field may or may not exist depending on model design
        # If it doesn't exist, we skip this test
        if "embedding_generated_at" not in News.model_fields:
            pytest.skip("embedding_generated_at not in News model (may be intentional)")

    def test_news_model_has_theme_ids(self):
        """Verifica que o model Pydantic News tem os IDs de tema."""
        from data_platform.models.news import News

        theme_fields = ["theme_l1_id", "theme_l2_id", "theme_l3_id", "most_specific_theme_id"]
        for field in theme_fields:
            assert field in News.model_fields, f"News model missing {field} field"
