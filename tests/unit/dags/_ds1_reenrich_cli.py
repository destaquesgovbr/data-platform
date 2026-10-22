"""Cópia da CLI do reenrich_combined_window.py do DS-1 (contrato do DAG enrichment_backfill).

Origem: repo data-science, PR #49 (DS-1, tema 26), scripts/reenrich_combined_window.py no
commit a6fe906: constantes de seleção, `_iso_date`, `_theme_code_arg`, `_extra_codes_arg`,
`build_arg_parser` e `_theme_args_error`, copiados sem mudança de lógica. O script
importa o worker do data-science (Bedrock, banco), que não existe aqui; por isso a cópia.

O teste de contrato (test_enrichment_backfill.py, TestContratoComACliDoDs1) passa os args
que o DAG monta por esse parser e por essa validação, como o Job faria. Se o DS-1 mudar a
CLI, atualizar esta cópia no mesmo passo (e o DAG, se o contrato mudar).
"""

import argparse
import datetime
import re

SELECT_CHOICES = ("null-theme", "mock", "null-summary", "theme-code", "theme26-candidates")
THEME_SELECTS = frozenset({"theme-code", "theme26-candidates"})
DEFAULT_EXTRA_CODES = ("04", "05.02.01", "15.02.03")
TERM_FIELDS = {"title": ("n.title",), "title-content": ("n.title", "n.content")}
DEFAULT_TERM_FIELDS = "title"
_CODE_RE = re.compile(r"^\d{2}(?:\.\d{2}){0,2}$")
_CAMPAIGN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,49}$")


def _iso_date(value: str) -> str:
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"data inválida {value!r} (use AAAA-MM-DD)") from e


def _theme_code_arg(value: str) -> str:
    if not _CODE_RE.match(value):
        raise argparse.ArgumentTypeError(
            f"código de tema inválido {value!r} (use NN, NN.NN ou NN.NN.NN)"
        )
    return value


def _extra_codes_arg(value: str) -> tuple:
    """Lista de códigos separados por vírgula; vazio = nenhum código extra."""
    if not value.strip():
        return ()
    codes = tuple(part.strip() for part in value.split(","))
    for code in codes:
        if not _CODE_RE.match(code):
            raise argparse.ArgumentTypeError(
                f"--extra-codes: código inválido {code!r} (use NN, NN.NN ou NN.NN.NN, "
                "separados por vírgula; vazio = nenhum)"
            )
    return codes


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--select",
        choices=SELECT_CHOICES,
        required=True,
        help="null-theme: tema NULL na janela; mock: summary LIKE '[MOCK]%%' na janela; "
        "null-summary: tema gravado e summary NULL na janela (só o resumo, prompt enxuto); "
        "theme-code: subárvore de --theme-code; theme26-candidates: candidatos ao tema 26 "
        "(as duas últimas só com --theme-only e --campaign)",
    )
    ap.add_argument(
        "--theme-code",
        type=_theme_code_arg,
        default=None,
        help="código da subárvore (só com --select theme-code), ex.: 19",
    )
    ap.add_argument(
        "--theme-only",
        action="store_true",
        help="grava SÓ os ids de tema, com guarda e auditoria em news_theme_changes "
        "(obrigatório nas seleções de tema; proibido nas demais)",
    )
    ap.add_argument(
        "--campaign",
        default=None,
        help="campanha da auditoria (obrigatória com --theme-only), ex.: tema26-llm-d1; "
        "[a-z0-9._-], até 50 caracteres; os já auditados nela saem da seleção",
    )
    ap.add_argument(
        "--term-fields",
        choices=tuple(TERM_FIELDS),
        default=None,
        help=f"theme26-candidates: onde buscar os termos (padrão {DEFAULT_TERM_FIELDS}: "
        "só o título; title-content inclui o conteúdo)",
    )
    ap.add_argument(
        "--extra-codes",
        type=_extra_codes_arg,
        default=None,
        help="theme26-candidates: códigos do bloco extra, separados por vírgula "
        f"(padrão {','.join(DEFAULT_EXTRA_CODES)}; '' = nenhum, só o bloco do 19)",
    )
    ap.add_argument(
        "--date-from", type=_iso_date, required=True, help="dia BRT inicial (inclusivo)"
    )
    ap.add_argument(
        "--date-to",
        type=_iso_date,
        default=None,
        help="dia BRT final (EXCLUSIVO). Obrigatório com --select null-theme e "
        "null-summary, e no máximo hoje (BRT); opcional com --select mock",
    )
    ap.add_argument("--limit", type=int, default=500, help="teto de artigos neste run")
    ap.add_argument("--workers", type=int, default=1, help="concorrência de chamadas Bedrock")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="só seleciona e lista; não chama o Bedrock nem escreve nada",
    )
    return ap


def _theme_args_error(args) -> str | None:
    """Combinações de argumentos do --theme-only (checadas antes de tocar o banco)."""
    theme_select = args.select in THEME_SELECTS
    if theme_select and not args.theme_only:
        return f"--select {args.select} exige --theme-only (grava só o tema)"
    if args.theme_only and not theme_select:
        return (
            f"--theme-only só vale com --select {' ou '.join(sorted(THEME_SELECTS))} "
            f"(não com {args.select})"
        )
    if args.campaign is not None and not args.theme_only:
        return "--campaign só vale com --theme-only"
    if args.theme_only:
        if args.campaign is None:
            return "--theme-only exige --campaign (ex.: tema26-llm-d1)"
        if not _CAMPAIGN_RE.match(args.campaign):
            return (
                f"--campaign inválida {args.campaign!r}: use [a-z0-9._-], começando por "
                "letra ou dígito, até 50 caracteres (ex.: tema26-llm-d1)"
            )
    if args.select == "theme-code" and not args.theme_code:
        return "--select theme-code exige --theme-code (ex.: 19)"
    if args.theme_code and args.select != "theme-code":
        return "--theme-code só vale com --select theme-code"
    if args.select != "theme26-candidates":
        for flag, value in (
            ("--term-fields", args.term_fields),
            ("--extra-codes", args.extra_codes),
        ):
            if value is not None:
                return f"{flag} só vale com --select theme26-candidates"
    return None
