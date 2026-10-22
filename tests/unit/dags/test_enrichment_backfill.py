"""Testes da DAG enrichment_backfill (backfills de enriquecimento no Cloud Run Job).

Airflow + provider google nao estao instalados localmente e o modulo executa
dag_instance = enrichment_backfill() no import (apos try/except ImportError).
Os testes estruturais usam AST (mesmo padrao de test_ner_backfill) e os de
comportamento carregam o modulo com um Airflow falso (mesmo padrao de
test_compute_entity_trending), capturando os kwargs do @dag e do operador.

Contrato com o data-science (entrypoint do Job destaquesgovbr-ner-backfill):
  - env BACKFILL_SCRIPT escolhe o script; o DAG passa reenrich_combined_window.py;
  - env ENRICHMENT_MODEL_ID, BEDROCK_DAILY_TOKEN_QUOTA (JSON) e
    BACKFILL_QUOTA_FRACTION vao no container override "env";
  - os argumentos do reenrich vao no container override "args". Os args sao passados
    pela copia da CLI do DS-1 (_ds1_reenrich_cli.py, data-science#49) em
    TestContratoComACliDoDs1.
"""

import ast
import importlib.util
import json
import sys
import types
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.unit.dags import _ds1_reenrich_cli as ds1_cli

DAG_FILE = Path("src/data_platform/dags/enrichment_backfill.py")
HAIKU_45 = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
QUOTA_HAIKU_45 = '{"us.anthropic.claude-haiku-4-5-20251001-v1:0": 20000000}'


def _source() -> str:
    return DAG_FILE.read_text()


def _parse() -> ast.Module:
    return ast.parse(_source())


# --------------------------------------------------------------------------
# Airflow falso: captura os kwargs do @dag, as tasks e o operador
# --------------------------------------------------------------------------


class _FakeParam:
    def __init__(self, default=None, **schema):
        self.value = default
        self.schema = schema


class _FakeXComArg:
    def __init__(self, task_id: str):
        self.task_id = task_id


def _fake_airflow(captured: dict, variables: dict) -> dict[str, types.ModuleType]:
    def dag(**kwargs):
        captured["dag_kwargs"] = kwargs
        return lambda fn: fn

    def task(**task_kwargs):
        def decorator(fn):
            task_id = task_kwargs.get("task_id", fn.__name__)
            captured.setdefault("tasks", {})[task_id] = fn
            return lambda *a, **k: _FakeXComArg(task_id)

        return decorator

    class Variable:
        @staticmethod
        def get(key, default_var=None):
            captured.setdefault("variables_read", []).append(key)
            return variables.get(key, default_var)

    class CloudRunExecuteJobOperator:
        def __init__(self, **kwargs):
            captured.setdefault("operators", []).append(kwargs)

    airflow = types.ModuleType("airflow")
    decorators = types.ModuleType("airflow.decorators")
    decorators.dag = dag
    decorators.task = task
    models = types.ModuleType("airflow.models")
    models.Variable = Variable
    sdk = types.ModuleType("airflow.sdk")
    sdk.Param = _FakeParam
    cloud_run = types.ModuleType("airflow.providers.google.cloud.operators.cloud_run")
    cloud_run.CloudRunExecuteJobOperator = CloudRunExecuteJobOperator
    return {
        "airflow": airflow,
        "airflow.decorators": decorators,
        "airflow.models": models,
        "airflow.sdk": sdk,
        "airflow.providers": types.ModuleType("airflow.providers"),
        "airflow.providers.google": types.ModuleType("airflow.providers.google"),
        "airflow.providers.google.cloud": types.ModuleType("airflow.providers.google.cloud"),
        "airflow.providers.google.cloud.operators": types.ModuleType(
            "airflow.providers.google.cloud.operators"
        ),
        "airflow.providers.google.cloud.operators.cloud_run": cloud_run,
    }


def _load(monkeypatch, variables: dict | None = None) -> tuple[types.ModuleType, dict]:
    monkeypatch.setenv("GCP_PROJECT_ID", "projeto-teste")
    captured: dict = {}
    with patch.dict(sys.modules, _fake_airflow(captured, variables or {})):
        spec = importlib.util.spec_from_file_location("_dag_enrichment_backfill", DAG_FILE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, captured


def _default_params(captured: dict) -> dict:
    return {name: param.value for name, param in captured["dag_kwargs"]["params"].items()}


def _container(overrides: dict) -> dict:
    (container,) = overrides["container_overrides"]
    return container


def _env(overrides: dict) -> dict:
    return {item["name"]: item["value"] for item in _container(overrides)["env"]}


# --------------------------------------------------------------------------
# Estrutura (AST) — padrao dos demais DAGs que disparam Cloud Run Job
# --------------------------------------------------------------------------


class TestEstrutura:
    def test_parseia_sem_erro(self):
        assert _parse() is not None

    def test_airflow_protegido_por_try_except(self):
        tree = _parse()
        has_guard = any(
            isinstance(node, ast.Try)
            and any(
                isinstance(h.type, ast.Name) and h.type.id == "ImportError" for h in node.handlers
            )
            for node in tree.body
        )
        assert has_guard, "imports do airflow devem estar em try/except ImportError"

    def test_airflow_nao_importado_fora_do_try(self):
        for node in _parse().body:
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("airflow")
            elif isinstance(node, ast.Import):
                assert not any(alias.name.startswith("airflow") for alias in node.names)

    def test_nao_importa_data_platform(self):
        """O DAG e autocontido: nada de data_platform.* (plugins do Composer sao seletivos)."""
        modules = [
            node.module or "" for node in ast.walk(_parse()) if isinstance(node, ast.ImportFrom)
        ]
        modules += [
            alias.name
            for node in ast.walk(_parse())
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(m.startswith("data_platform") for m in modules), modules

    def test_dag_id_correto(self):
        assert 'dag_id="enrichment_backfill"' in _source()

    def test_usa_cloud_run_execute_job_operator(self):
        assert "CloudRunExecuteJobOperator(" in _source()

    def test_instancia_dag_no_modulo(self):
        assert "dag_instance = enrichment_backfill()" in _source()


# --------------------------------------------------------------------------
# Configuracao do DAG (carregado com Airflow falso)
# --------------------------------------------------------------------------


class TestConfiguracaoDoDag:
    def test_importa_e_registra_o_dag(self, monkeypatch):
        module, captured = _load(monkeypatch)
        assert captured["dag_kwargs"]["dag_id"] == "enrichment_backfill"
        assert hasattr(module, "dag_instance")

    def test_schedule_noturno_em_brt(self, monkeypatch):
        """22:30, 01:30 e 04:30 BRT (Composer em America/Sao_Paulo) = 01:30Z, 04:30Z, 07:30Z.

        Logo apos a virada do dia do ledger (00:00Z), fora do pico do worker ao vivo
        (07h-21h BRT) e sem coincidir com o canon (03/09/15/21Z) nem com o
        ner_backfill (05/11/17/23Z).
        """
        _, captured = _load(monkeypatch)
        assert captured["dag_kwargs"]["schedule"] == "30 1,4,22 * * *"

    def test_catchup_false_max_active_runs_1(self, monkeypatch):
        _, captured = _load(monkeypatch)
        assert captured["dag_kwargs"]["catchup"] is False
        assert captured["dag_kwargs"]["max_active_runs"] == 1

    def test_nao_nasce_pausado(self, monkeypatch):
        """O DAG assume o B5 sozinho apos o deploy (Composer cria DAGs pausados por padrao)."""
        _, captured = _load(monkeypatch)
        assert captured["dag_kwargs"]["is_paused_upon_creation"] is False

    def test_retry_unico_e_timeout_dentro_do_job(self, monkeypatch):
        _, captured = _load(monkeypatch)
        default_args = captured["dag_kwargs"]["default_args"]
        assert default_args["retries"] == 1
        assert default_args["execution_timeout"] == timedelta(minutes=130)

    def test_tags(self, monkeypatch):
        _, captured = _load(monkeypatch)
        assert {"silver", "enrichment", "backfill"} <= set(captured["dag_kwargs"]["tags"])

    def test_params_default_sao_a_campanha_b5(self, monkeypatch):
        _, captured = _load(monkeypatch)
        assert _default_params(captured) == {
            "select": "mock",
            "date_from": "2025-09-01",
            "date_to": "2026-03-01",
            "limit": 400,
            "workers": 2,
            "model_id": HAIKU_45,
            "daily_token_quota": {HAIKU_45: 20000000},
            "quota_fraction": 0.8,
            "dry_run": False,
            "theme_code": None,
            "campaign": "tema26-llm-d1",
            "term_fields": "title-content",
            "extra_codes": None,
        }

    def test_param_select_restrito_aos_modos_do_script(self, monkeypatch):
        _, captured = _load(monkeypatch)
        schema = captured["dag_kwargs"]["params"]["select"].schema
        assert schema["enum"] == [
            "mock",
            "null-theme",
            "null-summary",
            "theme-code",
            "theme26-candidates",
        ]

    def test_param_theme_code_opcional_com_formato_de_codigo(self, monkeypatch):
        _, captured = _load(monkeypatch)
        schema = captured["dag_kwargs"]["params"]["theme_code"].schema
        assert schema["type"] == ["null", "string"]
        assert schema["pattern"] == r"^\d{2}(\.\d{2}){0,2}$"

    def test_param_campaign_no_formato_do_ds1(self, monkeypatch):
        _, captured = _load(monkeypatch)
        schema = captured["dag_kwargs"]["params"]["campaign"].schema
        assert schema["type"] == "string"
        assert schema["pattern"] == r"^[a-z0-9][a-z0-9._-]{0,49}$"

    def test_param_term_fields_com_as_opcoes_do_ds1(self, monkeypatch):
        _, captured = _load(monkeypatch)
        schema = captured["dag_kwargs"]["params"]["term_fields"].schema
        assert schema["enum"] == ["title", "title-content"]

    def test_param_extra_codes_opcional(self, monkeypatch):
        _, captured = _load(monkeypatch)
        schema = captured["dag_kwargs"]["params"]["extra_codes"].schema
        assert schema["type"] == ["null", "string"]


# --------------------------------------------------------------------------
# Operador: mesmo Job, regiao e projeto do ner_backfill
# --------------------------------------------------------------------------


class TestOperador:
    def test_dispara_o_job_do_ner_backfill_por_default(self, monkeypatch):
        _, captured = _load(monkeypatch)
        (op,) = captured["operators"]
        assert op["task_id"] == "run_enrichment_backfill"
        assert op["job_name"] == "destaquesgovbr-ner-backfill"
        assert op["region"] == "southamerica-east1"
        assert op["project_id"] == "projeto-teste"

    def test_job_e_regiao_vem_das_mesmas_variables_do_ner_backfill(self, monkeypatch):
        _, captured = _load(
            monkeypatch,
            variables={"ner_job_name": "outro-job", "cloud_run_jobs_region": "us-east1"},
        )
        (op,) = captured["operators"]
        assert op["job_name"] == "outro-job"
        assert op["region"] == "us-east1"

    def test_overrides_vem_da_task_que_valida_os_params(self, monkeypatch):
        _, captured = _load(monkeypatch)
        (op,) = captured["operators"]
        assert isinstance(op["overrides"], _FakeXComArg)
        assert op["overrides"].task_id == "build_overrides"

    def test_task_build_overrides_usa_os_params_do_run(self, monkeypatch):
        module, captured = _load(monkeypatch)
        params = _default_params(captured) | {"limit": 10, "dry_run": True}
        overrides = captured["tasks"]["build_overrides"](params=params)
        assert overrides == module.build_overrides(params)
        assert "--dry-run" in _container(overrides)["args"]


# --------------------------------------------------------------------------
# build_overrides: o contrato com o entrypoint do data-science
# --------------------------------------------------------------------------


class TestContratoDosOverrides:
    def test_defaults_exatamente_como_o_contrato(self, monkeypatch):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(_default_params(captured))
        assert overrides == {
            "container_overrides": [
                {
                    "args": [
                        "--select",
                        "mock",
                        "--date-from",
                        "2025-09-01",
                        "--date-to",
                        "2026-03-01",
                        "--limit",
                        "400",
                        "--workers",
                        "2",
                    ],
                    "env": [
                        {"name": "BACKFILL_SCRIPT", "value": "reenrich_combined_window.py"},
                        {"name": "ENRICHMENT_MODEL_ID", "value": HAIKU_45},
                        {"name": "BEDROCK_DAILY_TOKEN_QUOTA", "value": QUOTA_HAIKU_45},
                        {"name": "BACKFILL_QUOTA_FRACTION", "value": "0.8"},
                    ],
                }
            ]
        }

    def test_sem_clear_args(self, monkeypatch):
        """clear_args e args sao mutuamente exclusivos na API v2 (ver ner_backfill)."""
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(_default_params(captured))
        assert "clear_args" not in _container(overrides)

    def test_params_sobrescrevem_args_e_env(self, monkeypatch):
        module, captured = _load(monkeypatch)
        params = _default_params(captured) | {
            "select": "null-summary",
            "date_from": "2026-06-01",
            "date_to": "2026-10-01",
            "limit": 50,
            "workers": 1,
            "model_id": "modelo-x",
            "daily_token_quota": {"modelo-x": 1000},
            "quota_fraction": 0.5,
        }
        overrides = module.build_overrides(params)
        assert _container(overrides)["args"] == [
            "--select",
            "null-summary",
            "--date-from",
            "2026-06-01",
            "--date-to",
            "2026-10-01",
            "--limit",
            "50",
            "--workers",
            "1",
        ]
        assert _env(overrides) == {
            "BACKFILL_SCRIPT": "reenrich_combined_window.py",
            "ENRICHMENT_MODEL_ID": "modelo-x",
            "BEDROCK_DAILY_TOKEN_QUOTA": '{"modelo-x": 1000}',
            "BACKFILL_QUOTA_FRACTION": "0.5",
        }

    def test_dry_run_acrescenta_flag(self, monkeypatch):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(_default_params(captured) | {"dry_run": True})
        assert _container(overrides)["args"][-1] == "--dry-run"

    @pytest.mark.parametrize("date_to", [None, ""])
    def test_mock_sem_date_to_omite_o_argumento(self, monkeypatch, date_to):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(_default_params(captured) | {"date_to": date_to})
        assert "--date-to" not in _container(overrides)["args"]

    def test_cota_como_string_json_e_aceita(self, monkeypatch):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(
            _default_params(captured) | {"daily_token_quota": QUOTA_HAIKU_45}
        )
        assert _env(overrides)["BEDROCK_DAILY_TOKEN_QUOTA"] == QUOTA_HAIKU_45

    def test_fracao_como_string_e_normalizada(self, monkeypatch):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(_default_params(captured) | {"quota_fraction": "0.8"})
        assert _env(overrides)["BACKFILL_QUOTA_FRACTION"] == "0.8"

    def test_cota_vai_como_json_valido(self, monkeypatch):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(_default_params(captured))
        assert json.loads(_env(overrides)["BEDROCK_DAILY_TOKEN_QUOTA"]) == {HAIKU_45: 20000000}


# --------------------------------------------------------------------------
# Validacao: falhar no Airflow antes de subir um Job mal configurado
# --------------------------------------------------------------------------


class TestValidacaoDosParams:
    @pytest.mark.parametrize(
        ("override", "trecho"),
        [
            ({"select": "tudo"}, "select"),
            ({"date_from": "01/09/2025"}, "date_from"),
            ({"date_to": "2026-13-01"}, "date_to"),
            ({"date_to": "2025-09-01"}, "date_to"),
            ({"limit": 0}, "limit"),
            ({"workers": 0}, "workers"),
            ({"model_id": ""}, "model_id"),
            ({"quota_fraction": 0}, "quota_fraction"),
            ({"quota_fraction": 1.5}, "quota_fraction"),
            ({"quota_fraction": "abc"}, "quota_fraction"),
            ({"daily_token_quota": "{nao e json"}, "daily_token_quota"),
            ({"daily_token_quota": ["lista"]}, "daily_token_quota"),
        ],
    )
    def test_params_invalidos_falham(self, monkeypatch, override, trecho):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match=trecho):
            module.build_overrides(_default_params(captured) | override)

    def test_modelo_sem_cota_falha_para_nao_rodar_sem_teto(self, monkeypatch):
        """Sem a chave do modelo na cota o governador entra em modo sem-teto."""
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="sem-teto"):
            module.build_overrides(_default_params(captured) | {"model_id": "outro-modelo"})

    @pytest.mark.parametrize("cota", [0, -1, "20M", True])
    def test_cota_do_modelo_precisa_ser_inteiro_positivo(self, monkeypatch, cota):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="daily_token_quota"):
            module.build_overrides(
                _default_params(captured) | {"daily_token_quota": {HAIKU_45: cota}}
            )

    @pytest.mark.parametrize("select", ["null-theme", "null-summary"])
    def test_selects_do_worker_ao_vivo_exigem_date_to(self, monkeypatch, select):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="date_to"):
            module.build_overrides(_default_params(captured) | {"select": select, "date_to": ""})


# --------------------------------------------------------------------------
# Tema 26 (D1): reclassificação por código de tema e candidatos por regra
# --------------------------------------------------------------------------


class TestSelecoesDoTema26:
    """Contrato com o reenrich_combined_window.py do DS-1 (data-science#49).

    - `--select theme-code --theme-code <c>`: artigos com tema no código <c> (L1, L2 ou L3);
    - `--select theme26-candidates`: L1 19, mais os de 04/05.02.01/15.02.03 (--extra-codes)
      do MDR ou com "defesa civil", "calamidade", "situação de emergência", "estado de
      emergência" ou "desastre" no título (--term-fields title) ou no título e no conteúdo
      (title-content, o escopo decidido em 22/10: 1.586 candidatos).
    As duas exigem `--theme-only` e `--campaign <id>` (auditoria em news_theme_changes).
    Nenhuma disputa artigo com o worker ao vivo (só pegam artigo já com tema), então
    date_to é opcional; o date_to herdado da campanha B5 (2026-03-01) é recusado.
    """

    def _params(self, captured, **override) -> dict:
        return _default_params(captured) | {"date_from": "2018-01-01", "date_to": None} | override

    def _args(self, module, captured, **override) -> list[str]:
        return _container(module.build_overrides(self._params(captured, **override)))["args"]

    def test_theme_code_com_theme_only_e_campanha(self, monkeypatch):
        module, captured = _load(monkeypatch)
        assert self._args(module, captured, select="theme-code", theme_code="19") == [
            "--select",
            "theme-code",
            "--theme-code",
            "19",
            "--theme-only",
            "--campaign",
            "tema26-llm-d1",
            "--date-from",
            "2018-01-01",
            "--limit",
            "400",
            "--workers",
            "2",
        ]

    def test_candidatos_do_tema_26_com_titulo_e_conteudo_por_padrao(self, monkeypatch):
        module, captured = _load(monkeypatch)
        assert self._args(module, captured, select="theme26-candidates") == [
            "--select",
            "theme26-candidates",
            "--theme-only",
            "--campaign",
            "tema26-llm-d1",
            "--term-fields",
            "title-content",
            "--date-from",
            "2018-01-01",
            "--limit",
            "400",
            "--workers",
            "2",
        ]

    def test_candidatos_so_no_titulo(self, monkeypatch):
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select="theme26-candidates", term_fields="title")
        assert args[args.index("--term-fields") + 1] == "title"

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("04,05.02.01", "04,05.02.01"),
            (" 04 , 15.02.03 ", "04,15.02.03"),
            ("05.02.01", "05.02.01"),
        ],
    )
    def test_extra_codes_vai_normalizado(self, monkeypatch, valor, esperado):
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select="theme26-candidates", extra_codes=valor)
        assert args[args.index("--extra-codes") + 1] == esperado

    @pytest.mark.parametrize("valor", [None, "", "  "])
    def test_extra_codes_vazio_omite_o_argumento(self, monkeypatch, valor):
        """Sem --extra-codes o DS-1 usa o padrão dele (04, 05.02.01, 15.02.03)."""
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select="theme26-candidates", extra_codes=valor)
        assert "--extra-codes" not in args

    @pytest.mark.parametrize("valor", ["4", "04,", "04;05", "05.2.01", "abc"])
    def test_extra_codes_invalido_falha(self, monkeypatch, valor):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="extra_codes"):
            self._args(module, captured, select="theme26-candidates", extra_codes=valor)

    @pytest.mark.parametrize("select", ["mock", "theme-code"])
    def test_extra_codes_so_vale_com_theme26_candidates(self, monkeypatch, select):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="extra_codes"):
            self._args(
                module,
                captured,
                select=select,
                theme_code="19" if select == "theme-code" else None,
                extra_codes="04",
            )

    def test_term_fields_invalido_falha(self, monkeypatch):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="term_fields"):
            self._args(module, captured, select="theme26-candidates", term_fields="content")

    def test_term_fields_fica_fora_do_theme_code(self, monkeypatch):
        """O DS-1 recusa --term-fields fora do theme26-candidates."""
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select="theme-code", theme_code="19")
        assert "--term-fields" not in args

    def test_campanha_explicita(self, monkeypatch):
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select="theme26-candidates", campaign="tema26-llm-d1b")
        assert args[args.index("--campaign") + 1] == "tema26-llm-d1b"

    @pytest.mark.parametrize("campanha", ["", "Tema26", "-tema26", "tema 26", "a" * 51, None])
    def test_campanha_fora_do_formato_falha(self, monkeypatch, campanha):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="campaign"):
            self._args(module, captured, select="theme-code", theme_code="19", campaign=campanha)

    @pytest.mark.parametrize("campanha", ["tema26-034", "tema26-rollback"])
    def test_campanhas_da_migracao_034_sao_reservadas(self, monkeypatch, campanha):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="campaign"):
            self._args(module, captured, select="theme26-candidates", campaign=campanha)

    def test_candidatos_do_tema_26_exigem_campanha_tema26(self, monkeypatch):
        """O rollback da 034 e o MERGE do BigQuery só leem campanhas tema26-*."""
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="tema26-"):
            self._args(module, captured, select="theme26-candidates", campaign="d1-llm")

    @pytest.mark.parametrize("select", ["mock", "null-theme", "null-summary"])
    def test_selecoes_antigas_sem_theme_only_nem_campanha(self, monkeypatch, select):
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select=select, date_to="2026-10-21")
        for flag in ("--theme-only", "--campaign", "--term-fields", "--extra-codes"):
            assert flag not in args

    @pytest.mark.parametrize("codigo", ["19", "05.02", "05.02.01", " 15.02.03 "])
    def test_theme_code_aceita_l1_l2_e_l3(self, monkeypatch, codigo):
        module, captured = _load(monkeypatch)
        args = self._args(module, captured, select="theme-code", theme_code=codigo)
        assert args[args.index("--theme-code") + 1] == codigo.strip()

    @pytest.mark.parametrize("codigo", [None, "", "  "])
    def test_theme_code_obrigatorio_com_select_theme_code(self, monkeypatch, codigo):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="theme_code"):
            self._args(module, captured, select="theme-code", theme_code=codigo)

    @pytest.mark.parametrize("codigo", ["9", "19.3", "abc", "19.03.01.01", "19-03", 19])
    def test_theme_code_com_formato_invalido_falha(self, monkeypatch, codigo):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="theme_code"):
            self._args(module, captured, select="theme-code", theme_code=codigo)

    @pytest.mark.parametrize("select", ["mock", "null-theme", "null-summary", "theme26-candidates"])
    def test_theme_code_so_vale_com_select_theme_code(self, monkeypatch, select):
        module, captured = _load(monkeypatch)
        with pytest.raises(ValueError, match="theme_code"):
            self._args(module, captured, select=select, theme_code="19", date_to="2026-10-21")

    def test_candidatos_do_tema_26_com_date_to_e_dry_run(self, monkeypatch):
        module, captured = _load(monkeypatch)
        args = self._args(
            module, captured, select="theme26-candidates", date_to="2026-11-11", dry_run=True
        )
        assert args[args.index("--date-to") + 1] == "2026-11-11"
        assert args[-1] == "--dry-run"

    @pytest.mark.parametrize("select", ["theme-code", "theme26-candidates"])
    def test_date_to_herdado_da_campanha_b5_e_recusado(self, monkeypatch, select):
        """Sem limpar o date_to, o default do B5 (2026-03-01) cortaria ~70% do L1 19
        (341 de 484 artigos são de mar/2026 em diante)."""
        module, captured = _load(monkeypatch)
        params = _default_params(captured) | {"select": select, "date_from": "2018-01-01"}
        if select == "theme-code":
            params["theme_code"] = "19"
        assert params["date_to"] == "2026-03-01"
        with pytest.raises(ValueError, match="date_to.*B5"):
            module.build_overrides(params)

    def test_mock_segue_aceitando_o_date_to_do_b5(self, monkeypatch):
        module, captured = _load(monkeypatch)
        args = _container(module.build_overrides(_default_params(captured)))["args"]
        assert args[args.index("--date-to") + 1] == "2026-03-01"

    def test_env_do_job_nao_muda(self, monkeypatch):
        module, captured = _load(monkeypatch)
        overrides = module.build_overrides(
            self._params(captured, select="theme-code", theme_code="19")
        )
        assert _env(overrides)["BACKFILL_SCRIPT"] == "reenrich_combined_window.py"


# --------------------------------------------------------------------------
# Contrato: os args do DAG passam pela CLI do DS-1 (cópia em _ds1_reenrich_cli.py)
# --------------------------------------------------------------------------


class TestContratoComACliDoDs1:
    """Os args montados pelo DAG são aceitos pelo argparse e pela validação do DS-1."""

    CASOS = [
        {"select": "mock"},
        {"select": "mock", "date_to": None, "dry_run": True},
        {"select": "null-theme", "date_from": "2026-11-10", "date_to": "2026-11-12"},
        {"select": "null-summary", "date_from": "2026-06-01", "date_to": "2026-10-21"},
        {"select": "theme-code", "theme_code": "19", "date_from": "2018-01-01", "date_to": None},
        {
            "select": "theme-code",
            "theme_code": "05.02.01",
            "date_from": "2018-01-01",
            "date_to": "2026-11-11",
            "campaign": "tema26-llm-d1b",
            "dry_run": True,
        },
        {"select": "theme26-candidates", "date_from": "2018-01-01", "date_to": None},
        {
            "select": "theme26-candidates",
            "date_from": "2018-01-01",
            "date_to": None,
            "term_fields": "title",
            "extra_codes": "04,05.02.01",
            "limit": 10,
            "dry_run": True,
        },
    ]

    def _parse(self, module, captured, override):
        args = _container(module.build_overrides(_default_params(captured) | override))["args"]
        parsed = ds1_cli.build_arg_parser().parse_args(args)
        return args, parsed

    @pytest.mark.parametrize("override", CASOS)
    def test_argparse_e_validacao_do_ds1_aceitam(self, monkeypatch, override):
        module, captured = _load(monkeypatch)
        _args, parsed = self._parse(module, captured, override)
        assert ds1_cli._theme_args_error(parsed) is None

    def test_candidatos_chegam_ao_ds1_com_o_escopo_de_22_10(self, monkeypatch):
        module, captured = _load(monkeypatch)
        _args, parsed = self._parse(
            module,
            captured,
            {"select": "theme26-candidates", "date_from": "2018-01-01", "date_to": None},
        )
        assert parsed.select == "theme26-candidates"
        assert parsed.theme_only is True
        assert parsed.campaign == "tema26-llm-d1"
        assert parsed.term_fields == "title-content"
        assert parsed.extra_codes is None  # padrão do DS-1: 04, 05.02.01, 15.02.03
        assert parsed.date_from == "2018-01-01"
        assert parsed.date_to is None

    def test_extra_codes_chegam_como_tupla(self, monkeypatch):
        module, captured = _load(monkeypatch)
        _args, parsed = self._parse(
            module,
            captured,
            {
                "select": "theme26-candidates",
                "date_from": "2018-01-01",
                "date_to": None,
                "extra_codes": "04,15.02.03",
            },
        )
        assert parsed.extra_codes == ("04", "15.02.03")

    def test_theme_code_chega_ao_ds1(self, monkeypatch):
        module, captured = _load(monkeypatch)
        _args, parsed = self._parse(
            module,
            captured,
            {
                "select": "theme-code",
                "theme_code": "19",
                "date_from": "2018-01-01",
                "date_to": None,
            },
        )
        assert (parsed.select, parsed.theme_code, parsed.theme_only) == ("theme-code", "19", True)
        assert parsed.campaign == "tema26-llm-d1"
        assert parsed.term_fields is None

    def test_a_copia_recusa_o_contrato_antigo(self):
        """Sanidade da cópia: sem --theme-only o DS-1 sai com erro (era o que o DAG mandava)."""
        parsed = ds1_cli.build_arg_parser().parse_args(
            ["--select", "theme26-candidates", "--date-from", "2025-09-01"]
        )
        assert "exige --theme-only" in ds1_cli._theme_args_error(parsed)
