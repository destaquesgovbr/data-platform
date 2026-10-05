-- 027_policy_ontology_seed_rollback.sql
-- Reverte a migração 027 apenas nas entidades do gazetteer de políticas.
-- AVISO: Remove entidades que foram inseridas pelo gazetteer (provenance = 'gazetteer')
-- AVISO: Não restaura valores de domain/lifecycle_phase que POLICYs pré-existentes
--        tinham antes da 027 (a 027 os sobrescreveu).

-- 1. Remover entidades inseridas diretamente pelo gazetteer
DELETE FROM entity_registry
WHERE provenance = 'gazetteer'
  AND type = 'POLICY';

-- 2. Limpar os campos de ontologia que a 027 gravou em POLICYs pré-existentes.
-- Restrito aos entity_ids do gazetteer: as demais POLICYs recebem domain e
-- lifecycle_phase do classificador do data-science e não podem ser tocadas.
UPDATE entity_registry
SET extra = extra - 'domain' - 'lifecycle_phase' - 'instance_of' - 'wikidata_id'
WHERE type = 'POLICY'
  AND entity_id IN (
    'dgb_pe-de-meia',
    'dgb_bolsa-familia',
    'dgb_novo-pac',
    'dgb_minha-casa-minha-vida',
    'dgb_farmacia-popular',
    'dgb_mais-medicos',
    'dgb_prouni',
    'dgb_sisu',
    'dgb_fies',
    'dgb_novo-ensino-medio',
    'dgb_taxa-selic',
    'dgb_arcabouco-fiscal',
    'dgb_reforma-tributaria',
    'dgb_marco-legal-garantias',
    'dgb_bpc',
    'dgb_auxilio-brasil',
    'dgb_pronasci',
    'dgb_estrategia-nacional-seguranca',
    'dgb_ppcdas',
    'dgb_fundo-amazonia',
    'dgb_plano-clima',
    'dgb_cop30-belem',
    'dgb_mapa-organizacoes',
    'dgb_reforma-administrativa',
    'dgb_portal-govbr',
    'dgb_egov-brasil',
    'dgb_cnpj-eletronico',
    'dgb_marco-legal-startups',
    'dgb_politica-ciberseguranca',
    'dgb_estrategia-ia',
    'dgb_brasil-participativo',
    'dgb_desenrola-brasil',
    'dgb_programa-acredita',
    'dgb_alimenta-brasil',
    'dgb_escola-tempo-integral',
    'dgb_banda-larga-escolas',
    'dgb_plano-nacional-educacao',
    'dgb_capes-mais-educacao',
    'dgb_emendas-pix',
    'dgb_programa-luz-para-todos',
    'dgb_brasil-sorridente',
    'dgb_rede-cegonha',
    'dgb_previne-brasil',
    'dgb_mercado-carbono',
    'dgb_programa-bio'
  );
