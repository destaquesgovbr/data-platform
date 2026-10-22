"""test-data/themes_tree_enriched_full.yaml segue o contrato do tema 26 (DP-2/TH-1).

O arquivo é cópia byte a byte do themes_tree_enriched_full.yaml do repo themes, que é a
fonte da tabela `themes` (588 códigos em 21/10/2026, idênticos ao YAML). O dono do
conteúdo é o repo themes; aqui só se copia (o sha256 fica fixado em
SHA256_THEMES_FULL para o drift não voltar). Contrato:

  - L1 '26' "Defesa Civil e Gestão de Desastres";
  - L2 '26.01' "Defesa Civil", com L3 26.01.01–05 = os L3 de 19.03.01–05 (mesmos rótulos);
  - L2 '26.02' "Situações de Emergência", com L3 26.02.01–05 = os L3 de 19.04.01–05;
  - 19.03* e 19.04* saem; o 19 fica com 19.01, 19.02 e 19.05;
  - códigos L1/L2 entre aspas.

A migração 034 grava esses mesmos códigos e rótulos no banco
(tests/unit/test_migration_034_tema26.py confere os dois lados).
"""

import hashlib
import re
from pathlib import Path

import yaml

YAML_PATH = Path(__file__).resolve().parents[2] / "test-data" / "themes_tree_enriched_full.yaml"

# sha256 do themes_tree_enriched_full.yaml da versão 3.2 no repo themes
# (destaquesgovbr/themes#4, branch feature/tema-26-defesa-civil: commit 7b7c002, o último
# que toca o arquivo; idêntico no head 683bfed, conferido em 22/10).
# Para atualizar: copie o arquivo do repo themes para test-data/ (cp, sem reformatar)
# e troque este hash pelo `shasum -a 256` do arquivo copiado.
SHA256_THEMES_FULL = "32a2fa43149ecd6bb1e8f5b26a341b3ee1b539750eb0c5d35120b2e2a32c92b0"

CONTRATO_26 = {
    "26": ("Defesa Civil e Gestão de Desastres", 1, None),
    "26.01": ("Defesa Civil", 2, "26"),
    "26.01.01": ("Preparação para Desastres", 3, "26.01"),
    "26.01.02": ("Planejamento de Evacuação", 3, "26.01"),
    "26.01.03": ("Resposta a Desastres", 3, "26.01"),
    "26.01.04": ("Monitoramento de Riscos Naturais", 3, "26.01"),
    "26.01.05": ("Gestão de Abrigos", 3, "26.01"),
    "26.02": ("Situações de Emergência", 2, "26"),
    "26.02.01": ("Resgate e Salvamento", 3, "26.02"),
    "26.02.02": ("Logística de Emergência", 3, "26.02"),
    "26.02.03": ("Ações Humanitárias", 3, "26.02"),
    "26.02.04": ("Reconstrução Pós-Desastre", 3, "26.02"),
    "26.02.05": ("Assistência a Deslocados Internos", 3, "26.02"),
}


def _load() -> dict:
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8"))


def _flatten(themes: list[dict], level: int = 1, parent: str | None = None) -> list[dict]:
    flat = []
    for theme in themes:
        flat.append({**theme, "level": level, "parent_code": parent})
        flat.extend(_flatten(theme.get("children") or [], level + 1, theme["code"]))
    return flat


def _by_code() -> dict[str, dict]:
    return {t["code"]: t for t in _flatten(_load()["themes"])}


def test_test_data_e_copia_byte_a_byte_do_repo_themes():
    """Duas versões 3.2 diferentes da taxonomia na D0 seriam drift; o repo themes manda."""
    digest = hashlib.sha256(YAML_PATH.read_bytes()).hexdigest()
    assert digest == SHA256_THEMES_FULL, (
        "test-data/themes_tree_enriched_full.yaml não é cópia byte a byte do "
        "themes_tree_enriched_full.yaml do repo themes; copie o arquivo de lá "
        "(ou, se o themes mudou, atualize SHA256_THEMES_FULL)"
    )


def test_todos_os_codigos_sao_strings():
    assert all(isinstance(code, str) for code in _by_code())


def test_tema_26_segue_o_contrato():
    themes = _by_code()
    got = {
        code: (t["label"], t["level"], t["parent_code"])
        for code, t in themes.items()
        if code.startswith("26")
    }
    assert got == CONTRATO_26


def test_19_03_e_19_04_saem_da_arvore():
    assert [c for c in _by_code() if re.match(r"^19\.0[34]", c)] == []


def test_19_fica_com_19_01_19_02_e_19_05():
    themes = _by_code()
    filhos = sorted(c for c, t in themes.items() if t["parent_code"] == "19")
    assert filhos == ["19.01", "19.02", "19.05"]
    assert themes["19"]["label"] == "Defesa e Forças Armadas"


def test_contagens_por_nivel():
    """588 de hoje (23/106/459) − 12 (19.03*, 19.04*) + 13 (26*) = 589 (24/106/459)."""
    niveis = [t["level"] for t in _by_code().values()]
    assert (niveis.count(1), niveis.count(2), niveis.count(3)) == (24, 106, 459)


def test_l1_26_vem_depois_do_25():
    assert [t["code"] for t in _load()["themes"]][-2:] == ["25", "26"]


def test_l1_26_tem_os_campos_dos_demais_l1():
    l1 = {t["code"]: t for t in _load()["themes"]}
    assert set(l1["26"]) >= {"description", "keywords", "includes", "excludes", "children"}
    assert all(l1["26"][campo] for campo in ("description", "keywords", "includes", "excludes"))


def test_l2_e_l3_do_26_mantem_descricoes_e_palavras_chave():
    for code, t in _by_code().items():
        if code.startswith("26."):
            assert t.get("description"), code
            assert t.get("keywords"), code


def test_excludes_do_19_apontam_para_o_26():
    l1 = {t["code"]: t for t in _load()["themes"]}
    assert any("Defesa Civil e Gestão de Desastres" in e for e in l1["19"]["excludes"])


def test_codigos_l1_e_l2_entre_aspas():
    """Sem aspas, o YAML 1.1 lê '08.01' como float; o contrato pede aspas em L1/L2."""
    sem_aspas = [
        linha.strip()
        for linha in YAML_PATH.read_text(encoding="utf-8").splitlines()
        if re.match(r"^\s*- code: \d{2}(\.\d{2})?\s*$", linha)
    ]
    assert sem_aspas == []


def test_cabecalho_na_versao_3_2():
    cabecalho = YAML_PATH.read_text(encoding="utf-8").split("\nthemes:", 1)[0]
    assert "Versão: 3.2" in cabecalho
    assert "24 temas L1" in cabecalho
