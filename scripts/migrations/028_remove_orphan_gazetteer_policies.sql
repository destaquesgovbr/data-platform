-- 028_remove_orphan_gazetteer_policies.sql
-- Remove as POLICYs que a 027 inseriu a partir do gazetteer e que ficaram órfãs.
-- A 027 não checava o registry: das 36 políticas que ela inseriu em prod, muitas
-- duplicam entidades canônicas já existentes (ex.: Bolsa Família = Q575545,
-- Programa Mais Médicos) e nenhuma tem menções, aliases ou arestas.
-- Os campos de ontologia que a 027 gravou em POLICYs pré-existentes são mantidos.
--
-- Só remove linhas sem nenhuma referência: é idempotente e preserva uma entidade
-- do gazetteer que tenha passado a ser usada.
--
-- Sem rollback: as linhas removidas não tinham dados associados. Para recriá-las,
-- reexecute o passo 4 de 027_policy_ontology_seed.sql.

DELETE FROM entity_registry er
WHERE er.provenance = 'gazetteer'
  AND er.type = 'POLICY'
  AND NOT EXISTS (SELECT 1 FROM news_entities ne WHERE ne.entity_id = er.entity_id)
  AND NOT EXISTS (SELECT 1 FROM entity_alias ea WHERE ea.entity_id = er.entity_id)
  AND NOT EXISTS (
      SELECT 1 FROM entity_edges ee
      WHERE ee.src_id = er.entity_id OR ee.dst_id = er.entity_id
  )
  AND NOT EXISTS (SELECT 1 FROM entity_registry_seen rs WHERE rs.entity_id = er.entity_id)
  AND NOT EXISTS (SELECT 1 FROM entity_trending_scores ts WHERE ts.entity_id = er.entity_id);
