"""Unit tests for scripts/migrations/017_seed_entity_registry_from_agencies.py.

Covers the pure, module-level helpers (normalize + alias extraction) and the
Python-migration interface (describe/migrate/rollback), mirroring test_migration_006.py.
"""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


def _import_migration_017():
    """Import the migration module dynamically (numeric prefix not importable directly)."""
    module_path = (
        Path(__file__).parent.parent.parent
        / "scripts"
        / "migrations"
        / "017_seed_entity_registry_from_agencies.py"
    )
    spec = importlib.util.spec_from_file_location("migration_017", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Interface compliance
# ---------------------------------------------------------------------------
class TestMigration017Interface:
    def test_describe_returns_nonempty_string(self):
        mod = _import_migration_017()
        result = mod.describe()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_has_migrate_function(self):
        mod = _import_migration_017()
        assert callable(getattr(mod, "migrate", None))

    def test_has_rollback_function(self):
        mod = _import_migration_017()
        assert callable(getattr(mod, "rollback", None))


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------
class TestNormalize:
    def test_lowercases(self):
        mod = _import_migration_017()
        assert mod.normalize("MEC") == "mec"

    def test_strips_accents(self):
        mod = _import_migration_017()
        assert mod.normalize("Educação") == "educacao"
        assert mod.normalize("Ministério da Saúde") == "ministerio da saude"

    def test_collapses_internal_whitespace(self):
        mod = _import_migration_017()
        assert mod.normalize("Minha   Casa,\tMinha\nVida") == "minha casa, minha vida"

    def test_strips_leading_trailing_whitespace(self):
        mod = _import_migration_017()
        assert mod.normalize("  Finep  ") == "finep"

    def test_keeps_spaces_between_words(self):
        mod = _import_migration_017()
        # It is a text key, not a slug — spaces are preserved.
        assert mod.normalize("Ministério da Educação") == "ministerio da educacao"

    def test_empty_and_none_safe(self):
        mod = _import_migration_017()
        assert mod.normalize("") == ""


# ---------------------------------------------------------------------------
# acronym / parenthetical helpers
# ---------------------------------------------------------------------------
class TestParentheticalAcronym:
    def test_extracts_trailing_acronym(self):
        mod = _import_migration_017()
        assert mod.extract_parenthetical("Ministério da Educação (MEC)") == "MEC"

    def test_returns_none_without_parenthesis(self):
        mod = _import_migration_017()
        assert mod.extract_parenthetical("Ministério da Educação") is None

    def test_strips_parenthetical(self):
        mod = _import_migration_017()
        assert mod.strip_parenthetical("Ministério da Educação (MEC)") == "Ministério da Educação"

    def test_strip_parenthetical_noop_without_parenthesis(self):
        mod = _import_migration_017()
        assert mod.strip_parenthetical("Finep") == "Finep"


# ---------------------------------------------------------------------------
# extract_aliases()
# ---------------------------------------------------------------------------
class TestExtractAliases:
    def test_includes_name_key_acronym_and_stripped(self):
        mod = _import_migration_017()
        aliases = mod.extract_aliases("Ministério da Educação (MEC)", "mec")
        assert "Ministério da Educação (MEC)" in aliases  # original name
        assert "MEC" in aliases  # trailing parenthetical acronym
        assert "Ministério da Educação" in aliases  # name with parenthetical stripped
        assert "mec" in aliases  # the agency key

    def test_no_parenthesis_yields_name_and_key(self):
        mod = _import_migration_017()
        aliases = mod.extract_aliases("Financiadora de Estudos e Projetos", "finep")
        assert "Financiadora de Estudos e Projetos" in aliases
        assert "finep" in aliases
        # no parenthetical -> no acronym, no separate stripped form duplicated
        assert all(a for a in aliases)  # no empty strings

    def test_distinct_no_duplicates(self):
        mod = _import_migration_017()
        # name equal to key -> should not duplicate
        aliases = mod.extract_aliases("Finep", "Finep")
        assert len(aliases) == len(set(aliases))

    def test_no_empty_or_whitespace_aliases(self):
        mod = _import_migration_017()
        aliases = mod.extract_aliases("Casa Civil ()", "casa-civil")
        for a in aliases:
            assert a.strip() == a
            assert a != ""

    def test_order_is_stable_and_deterministic(self):
        mod = _import_migration_017()
        a1 = mod.extract_aliases("Ministério da Saúde (MS)", "saude")
        a2 = mod.extract_aliases("Ministério da Saúde (MS)", "saude")
        assert a1 == a2


# ---------------------------------------------------------------------------
# migrate() / rollback() behavior with mocked connection
# ---------------------------------------------------------------------------
def _make_conn_with_agencies(rows):
    """Build a mock psycopg2 conn whose first SELECT returns the given agency rows."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = rows
    return mock_conn, mock_cursor


class TestMigrate017:
    AGENCIES = [
        # (key, name, type, parent_key)
        ("mec", "Ministério da Educação (MEC)", "Ministério", None),
        ("finep", "Financiadora de Estudos e Projetos", "Empresa", "mcti"),
    ]

    def test_dry_run_returns_counts_and_does_not_commit(self):
        mod = _import_migration_017()
        mock_conn, _ = _make_conn_with_agencies(self.AGENCIES)

        result = mod.migrate(mock_conn, dry_run=True)

        assert isinstance(result, dict)
        assert result.get("preview") is True
        assert result["entities_to_insert"] == 2
        assert result["aliases_to_insert"] >= 2
        mock_conn.commit.assert_not_called()

    def test_dry_run_with_no_agencies(self):
        mod = _import_migration_017()
        mock_conn, _ = _make_conn_with_agencies([])

        result = mod.migrate(mock_conn, dry_run=True)
        assert isinstance(result, dict)
        assert result["entities_to_insert"] == 0
        mock_conn.commit.assert_not_called()

    @patch("psycopg2.extras.execute_batch")
    def test_migrate_returns_dict_with_inserted_counts(self, mock_execute_batch):
        mod = _import_migration_017()
        mock_conn, _ = _make_conn_with_agencies(self.AGENCIES)

        result = mod.migrate(mock_conn, dry_run=False)
        assert isinstance(result, dict)
        assert result["entities_inserted"] == 2
        assert result["aliases_inserted"] >= 2
        # Two execute_batch calls: one for entity_registry, one for entity_alias.
        assert mock_execute_batch.call_count == 2


# ---------------------------------------------------------------------------
# Cross-entity alias collisions (ambiguous surface forms -> resolve to NEITHER)
# ---------------------------------------------------------------------------
class TestAliasCollisions:
    # Real-world collision from agencies.yaml: two distinct keys share the same name.
    COLLIDING_AGENCIES = [
        ("casacivil", "Casa Civil da Presidência da República", "Órgão", "presidencia"),
        ("planalto", "Casa Civil da Presidência da República", "Órgão", "presidencia"),
    ]

    def _build(self, mod, agencies):
        """Call _build_rows and normalize its return into (entities, aliases, collisions)."""
        result = mod._build_rows(agencies)
        # _build_rows must now also surface the dropped ambiguous keys.
        assert len(result) == 3, "_build_rows must return (entity_rows, alias_rows, collisions)"
        return result

    def test_both_registry_rows_created_despite_collision(self):
        mod = _import_migration_017()
        entity_rows, _alias_rows, _collisions = self._build(mod, self.COLLIDING_AGENCIES)
        entity_ids = {row[0] for row in entity_rows}
        # (a) BOTH entities exist in the registry.
        assert entity_ids == {"dgb_casacivil", "dgb_planalto"}

    def test_colliding_alias_inserted_for_neither(self):
        mod = _import_migration_017()
        _entity_rows, alias_rows, _collisions = self._build(mod, self.COLLIDING_AGENCIES)

        collide_norm = mod.normalize("Casa Civil da Presidência da República")
        # (b) The ambiguous (alias_norm, 'ORG') key is inserted for NEITHER entity.
        for alias_norm, atype, _entity_id in alias_rows:
            assert not (
                alias_norm == collide_norm and atype == "ORG"
            ), "ambiguous alias must not be inserted for any entity"

        # The unambiguous keys (the agency keys themselves) survive.
        surviving = {(a, t) for a, t, _e in alias_rows}
        assert ("casacivil", "ORG") in surviving
        assert ("planalto", "ORG") in surviving

    def test_collision_recorded_in_build_rows(self):
        mod = _import_migration_017()
        _entity_rows, _alias_rows, collisions = self._build(mod, self.COLLIDING_AGENCIES)
        collide_norm = mod.normalize("Casa Civil da Presidência da República")
        assert [collide_norm, "ORG"] in collisions or (collide_norm, "ORG") in collisions

    def test_registry_aliases_jsonb_intact_for_both(self):
        mod = _import_migration_017()
        entity_rows, _alias_rows, _collisions = self._build(mod, self.COLLIDING_AGENCIES)
        # (per-entity display field is NOT pruned) — both keep the full name in their aliases.
        by_id = {row[0]: row[3] for row in entity_rows}  # entity_id -> aliases list
        assert "Casa Civil da Presidência da República" in by_id["dgb_casacivil"]
        assert "Casa Civil da Presidência da República" in by_id["dgb_planalto"]

    def test_single_entity_multiple_surface_forms_not_a_collision(self):
        mod = _import_migration_017()
        # name and key both normalize distinctly; "MEC" appears once -> 1 entity, no collision.
        agencies = [("mec", "Ministério da Educação (MEC)", "Ministério", None)]
        _entity_rows, alias_rows, collisions = self._build(mod, agencies)
        assert collisions == []
        # the alias key for the canonical name resolves to the single entity.
        name_norm = mod.normalize("Ministério da Educação")
        owners = {e for a, t, e in alias_rows if a == name_norm and t == "ORG"}
        assert owners == {"dgb_mec"}

    @patch("psycopg2.extras.execute_batch")
    def test_migrate_surfaces_collisions_in_result(self, mock_execute_batch):
        mod = _import_migration_017()
        mock_conn, _ = _make_conn_with_agencies(self.COLLIDING_AGENCIES)

        result = mod.migrate(mock_conn, dry_run=False)
        assert result["entities_inserted"] == 2
        assert "alias_collisions" in result
        assert "alias_collisions_dropped" in result
        assert result["alias_collisions_dropped"] == 1
        collide_norm = mod.normalize("Casa Civil da Presidência da República")
        flat = [tuple(x) if isinstance(x, list) else x for x in result["alias_collisions"]]
        assert (collide_norm, "ORG") in flat

    def test_dry_run_surfaces_collisions(self):
        mod = _import_migration_017()
        mock_conn, _ = _make_conn_with_agencies(self.COLLIDING_AGENCIES)
        result = mod.migrate(mock_conn, dry_run=True)
        assert result.get("preview") is True
        assert result["alias_collisions_dropped"] == 1

    def test_rollback_returns_dict(self):
        mod = _import_migration_017()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # rowcounts for the two DELETEs
        type(mock_cursor).rowcount = 3

        result = mod.rollback(mock_conn, dry_run=False)
        assert isinstance(result, dict)
        assert "entities_deleted" in result
        assert "aliases_deleted" in result

    def test_rollback_dry_run_does_not_commit(self):
        mod = _import_migration_017()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.side_effect = [(2,), (5,)]

        result = mod.rollback(mock_conn, dry_run=True)
        assert isinstance(result, dict)
        assert result.get("preview") is True
        mock_conn.commit.assert_not_called()
