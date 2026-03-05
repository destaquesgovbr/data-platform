"""Testes unitários para processamento de resultados de integridade."""

from unittest.mock import MagicMock, call

from data_platform.jobs.integrity.results import sync_image_status_to_typesense


class TestSyncImageStatusToTypesense:
    """Testes para sincronização de status com Typesense."""

    def test_no_changes(self):
        client = MagicMock()
        result = sync_image_status_to_typesense(client, "news", [], [])
        assert result == 0

    def test_marks_broken_images(self):
        client = MagicMock()
        result = sync_image_status_to_typesense(
            client, "news", broken_ids=["abc", "def"], fixed_ids=[]
        )
        assert result == 2

        calls = client.collections["news"].documents.__getitem__.call_args_list
        assert len(calls) == 2

    def test_marks_fixed_images(self):
        client = MagicMock()
        result = sync_image_status_to_typesense(
            client, "news", broken_ids=[], fixed_ids=["abc"]
        )
        assert result == 1

    def test_handles_typesense_error(self):
        client = MagicMock()
        client.collections.__getitem__.return_value.documents.__getitem__.return_value.update.side_effect = Exception("Not found")

        # Não deve levantar exceção
        result = sync_image_status_to_typesense(
            client, "news", broken_ids=["abc"], fixed_ids=[]
        )
        assert result == 0
