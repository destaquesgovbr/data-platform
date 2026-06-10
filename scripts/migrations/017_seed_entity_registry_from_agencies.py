"""
Seed entity_registry + entity_alias from the agencies master table.

Python migration following the runner interface (describe/migrate/rollback),
mirroring 006_migrate_unique_ids.py.

For each agency row (key, name, type, parent_key) it idempotently inserts:
  - one entity_registry row:
        entity_id    = 'dgb_' + key
        canonical_name = name
        type         = 'ORG'
        agency_key   = key
        provenance   = 'agencies_seed'
        confidence   = 1.0
        aliases      = JSON array of distinct surface forms
                       {name, key, trailing-parenthetical acronym, name-without-parenthetical}
  - one entity_alias row per alias:
        alias_norm   = normalize(alias)
        type         = 'ORG'
        entity_id    = 'dgb_' + key
        source       = 'agencies_seed'

Both inserts use ON CONFLICT DO NOTHING, so the migration is re-runnable.
The alias-extraction and normalize() helpers are module-level pure functions so
they can be unit-tested in isolation.

Ref: data-platform#178 (Evolucao do identificador de entidades / NER) — Fase 1.
"""

import re
import time
import unicodedata

PROVENANCE = "agencies_seed"
SOURCE = "agencies_seed"
ENTITY_TYPE = "ORG"
ENTITY_ID_PREFIX = "dgb_"

# Matches a trailing parenthetical group, e.g. "Ministério da Educação (MEC)".
_TRAILING_PAREN_RE = re.compile(r"\s*\(([^()]*)\)\s*$")


# =============================================================================
# Pure helpers (unit-tested)
# =============================================================================


def normalize(s: str | None) -> str:
    """Normalize a surface form into a text key.

    NFKD -> drop non-ASCII -> lowercase -> collapse internal whitespace -> strip.
    Spaces are preserved (this is a text key, not a slug).
    """
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_parenthetical(name: str | None) -> str | None:
    """Return the content of a trailing parenthetical (e.g. the acronym), or None."""
    if not name:
        return None
    match = _TRAILING_PAREN_RE.search(name)
    if not match:
        return None
    inner = match.group(1).strip()
    return inner or None


def strip_parenthetical(name: str | None) -> str:
    """Return the name with a trailing parenthetical removed; no-op if absent."""
    if not name:
        return ""
    return _TRAILING_PAREN_RE.sub("", name).strip()


def extract_aliases(name: str | None, key: str | None) -> list[str]:
    """Build the distinct list of surface forms for an agency.

    Candidates (in stable order): full name, name-without-parenthetical,
    trailing-parenthetical acronym, and the agency key. Empty/whitespace forms
    are dropped and duplicates are removed while preserving first-seen order.
    """
    candidates: list[str] = []
    if name:
        candidates.append(name)
        stripped = strip_parenthetical(name)
        if stripped:
            candidates.append(stripped)
        acronym = extract_parenthetical(name)
        if acronym:
            candidates.append(acronym)
    if key:
        candidates.append(key)

    seen: set[str] = set()
    aliases: list[str] = []
    for c in candidates:
        c = c.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        aliases.append(c)
    return aliases


# =============================================================================
# Database helpers
# =============================================================================


def _fetch_agencies(conn):
    """Fetch all agency rows: (key, name, type, parent_key)."""
    cursor = conn.cursor()
    cursor.execute("SELECT key, name, type, parent_key FROM agencies ORDER BY key")
    rows = cursor.fetchall()
    cursor.close()
    return rows


def _build_rows(agencies):
    """Build (entity_rows, alias_rows) tuples from agency rows.

    entity_rows: (entity_id, canonical_name, type, aliases_list, agency_key, parent_key)
    alias_rows:  (alias_norm, type, entity_id)
    """
    entity_rows = []
    alias_rows = []
    seen_alias_keys: set[tuple[str, str]] = set()

    for key, name, _type, parent_key in agencies:
        entity_id = f"{ENTITY_ID_PREFIX}{key}"
        aliases = extract_aliases(name, key)
        entity_rows.append((entity_id, name, ENTITY_TYPE, aliases, key, parent_key))

        for alias in aliases:
            alias_norm = normalize(alias)
            if not alias_norm:
                continue
            dedup_key = (alias_norm, ENTITY_TYPE)
            # entity_alias PK is (alias_norm, type); dedup within this batch so we
            # don't send conflicting rows for the same key in one execute_batch.
            if dedup_key in seen_alias_keys:
                continue
            seen_alias_keys.add(dedup_key)
            alias_rows.append((alias_norm, ENTITY_TYPE, entity_id))

    return entity_rows, alias_rows


# =============================================================================
# Runner interface
# =============================================================================


def describe() -> str:
    """Human description for logs and audit."""
    return (
        "Semear entity_registry/entity_alias a partir da tabela agencies (provenance=agencies_seed)"
    )


def migrate(conn, dry_run: bool = False) -> dict:
    """Seed entity_registry + entity_alias from agencies. Idempotent.

    conn is a psycopg2 connection without autocommit (the runner manages commit).
    """
    import json

    agencies = _fetch_agencies(conn)
    entity_rows, alias_rows = _build_rows(agencies)

    if dry_run:
        return {
            "agencies": len(agencies),
            "entities_to_insert": len(entity_rows),
            "aliases_to_insert": len(alias_rows),
            "preview": True,
        }

    from psycopg2.extras import execute_batch

    cursor = conn.cursor()
    t0 = time.time()

    entity_params = [
        (
            entity_id,
            canonical_name,
            etype,
            json.dumps(aliases, ensure_ascii=False),
            agency_key,
            json.dumps({"parent_key": parent_key} if parent_key else {}, ensure_ascii=False),
        )
        for (entity_id, canonical_name, etype, aliases, agency_key, parent_key) in entity_rows
    ]
    execute_batch(
        cursor,
        """
        INSERT INTO entity_registry
            (entity_id, canonical_name, type, aliases, wikidata_id, wikidata_url,
             description, agency_key, confidence, provenance, extra)
        VALUES (%s, %s, %s, %s::jsonb, NULL, NULL, NULL, %s, 1.0, '"""
        + PROVENANCE
        + """', %s::jsonb)
        ON CONFLICT (entity_id) DO NOTHING
        """,
        entity_params,
        page_size=500,
    )

    alias_params = [
        (alias_norm, atype, entity_id, SOURCE) for (alias_norm, atype, entity_id) in alias_rows
    ]
    execute_batch(
        cursor,
        """
        INSERT INTO entity_alias (alias_norm, type, entity_id, source, confidence)
        VALUES (%s, %s, %s, %s, 1.0)
        ON CONFLICT (alias_norm, type) DO NOTHING
        """,
        alias_params,
        page_size=500,
    )

    cursor.close()
    elapsed = time.time() - t0

    return {
        "agencies": len(agencies),
        "entities_inserted": len(entity_rows),
        "aliases_inserted": len(alias_rows),
        "elapsed_seconds": round(elapsed, 2),
    }


def rollback(conn, dry_run: bool = False) -> dict:
    """Delete only the rows seeded by this migration (provenance/source = agencies_seed)."""
    cursor = conn.cursor()

    if dry_run:
        cursor.execute("SELECT COUNT(*) FROM entity_alias WHERE source = %s", (SOURCE,))
        aliases_to_delete = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM entity_registry WHERE provenance = %s", (PROVENANCE,))
        entities_to_delete = cursor.fetchone()[0]
        cursor.close()
        return {
            "entities_to_delete": entities_to_delete,
            "aliases_to_delete": aliases_to_delete,
            "preview": True,
        }

    # Delete aliases first (they FK to entity_registry; ON DELETE CASCADE would also
    # cover registry-seeded rows, but we delete explicitly to honor the source filter).
    cursor.execute("DELETE FROM entity_alias WHERE source = %s", (SOURCE,))
    aliases_deleted = cursor.rowcount

    cursor.execute("DELETE FROM entity_registry WHERE provenance = %s", (PROVENANCE,))
    entities_deleted = cursor.rowcount

    cursor.close()

    return {
        "entities_deleted": entities_deleted,
        "aliases_deleted": aliases_deleted,
    }
