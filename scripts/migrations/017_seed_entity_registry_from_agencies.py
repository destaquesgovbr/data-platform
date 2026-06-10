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

Cross-entity alias collisions: ``entity_alias`` has PK ``(alias_norm, type)`` and
is the deterministic cross-entity resolver. If a surface form normalizes to the
same key for MORE THAN ONE distinct entity (e.g. "Casa Civil da Presidência da
República" shared by keys ``casacivil`` and ``planalto``), it is genuinely
ambiguous and is inserted for NEITHER entity — all rows for that key are dropped
and reported (``alias_collisions``) so the mention is later forced to the
LLM / needs_review path instead of being silently misresolved. The per-entity
``entity_registry.aliases`` JSONB stays intact for both entities (display field).

Ref: data-platform#178 (Evolucao do identificador de entidades / NER) — Fase 1.
"""

import re
import time
import unicodedata

from loguru import logger

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
    """Build (entity_rows, alias_rows, collisions) from agency rows.

    entity_rows: (entity_id, canonical_name, type, aliases_list, agency_key, parent_key)
    alias_rows:  (alias_norm, type, entity_id)  — ONLY unambiguous keys
    collisions:  sorted list of (alias_norm, type) keys that map to >1 distinct
                 entity_id and were therefore excluded from alias_rows entirely.

    The entity_alias table is the cross-entity deterministic resolver: an
    (alias_norm, type) is a unique key, so it can only point to one entity. A
    surface form that normalizes to the same key across DIFFERENT entities is
    genuinely ambiguous and must resolve to NEITHER — we drop ALL rows for that
    key so the mention is forced to the LLM / needs_review path later, instead
    of silently (and wrongly) being awarded to whichever entity sorts first.

    The per-entity ``entity_registry.aliases`` JSONB list is left intact for
    every entity — it is a display/provenance field, not the resolver.
    """
    entity_rows = []
    # (alias_norm, type) -> ordered list of distinct entity_ids claiming it
    owners: dict[tuple[str, str], list[str]] = {}

    for key, name, _type, parent_key in agencies:
        entity_id = f"{ENTITY_ID_PREFIX}{key}"
        aliases = extract_aliases(name, key)
        entity_rows.append((entity_id, name, ENTITY_TYPE, aliases, key, parent_key))

        seen_for_entity: set[tuple[str, str]] = set()
        for alias in aliases:
            alias_norm = normalize(alias)
            if not alias_norm:
                continue
            dedup_key = (alias_norm, ENTITY_TYPE)
            # Within a single entity the same key may surface from several forms
            # (e.g. name == key); count the entity only once per key.
            if dedup_key in seen_for_entity:
                continue
            seen_for_entity.add(dedup_key)
            owner_list = owners.setdefault(dedup_key, [])
            if entity_id not in owner_list:
                owner_list.append(entity_id)

    alias_rows = []
    collisions = []
    for (alias_norm, atype), owner_ids in owners.items():
        if len(owner_ids) > 1:
            # Ambiguous across distinct entities -> resolve to NEITHER.
            collisions.append((alias_norm, atype))
            continue
        alias_rows.append((alias_norm, atype, owner_ids[0]))

    collisions.sort()
    return entity_rows, alias_rows, collisions


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
    entity_rows, alias_rows, collisions = _build_rows(agencies)

    # Surface ambiguous surface forms that were excluded from the resolver so they
    # land in migration_history.execution_details and the logs (never drop silently).
    collisions_payload = [[alias_norm, atype] for (alias_norm, atype) in collisions]
    if collisions:
        logger.warning(
            f"{len(collisions)} alias(es) ambiguo(s) across distinct entities — "
            f"excluidos de entity_alias (resolvem para NENHUMA entidade, vao para LLM/needs_review): "
            f"{collisions_payload}"
        )
    else:
        logger.info("Nenhuma colisao de alias entre entidades distintas.")

    if dry_run:
        return {
            "agencies": len(agencies),
            "entities_to_insert": len(entity_rows),
            "aliases_to_insert": len(alias_rows),
            "alias_collisions": collisions_payload,
            "alias_collisions_dropped": len(collisions),
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
        "alias_collisions": collisions_payload,
        "alias_collisions_dropped": len(collisions),
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
