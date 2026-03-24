"""Processamento e persistência de resultados de verificação de integridade."""

import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

UPSERT_SQL = text("""
    INSERT INTO news_features (unique_id, features)
    VALUES (:uid, jsonb_build_object('integrity', :integrity_fields::jsonb))
    ON CONFLICT (unique_id) DO UPDATE
    SET features = jsonb_set(
        COALESCE(news_features.features, '{}'),
        '{integrity}',
        COALESCE(news_features.features -> 'integrity', '{}') || :integrity_fields::jsonb
    ),
        updated_at = NOW()
""")

LOAD_STATE_SQL = text("""
    SELECT unique_id,
           COALESCE((features -> 'integrity' ->> 'check_count')::int, 0) AS check_count,
           features -> 'integrity' ->> 'image_status' AS image_status
    FROM news_features
    WHERE unique_id = ANY(:uids)
""")


def upsert_integrity_results(db_url: str, results: list[dict]) -> dict:
    """Upsert resultados de integridade no news_features.features.integrity.

    Args:
        db_url: PostgreSQL connection string.
        results: Lista de dicts com unique_id e campos de integridade.

    Returns:
        Dict com broken_ids (imagens quebradas) e fixed_ids (imagens restauradas).
    """
    if not results:
        return {"broken_ids": [], "fixed_ids": [], "count": 0}

    engine = create_engine(db_url, poolclass=NullPool)
    count = 0
    broken_ids = []
    fixed_ids = []

    try:
        with engine.begin() as conn:
            # Pré-carregar estado atual em batch (resolve N+1)
            unique_ids = [r["unique_id"] for r in results if r.get("unique_id")]
            existing_state = _load_existing_state(conn, unique_ids)

            for r in results:
                uid = r.get("unique_id")
                if not uid:
                    continue

                state = existing_state.get(uid, {})
                previous_image_status = state.get("image_status")

                # Montar objeto integrity para merge
                integrity = {}
                for key in (
                    "image_status", "image_http_code", "image_checked_at",
                    "image_content_type", "content_status", "content_hash",
                    "content_checked_at", "source_etag", "new_image_url",
                ):
                    if key in r:
                        integrity[key] = r[key]

                integrity["check_count"] = state.get("check_count", 0) + 1

                conn.execute(UPSERT_SQL, {
                    "uid": uid,
                    "integrity_fields": json.dumps(integrity),
                })
                count += 1

                # Rastrear mudanças de status de imagem
                if r.get("image_status") == "broken":
                    broken_ids.append(uid)
                elif r.get("image_status") == "ok" and previous_image_status == "broken":
                    fixed_ids.append(uid)

        logger.info(
            f"Upsert de integridade: {count} artigos, "
            f"{len(broken_ids)} quebrados, {len(fixed_ids)} restaurados"
        )
    finally:
        engine.dispose()

    return {"broken_ids": broken_ids, "fixed_ids": fixed_ids, "count": count}


def _load_existing_state(conn, unique_ids: list[str]) -> dict:
    """Carrega check_count e image_status atuais em batch."""
    if not unique_ids:
        return {}
    rows = conn.execute(LOAD_STATE_SQL, {"uids": unique_ids}).fetchall()
    return {
        r.unique_id: {"check_count": r.check_count, "image_status": r.image_status}
        for r in rows
    }


def sync_image_status_to_typesense(
    typesense_client,
    collection_name: str,
    broken_ids: list[str],
    fixed_ids: list[str],
) -> int:
    """Atualiza campo image_broken nos documentos Typesense.

    Args:
        typesense_client: Cliente Typesense configurado.
        collection_name: Nome da collection.
        broken_ids: IDs de artigos com imagem quebrada.
        fixed_ids: IDs de artigos com imagem restaurada.

    Returns:
        Número de documentos atualizados.
    """
    updated = 0

    for uid in broken_ids:
        try:
            typesense_client.collections[collection_name].documents[uid].update(
                {"image_broken": True}
            )
            updated += 1
        except Exception as e:
            logger.warning(f"Erro ao atualizar Typesense para {uid}: {e}")

    for uid in fixed_ids:
        try:
            typesense_client.collections[collection_name].documents[uid].update(
                {"image_broken": False}
            )
            updated += 1
        except Exception as e:
            logger.warning(f"Erro ao atualizar Typesense para {uid}: {e}")

    if updated:
        logger.info(f"Typesense atualizado: {updated} documentos")

    return updated
