"""
Étape 3 – Dictionnaire des KPI, vues SQL de pilotage et exports pour Power BI
"""
import sqlite3
from pathlib import Path
import pandas as pd

conn = sqlite3.connect("sephora.db")
conn.executescript(Path("03_kpi.sql").read_text(encoding="utf-8"))
Path("exports").mkdir(exist_ok=True)

# ---------------------------------------------------------------
# 1. Dictionnaire des KPI
# ---------------------------------------------------------------
kpi = pd.DataFrame([
    ["Volume d'avis", "Nombre d'avis publiés", "COUNT(*)", "avis_propres", "Mois, marque, produit", "Indicateur d'activité / de demande", "Baisse > 20 % vs N-1"],
    ["Note moyenne", "Moyenne des notes de 1 à 5", "AVG(rating)", "avis_propres.rating", "Mois, marque, produit", "Plus haut = mieux", "< 4,0"],
    ["Part d'avis négatifs", "Part des avis notés 1 ou 2 étoiles", "AVG(rating <= 2)", "avis_propres.rating", "Mois, marque, produit", "Plus bas = mieux (KPI principal)", "> 15 % ou +5 pts vs historique"],
    ["Part d'avis positifs", "Part des avis notés 4 ou 5 étoiles", "AVG(rating >= 4)", "avis_propres.rating", "Mois, marque, produit", "Plus haut = mieux", "< 75 %"],
    ["Score net de satisfaction", "Part d'avis positifs moins part d'avis négatifs", "% positifs - % négatifs", "avis_propres.rating", "Mois, marque, produit", "Plus haut = mieux", "< 60 points"],
    ["Taux de recommandation", "Part des clientes qui recommandent le produit (avis renseignés)", "AVG(is_recommended)", "avis_propres.is_recommended", "Mois, marque, produit", "Plus haut = mieux", "< 80 %"],
    ["Évolution des avis négatifs N vs N-1", "Variation en points de la part d'avis négatifs sur un an", "pct_neg(N) - pct_neg(N-1)", "v_kpi_marque_annee", "Marque, année", "Négatif = amélioration", "> +3 points"],
    ["Popularité", "Nombre de « loves » (ajouts en favoris)", "loves_count", "produits_propres.loves_count", "Produit, marque", "Plus haut = mieux", "-"],
    ["Prix moyen", "Prix moyen des produits (USD)", "AVG(price_usd)", "produits_propres.price_usd", "Marque, catégorie, segment", "Positionnement", "-"],
    ["Produits à surveiller", "Produits dont la part d'avis négatifs récente dépasse l'historique de 5 points ou plus", "pct_neg_recent - pct_neg_historique >= 5", "v_produits_a_surveiller", "Produit", "Alerte", "Toute apparition"],
], columns=["kpi", "definition", "formule", "source", "granularite", "lecture", "seuil_alerte"])
kpi.to_csv("dictionnaire_kpi.csv", index=False, encoding="utf-8-sig")
kpi.to_sql("dictionnaire_kpi", conn, if_exists="replace", index=False)

# ---------------------------------------------------------------
# 2. Début de la période fiable : premier mois à partir duquel
#    tous les mois suivants comptent au moins 1 000 avis
# ---------------------------------------------------------------
mens = pd.read_sql("SELECT * FROM v_kpi_mensuel ORDER BY mois", conn)
faibles = mens.loc[mens["nb_avis"] < 1000, "mois"]
derniers_complets = mens["mois"].iloc[-1]
faibles = faibles[faibles < derniers_complets]  # le dernier mois (incomplet) ne compte pas
debut_fiable = mens.loc[mens["mois"] > faibles.max(), "mois"].min() if len(faibles) else mens["mois"].min()

# ---------------------------------------------------------------
# 3. Exports pour Power BI
# ---------------------------------------------------------------
vues = ["v_kpi_mensuel", "v_kpi_marque_annee", "v_kpi_categorie_segment",
        "v_luxe_vs_marche", "v_kpi_attributs", "v_produits_a_surveiller"]
for v in vues:
    pd.read_sql(f"SELECT * FROM {v}", conn).to_csv(f"exports/{v}.csv", index=False, encoding="utf-8-sig")
pd.read_sql("SELECT * FROM produits_propres", conn).to_csv("exports/produits.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------
# 4. Premiers résultats
# ---------------------------------------------------------------
pd.set_option("display.width", 200, "display.max_colwidth", 45)
print(f"Période fiable pour les analyses dans le temps : à partir de {debut_fiable}")

print("\n=== Maisons de luxe vs reste du marché (depuis 2016) ===")
print(pd.read_sql("""SELECT univers, SUM(nb_avis) AS nb_avis,
                     ROUND(SUM(note_moyenne*nb_avis)/SUM(nb_avis),3) AS note_moyenne,
                     ROUND(SUM(pct_avis_negatifs*nb_avis)/SUM(nb_avis),2) AS pct_avis_negatifs
                     FROM v_luxe_vs_marche WHERE annee >= 2016 GROUP BY univers""", conn).to_string(index=False))

marques = pd.read_sql("""SELECT brand_name, MAX(maison_luxe) AS luxe, SUM(nb_avis) AS nb_avis,
                         ROUND(SUM(pct_avis_negatifs*nb_avis)/SUM(nb_avis),1) AS pct_neg,
                         ROUND(SUM(note_moyenne*nb_avis)/SUM(nb_avis),2) AS note
                         FROM v_kpi_marque_annee GROUP BY brand_name HAVING SUM(nb_avis) >= 3000""", conn)
print(f"\n=== Marques les MIEUX notées (>= 3 000 avis, {len(marques)} marques) ===")
print(marques.sort_values("pct_neg").head(10).to_string(index=False))
print("\n=== Marques les PLUS critiquées ===")
print(marques.sort_values("pct_neg", ascending=False).head(10).to_string(index=False))
print("\n=== Maisons de luxe (>= 3 000 avis) ===")
print(marques[marques.luxe == 1].sort_values("pct_neg").to_string(index=False))

print("\n=== Caractéristiques commerciales ===")
print(pd.read_sql("SELECT * FROM v_kpi_attributs", conn).to_string(index=False))

surv = pd.read_sql("SELECT * FROM v_produits_a_surveiller", conn)
print(f"\n=== Produits à surveiller : {len(surv)} ===")
print(surv[["brand_name", "product_name", "nb_avis_recents", "pct_neg_historique", "pct_neg_recent", "degradation_points"]]
      .head(10).round(1).to_string(index=False))

print(f"\nExports écrits dans le dossier exports/ ({len(vues) + 1} fichiers) + dictionnaire_kpi.csv")
conn.close()
