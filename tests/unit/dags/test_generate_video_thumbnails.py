"""Unit tests for generate_video_thumbnails DAG.

Airflow is not installed locally and the DAG module executes
dag_instance = generate_video_thumbnails_dag() at import time,
so we use AST-based structural tests and exec-based isolation
for testing the _process_one helper.
"""

import ast
import base64
import json
import textwrap
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

DAG_FILE = Path("src/data_platform/dags/generate_video_thumbnails.py")


def _parse_dag_ast() -> ast.Module:
    """Parse the DAG file AST for structural tests."""
    return ast.parse(DAG_FILE.read_text())


class TestFetchBatchEngineDispose:
    """Verify that fetch_batch wraps engine usage in try/finally with dispose."""

    def test_engine_dispose_in_finally_block(self) -> None:
        """engine.dispose() must be called in a finally block."""
        tree = _parse_dag_ast()

        fetch_batch_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "fetch_batch":
                fetch_batch_fn = node
                break

        assert fetch_batch_fn is not None, "fetch_batch function not found"

        has_try_finally = False
        for node in ast.walk(fetch_batch_fn):
            if isinstance(node, ast.Try) and node.finalbody:
                for stmt in node.finalbody:
                    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                        call = stmt.value
                        if isinstance(call.func, ast.Attribute) and call.func.attr == "dispose":
                            has_try_finally = True

        assert (
            has_try_finally
        ), "fetch_batch must wrap engine usage in try/finally with engine.dispose()"


class TestGenerateThumbnailsParallel:
    """Verify that generate_thumbnails uses ThreadPoolExecutor."""

    def test_uses_thread_pool_executor(self) -> None:
        """generate_thumbnails must use ThreadPoolExecutor for parallel processing."""
        tree = _parse_dag_ast()

        gen_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "generate_thumbnails":
                gen_fn = node
                break

        assert gen_fn is not None, "generate_thumbnails function not found"

        source = DAG_FILE.read_text()
        fn_source = ast.get_source_segment(source, gen_fn)
        assert "ThreadPoolExecutor" in fn_source, "generate_thumbnails must use ThreadPoolExecutor"

    def test_has_process_one_function(self) -> None:
        """A _process_one helper must exist at module level for testability."""
        tree = _parse_dag_ast()

        found = False
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_process_one":
                found = True
                break

        assert found, "_process_one function must exist at module level"


def _load_process_one():
    """Load _process_one from DAG source without importing airflow.

    Extracts the function source + its dependencies and exec's them
    in an isolated namespace.
    """
    source = DAG_FILE.read_text()
    tree = ast.parse(source)

    # Find _process_one function node
    fn_node = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_one":
            fn_node = node
            break

    if fn_node is None:
        return None

    fn_source = ast.get_source_segment(source, fn_node)

    # Build a minimal namespace with required imports
    ns: dict = {}
    exec(
        textwrap.dedent(
            """
        import base64
        import json
        import logging
        import requests

        logger = logging.getLogger("test")
        WORKER_REQUEST_TIMEOUT = 60
        """
        ),
        ns,
    )
    exec(fn_source, ns)
    return ns["_process_one"]


class TestProcessOne:
    """Tests for the _process_one helper function."""

    @pytest.fixture()
    def process_one(self):
        fn = _load_process_one()
        if fn is None:
            pytest.skip("_process_one not found in DAG source")
        return fn

    @patch("requests.post")
    def test_returns_status_on_success(self, mock_post, process_one) -> None:
        mock_post.return_value = Mock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=Mock(return_value={"status": "generated"}),
            raise_for_status=Mock(),
        )
        uid, status = process_one({"unique_id": "a1"}, "http://worker")
        assert uid == "a1"
        assert status == "generated"

    @patch("requests.post")
    def test_returns_failed_on_exception(self, mock_post, process_one) -> None:
        mock_post.side_effect = Exception("connection refused")
        uid, status = process_one({"unique_id": "a1"}, "http://worker")
        assert uid == "a1"
        assert status == "failed"

    @patch("requests.post")
    def test_sends_correct_pubsub_envelope(self, mock_post, process_one) -> None:
        mock_post.return_value = Mock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=Mock(return_value={"status": "generated"}),
            raise_for_status=Mock(),
        )
        process_one({"unique_id": "test_uid"}, "http://worker")

        call_kwargs = mock_post.call_args[1]
        envelope = call_kwargs["json"]
        decoded = json.loads(base64.b64decode(envelope["message"]["data"]))
        assert decoded == {"unique_id": "test_uid"}
