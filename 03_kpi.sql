-- =====================================================================
-- Étape 3 – Vues SQL de pilotage (alimentent le dashboard Power BI)
-- Base : sephora.db  |  Tables sources : avis_propres, produits_propres
-- =====================================================================

-- KPI mensuels (suivi de tendance)
DROP VIEW IF EXISTS v_kpi_mensuel;
CREATE VIEW v_kpi_mensuel AS
SELECT mois,
       COUNT(*)                                    AS nb_avis,
       ROUND(AVG(rating), 3)                       AS note_moyenne,
       ROUND(100.0 * AVG(avis_negatif), 2)         AS pct_avis_negatifs,
       ROUND(100.0 * AVG(avis_positif), 2)         AS pct_avis_positifs,
       ROUND(100.0 * AVG(avis_positif) - 100.0 * AVG(avis_negatif), 2) AS score_net_satisfaction,
       ROUND(100.0 * AVG(is_recommended), 2)       AS taux_recommandation   -- AVG ignore les valeurs manquantes
FROM avis_propres
GROUP BY mois;

-- KPI par marque et par année, avec l'évolution sur un an (N vs N-1)
DROP VIEW IF EXISTS v_kpi_marque_annee;
CREATE VIEW v_kpi_marque_annee AS
WITH base AS (
  SELECT brand_name, annee, MAX(maison_luxe) AS maison_luxe,
         COUNT(*) AS nb_avis,
         ROUND(AVG(rating), 3) AS note_moyenne,
         ROUND(100.0 * AVG(avis_negatif), 2) AS pct_avis_negatifs,
         ROUND(100.0 * AVG(is_recommended), 2) AS taux_recommandation
  FROM avis_propres
  GROUP BY brand_name, annee
)
SELECT *,
       ROUND(pct_avis_negatifs - LAG(pct_avis_negatifs) OVER (PARTITION BY brand_name ORDER BY annee), 2)
         AS evol_pct_negatifs_vs_n1
FROM base;

-- KPI par catégorie et segment de prix
DROP VIEW IF EXISTS v_kpi_categorie_segment;
CREATE VIEW v_kpi_categorie_segment AS
SELECT categorie_analyse, segment_prix,
       COUNT(*) AS nb_avis,
       ROUND(AVG(rating), 3) AS note_moyenne,
       ROUND(100.0 * AVG(avis_negatif), 2) AS pct_avis_negatifs,
       ROUND(100.0 * AVG(is_recommended), 2) AS taux_recommandation
FROM avis_propres
WHERE categorie_analyse IS NOT NULL
GROUP BY categorie_analyse, segment_prix;

-- Maisons de luxe vs reste du marché, par année
DROP VIEW IF EXISTS v_luxe_vs_marche;
CREATE VIEW v_luxe_vs_marche AS
SELECT annee,
       CASE WHEN maison_luxe = 1 THEN 'Maisons de luxe' ELSE 'Reste du marché' END AS univers,
       COUNT(*) AS nb_avis,
       ROUND(AVG(rating), 3) AS note_moyenne,
       ROUND(100.0 * AVG(avis_negatif), 2) AS pct_avis_negatifs,
       ROUND(100.0 * AVG(is_recommended), 2) AS taux_recommandation
FROM avis_propres
GROUP BY annee, univers;

-- Effet des caractéristiques commerciales (exclusivité, nouveauté, édition limitée)
DROP VIEW IF EXISTS v_kpi_attributs;
CREATE VIEW v_kpi_attributs AS
SELECT 'Exclusivité Sephora' AS attribut, sephora_exclusive AS valeur, COUNT(*) AS nb_avis,
       ROUND(100.0 * AVG(avis_negatif), 2) AS pct_avis_negatifs, ROUND(AVG(rating), 3) AS note_moyenne
FROM avis_propres WHERE sephora_exclusive IS NOT NULL GROUP BY sephora_exclusive
UNION ALL
SELECT 'Nouveauté', new, COUNT(*), ROUND(100.0 * AVG(avis_negatif), 2), ROUND(AVG(rating), 3)
FROM avis_propres WHERE new IS NOT NULL GROUP BY new
UNION ALL
SELECT 'Édition limitée', limited_edition, COUNT(*), ROUND(100.0 * AVG(avis_negatif), 2), ROUND(AVG(rating), 3)
FROM avis_propres WHERE limited_edition IS NOT NULL GROUP BY limited_edition
UNION ALL
SELECT 'Vente en ligne uniquement', online_only, COUNT(*), ROUND(100.0 * AVG(avis_negatif), 2), ROUND(AVG(rating), 3)
FROM avis_propres WHERE online_only IS NOT NULL GROUP BY online_only;

-- Produits à surveiller : dégradation récente de la satisfaction
-- (au moins 100 avis au total, au moins 30 avis sur la période récente,
--  part d'avis négatifs récente supérieure d'au moins 5 points à l'historique)
DROP VIEW IF EXISTS v_produits_a_surveiller;
CREATE VIEW v_produits_a_surveiller AS
WITH p AS (
  SELECT product_id, brand_name, maison_luxe, categorie_analyse, segment_prix,
         COUNT(*) AS nb_avis_total,
         SUM(CASE WHEN date >= '2022-01-01' THEN 1 ELSE 0 END) AS nb_avis_recents,
         100.0 * AVG(CASE WHEN date <  '2022-01-01' THEN avis_negatif END) AS pct_neg_historique,
         100.0 * AVG(CASE WHEN date >= '2022-01-01' THEN avis_negatif END) AS pct_neg_recent
  FROM avis_propres
  GROUP BY product_id
)
SELECT p.*, pr.product_name, pr.price_usd,
       ROUND(pct_neg_recent - pct_neg_historique, 1) AS degradation_points
FROM p JOIN produits_propres pr USING (product_id)
WHERE nb_avis_total >= 100 AND nb_avis_recents >= 30
  AND pct_neg_recent - pct_neg_historique >= 5
ORDER BY degradation_points DESC;
