"""CLI do reenrich_combined_window.py (DS-1) no contrato do DAG enrichment_backfill (22/10).

Contrato final (plano, 22/10): as flags que o DAG passa e que o DS-1 (data-science#49) aceita
são exatamente

  --select {mock,null-theme,null-summary}  --date-from D [--date-to D]
  --select theme-code --theme-code <NN|NN.NN|NN.NN.NN>  --date-from D [--date-to D]
  --select theme26-candidates  --date-from D [--date-to D]

mais --limit N, --workers N e [--dry-run]. As seleções de tema gravam só o tema e auditam na
campanha tema26-llm-d1 (source llm:<model_id>), com os termos no título e no conteúdo e a
guarda dos extras; nada disso é flag. Este parser reproduz esse contrato (argparse recusa
qualquer outra flag, como --theme-only, --campaign, --term-fields e --extra-codes) para o
teste TestContratoComACliDoDs1 (test_enrichment_backfill.py) passar por ele os args que o
DAG monta, como o Job faria. Se o contrato mudar, mudar aqui, no DAG e no DS-1 juntos.
"""

import argparse
import datetime
import re

SELECT_CHOICES = ("null-theme", "mock", "null-summary", "theme-code", "theme26-candidates")
SELECTS_REQUIRING_DATE_TO = frozenset({"null-theme", "null-summary"})
_CODE_RE = re.compile(r"^\d{2}(?:\.\d{2}){0,2}$")


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


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"esperado inteiro positivo, recebido {value!r}")
    return number


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="reenrich_combined_window.py", allow_abbrev=False)
    ap.add_argument("--select", choices=SELECT_CHOICES, required=True)
    ap.add_argument("--theme-code", type=_theme_code_arg, default=None)
    ap.add_argument("--date-from", type=_iso_date, required=True)
    ap.add_argument("--date-to", type=_iso_date, default=None)
    ap.add_argument("--limit", type=_positive_int, required=True)
    ap.add_argument("--workers", type=_positive_int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    return ap


def contract_error(args) -> str | None:
    """Combinações do contrato (checadas antes de tocar o banco)."""
    if args.select == "theme-code" and not args.theme_code:
        return "--select theme-code exige --theme-code (ex.: 19)"
    if args.theme_code and args.select != "theme-code":
        return "--theme-code só vale com --select theme-code"
    if args.select in SELECTS_REQUIRING_DATE_TO and args.date_to is None:
        return f"--select {args.select} exige --date-to"
    return None
