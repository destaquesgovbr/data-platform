"""Atualiza o snapshot ``tests/fixtures/graphql_api_schema.graphql`` por introspecção.

O snapshot é a referência do teste de contrato
(``tests/unit/clients/test_graphql_contract.py``): toda constante ``*_QUERY`` e
``*_MUTATION`` de ``data_platform.clients.graphql_client`` é validada contra ele.

Uso (a partir da raiz do repo, com a venv do projeto):

    python tests/fixtures/refresh_graphql_schema.py            # regrava o snapshot
    python tests/fixtures/refresh_graphql_schema.py --check    # só compara (exit 1 se divergir)
    python tests/fixtures/refresh_graphql_schema.py --url URL  # outra instância da graphql-api

Segurança: só envia a query de introspecção, sem autenticação. O script recusa
qualquer documento que não seja uma operação ``query``; nunca envia mutation.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

import httpx
from graphql import (
    OperationDefinitionNode,
    OperationType,
    build_client_schema,
    get_introspection_query,
    parse,
    print_schema,
)

DEFAULT_URL = "https://destaquesgovbr-graphql-api-klvx64dufq-rj.a.run.app/graphql"
SNAPSHOT_PATH = Path(__file__).with_name("graphql_api_schema.graphql")


def introspection_query() -> str:
    """Query de introspecção padrão, conferida como operação de leitura."""
    query = get_introspection_query(descriptions=True)
    operations = [d for d in parse(query).definitions if isinstance(d, OperationDefinitionNode)]
    if not operations or any(op.operation is not OperationType.QUERY for op in operations):
        raise RuntimeError("documento de introspecção não é uma query de leitura")
    return query


def fetch_sdl(url: str = DEFAULT_URL, *, timeout: float = 30.0) -> str:
    """Introspecção ao vivo → SDL impresso (com newline final)."""
    resp = httpx.post(url, json={"query": introspection_query()}, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"introspecção falhou: {body['errors']}")
    schema = build_client_schema(body["data"])
    return print_schema(schema) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default=DEFAULT_URL, help="endpoint GraphQL")
    parser.add_argument("--out", type=Path, default=SNAPSHOT_PATH, help="arquivo de saída")
    parser.add_argument(
        "--check", action="store_true", help="só compara com o snapshot; exit 1 se divergir"
    )
    args = parser.parse_args(argv)

    sdl = fetch_sdl(args.url)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current == sdl:
            print(f"snapshot em dia: {args.out}")
            return 0
        diff = difflib.unified_diff(
            current.splitlines(keepends=True),
            sdl.splitlines(keepends=True),
            fromfile=str(args.out),
            tofile=args.url,
        )
        sys.stdout.writelines(diff)
        return 1

    args.out.write_text(sdl, encoding="utf-8")
    print(f"snapshot gravado: {args.out} ({len(sdl.splitlines())} linhas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
