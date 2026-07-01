-- 026_policy_ontology_seed.sql
-- Popula campos de ontologia (domain, lifecycle_phase) para entidades POLICY existentes
-- via JOIN com o gazetteer de políticas
-- Aplicar após confirmar que entity_registry tem entidades POLICY (verificar com SELECT COUNT(*) WHERE type='POLICY')

-- 1. Criar tabela temporária a partir do gazetteer
CREATE TEMP TABLE policy_gazetteer_temp (
    entity_id VARCHAR(64),
    canonical_name TEXT,
    domain VARCHAR(32),
    lifecycle_phase VARCHAR(32),
    wikidata_id VARCHAR(32),
    instance_of VARCHAR(32)
);

-- 2. Inserir dados do gazetteer (self-contained, espelhando policy_gazetteer.csv)
INSERT INTO policy_gazetteer_temp VALUES
    ('dgb_pe-de-meia',               'Pé-de-Meia',                         'SOCIAL',       'ROUTINE',         NULL,       'Q327254'),
    ('dgb_bolsa-familia',            'Bolsa Família',                       'SOCIAL',       'ROUTINE',         'Q327254',  'Q327254'),
    ('dgb_novo-pac',                 'Novo PAC',                            'ECONOMIC',     'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_minha-casa-minha-vida',    'Minha Casa Minha Vida',               'SOCIAL',       'IMPLEMENTATION',  'Q2376464', 'Q2376464'),
    ('dgb_farmacia-popular',         'Farmácia Popular',                    'HEALTH',       'ROUTINE',         NULL,       NULL),
    ('dgb_mais-medicos',             'Mais Médicos',                        'HEALTH',       'ROUTINE',         NULL,       NULL),
    ('dgb_prouni',                   'ProUni',                              'EDUCATION',    'ROUTINE',         NULL,       NULL),
    ('dgb_sisu',                     'SISU',                                'EDUCATION',    'ROUTINE',         NULL,       NULL),
    ('dgb_fies',                     'FIES',                                'EDUCATION',    'ROUTINE',         NULL,       NULL),
    ('dgb_novo-ensino-medio',        'Novo Ensino Médio',                   'EDUCATION',    'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_taxa-selic',               'Taxa Selic',                          'ECONOMIC',     'ROUTINE',         NULL,       NULL),
    ('dgb_arcabouco-fiscal',         'Arcabouço Fiscal',                    'ECONOMIC',     'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_reforma-tributaria',       'Reforma Tributária',                  'ECONOMIC',     'REGULATION',      NULL,       NULL),
    ('dgb_marco-legal-garantias',    'Marco Legal das Garantias',           'ECONOMIC',     'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_bpc',                      'BPC',                                 'SOCIAL',       'ROUTINE',         NULL,       NULL),
    ('dgb_auxilio-brasil',           'Auxílio Brasil',                      'SOCIAL',       'ROUTINE',         NULL,       NULL),
    ('dgb_pronasci',                 'PRONASCI',                            'SECURITY',     'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_estrategia-nacional-seguranca', 'Estratégia Nacional de Segurança Pública', 'SECURITY', 'REGULATION', NULL,    NULL),
    ('dgb_ppcdas',                   'PPCDAm',                              'ENVIRONMENT',  'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_fundo-amazonia',           'Fundo Amazônia',                      'ENVIRONMENT',  'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_plano-clima',              'Plano Clima',                         'ENVIRONMENT',  'REGULATION',      NULL,       NULL),
    ('dgb_cop30-belem',              'COP30 Belém',                         'ENVIRONMENT',  'ANNOUNCED',       NULL,       NULL),
    ('dgb_mapa-organizacoes',        'Mapa das Organizações',               'GOVERNANCE',   'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_reforma-administrativa',   'Reforma Administrativa',              'GOVERNANCE',   'REGULATION',      NULL,       NULL),
    ('dgb_portal-govbr',             'Portal Gov.BR',                       'GOVERNANCE',   'ROUTINE',         NULL,       NULL),
    ('dgb_egov-brasil',              'e-gov Brasil',                        'GOVERNANCE',   'ROUTINE',         NULL,       NULL),
    ('dgb_cnpj-eletronico',          'CNPJ Eletrônico',                     'GOVERNANCE',   'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_marco-legal-startups',     'Marco Legal das Startups',            'ECONOMIC',     'ROUTINE',         NULL,       NULL),
    ('dgb_politica-ciberseguranca',  'Política Nacional de Cibersegurança', 'SECURITY',     'REGULATION',      NULL,       NULL),
    ('dgb_estrategia-ia',            'Estratégia Nacional de IA',           'EDUCATION',    'REGULATION',      NULL,       NULL),
    ('dgb_brasil-participativo',     'Brasil Participativo',                'GOVERNANCE',   'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_desenrola-brasil',         'Desenrola Brasil',                    'ECONOMIC',     'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_programa-acredita',        'Programa Acredita',                   'ECONOMIC',     'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_alimenta-brasil',          'Programa Alimenta Brasil',            'SOCIAL',       'ROUTINE',         NULL,       NULL),
    ('dgb_escola-tempo-integral',    'Programa Escola em Tempo Integral',   'EDUCATION',    'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_banda-larga-escolas',      'Banda Larga nas Escolas',             'EDUCATION',    'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_plano-nacional-educacao',  'Plano Nacional de Educação',          'EDUCATION',    'REGULATION',      NULL,       NULL),
    ('dgb_capes-mais-educacao',      'CAPES Mais Educação',                 'EDUCATION',    'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_emendas-pix',              'Emendas Pix',                         'GOVERNANCE',   'ROUTINE',         NULL,       NULL),
    ('dgb_programa-luz-para-todos',  'Luz para Todos',                      'SOCIAL',       'ROUTINE',         NULL,       NULL),
    ('dgb_brasil-sorridente',        'Brasil Sorridente',                   'HEALTH',       'ROUTINE',         NULL,       NULL),
    ('dgb_rede-cegonha',             'Rede Cegonha',                        'HEALTH',       'ROUTINE',         NULL,       NULL),
    ('dgb_previne-brasil',           'Previne Brasil',                      'HEALTH',       'IMPLEMENTATION',  NULL,       NULL),
    ('dgb_mercado-carbono',          'Mercado Brasileiro de Carbono',       'ENVIRONMENT',  'REGULATION',      NULL,       NULL),
    ('dgb_programa-bio',             'Programa BIO',                        'ENVIRONMENT',  'IMPLEMENTATION',  NULL,       NULL);

-- 3. Atualizar entity_registry: mesclar campos de ontologia no JSONB extra
-- Apenas para entidades que JÁ EXISTEM no registry e são do tipo POLICY
UPDATE entity_registry er
SET
    extra = er.extra || jsonb_build_object(
        'domain',          g.domain,
        'lifecycle_phase', g.lifecycle_phase,
        'wikidata_id',     g.wikidata_id,
        'instance_of',     g.instance_of
    ),
    updated_at = NOW()
FROM policy_gazetteer_temp g
WHERE er.entity_id = g.entity_id
  AND er.type = 'POLICY';

-- 4. Inserir entidades do gazetteer que NÃO existem no registry
INSERT INTO entity_registry (entity_id, canonical_name, type, aliases, wikidata_id, confidence, provenance, extra)
SELECT
    g.entity_id,
    g.canonical_name,
    'POLICY',
    '[]'::jsonb,
    g.wikidata_id,
    0.9,
    'gazetteer',
    jsonb_build_object(
        'domain',          g.domain,
        'lifecycle_phase', g.lifecycle_phase,
        'instance_of',     g.instance_of
    )
FROM policy_gazetteer_temp g
WHERE NOT EXISTS (
    SELECT 1 FROM entity_registry er WHERE er.entity_id = g.entity_id
);

-- 5. Cleanup
DROP TABLE policy_gazetteer_temp;
