"""Consistency checks for the PostgreSQL migration files (scripts/migrations/).

scripts/migrate.py keys migration history by the 3-digit version, so two files
with the same number make one of them invisible to the runner.
"""

import importlib.util
import re
from collections import defaultdict
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parents[2] / "scripts" / "migrations"
MIGRATE_SCRIPT = MIGRATIONS_DIR.parent / "migrate.py"
MIGRATION_PATTERN = re.compile(r"^(\d{3})_(.+)\.(sql|py)$")
ROLLBACK_SUFFIX = "_rollback.sql"


def _reserved_versions() -> set[int]:
    """RESERVED_VERSIONS do runner (fonte única, a mesma do `migrate.py validate`)."""
    spec = importlib.util.spec_from_file_location("migrate_runner", MIGRATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {int(v) for v in module.RESERVED_VERSIONS}


def _files_by_version(rollback: bool) -> dict[str, list[str]]:
    by_version = defaultdict(list)
    for f in MIGRATIONS_DIR.iterdir():
        match = MIGRATION_PATTERN.match(f.name)
        if match and f.name.endswith(ROLLBACK_SUFFIX) == rollback:
            by_version[match.group(1)].append(f.name)
    return by_version


class TestPgMigrationFiles:
    def test_migrations_dir_exists(self):
        assert MIGRATIONS_DIR.is_dir()

    def test_migration_versions_are_unique(self):
        duplicates = {v: names for v, names in _files_by_version(False).items() if len(names) > 1}
        assert duplicates == {}, f"Duplicate migration versions: {duplicates}"

    def test_rollback_versions_are_unique(self):
        duplicates = {v: names for v, names in _files_by_version(True).items() if len(names) > 1}
        assert duplicates == {}, f"Duplicate rollback versions: {duplicates}"

    def test_every_rollback_matches_its_migration(self):
        stems = {Path(n).stem for names in _files_by_version(False).values() for n in names}
        for names in _files_by_version(True).values():
            for name in names:
                expected = name.removesuffix(ROLLBACK_SUFFIX)
                assert expected in stems, f"{name} has no matching migration {expected}.*"

    def test_versions_have_no_gaps(self):
        """Só as versões reservadas a PRs abertos (RESERVED_VERSIONS) podem faltar."""
        versions = {int(v) for v in _files_by_version(False)}
        missing = set(range(1, max(versions) + 1)) - versions - _reserved_versions()
        assert missing == set(), f"Sequence gap: {sorted(missing)}"
