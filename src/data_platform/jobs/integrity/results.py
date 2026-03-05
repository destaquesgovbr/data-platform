"""Processamento e persistência de resultados de verificação de integridade."""

import json
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

UPSERT_SQL = text("""
    INSERT INTO news_features (unique_id, features)
    VALUES (:uid, :features)
    ON CONFLICT (unique_id) DO UPDATE
    SET features = news_features.features || :features,
        updated_at = NOW()
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
            for r in results:
                uid = r.get("unique_id")
                if not uid:
                    continue

                # Montar objeto integrity para merge
                integrity = {}
                for key in (
                    "image_status", "image_http_code", "image_checked_at",
                    "image_content_type", "content_status", "content_hash",
                    "content_checked_at", "source_etag", "new_image_url",
                ):
                    if key in r:
                        integrity[key] = r[key]

                # Incrementar check_count
                integrity["check_count"] = _get_current_check_count(conn, uid) + 1

                features = json.dumps({"integrity": integrity})
                conn.execute(UPSERT_SQL, {"uid": uid, "features": features})
                count += 1

                # Rastrear mudanças de status de imagem
                if r.get("image_status") == "broken":
                    broken_ids.append(uid)
                elif r.get("image_status") == "ok":
                    # Verificar se era broken antes (agora foi corrigido)
                    if _was_previously_broken(conn, uid):
                        fixed_ids.append(uid)

        logger.info(
            f"Upsert de integridade: {count} artigos, "
            f"{len(broken_ids)} quebrados, {len(fixed_ids)} restaurados"
        )
    finally:
        engine.dispose()

    return {"broken_ids": broken_ids, "fixed_ids": fixed_ids, "count": count}


def _get_current_check_count(conn, unique_id: str) -> int:
    """Busca check_count atual do artigo."""
    result = conn.execute(
        text("""
            SELECT COALESCE(
                (features -> 'integrity' ->> 'check_count')::int,
                0
            ) FROM news_features WHERE unique_id = :uid
        """),
        {"uid": unique_id},
    ).scalar()
    return result or 0


def _was_previously_broken(conn, unique_id: str) -> bool:
    """Verifica se o artigo tinha image_status = 'broken' antes."""
    result = conn.execute(
        text("""
            SELECT features -> 'integrity' ->> 'image_status'
            FROM news_features WHERE unique_id = :uid
        """),
        {"uid": unique_id},
    ).scalar()
    return result == "broken"


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
