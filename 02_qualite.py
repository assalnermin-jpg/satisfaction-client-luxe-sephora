"""
Étape 2 – Contrôle qualité des données et préparation des tables d'analyse

Chaque contrôle est mesuré, puis une décision est prise et documentée.
Résultats :
  - table controles_qualite  : le rapport de qualité (aussi exporté en CSV)
  - table avis_propres       : les avis prêts pour l'analyse
  - table produits_propres   : le catalogue enrichi (segment de prix, maison de luxe)
"""
import sqlite3
import pandas as pd

conn = sqlite3.connect("sephora.db")
avis = pd.read_sql("SELECT * FROM avis", conn)
produits = pd.read_sql("SELECT * FROM produits", conn)
n0 = len(avis)
controles = []

def note(controle, nb, base, decision):
    controles.append({"controle": controle, "nb_lignes": int(nb),
                      "pct": round(100 * nb / base, 2) if base else 0.0, "decision": decision})

# ---------------------------------------------------------------
# 1. Doublons d'avis (même autrice, même produit, même date, même texte)
# ---------------------------------------------------------------
cle = ["author_id", "product_id", "submission_time", "review_text"]
doublons = avis.duplicated(subset=cle, keep="first")
note("Avis en double", doublons.sum(), n0, "Supprimés (on garde le premier)")
avis = avis[~doublons].copy()

# ---------------------------------------------------------------
# 2. Dates invalides
# ---------------------------------------------------------------
avis["date"] = pd.to_datetime(avis["submission_time"], errors="coerce")
mauvaises_dates = avis["date"].isna()
note("Date d'avis invalide", mauvaises_dates.sum(), n0, "Supprimés")
avis = avis[~mauvaises_dates].copy()

# ---------------------------------------------------------------
# 3. Notes hors de l'échelle 1–5
# ---------------------------------------------------------------
hors = ~avis["rating"].between(1, 5)
note("Note hors de l'échelle 1-5", hors.sum(), n0, "Supprimés")
avis = avis[~hors].copy()

# ---------------------------------------------------------------
# 4. Avis dont le produit est absent du catalogue
# ---------------------------------------------------------------
orphelins = ~avis["product_id"].isin(produits["product_id"])
note("Avis sur un produit absent du catalogue", orphelins.sum(), n0,
     "Conservés pour les KPI de satisfaction, exclus des analyses produit")
avis["produit_au_catalogue"] = (~orphelins).astype(int)

# ---------------------------------------------------------------
# 5. Texte d'avis vide
# ---------------------------------------------------------------
vide = avis["review_text"].isna() | (avis["review_text"].astype(str).str.strip() == "")
note("Texte d'avis vide", vide.sum(), n0, "Conservés pour les KPI, exclus de l'analyse du texte")
avis["texte_disponible"] = (~vide).astype(int)

# ---------------------------------------------------------------
# 6. Recommandation manquante
# ---------------------------------------------------------------
note("Recommandation manquante", avis["is_recommended"].isna().sum(), n0,
     "Conservés ; taux de recommandation calculé sur les avis renseignés")

# ---------------------------------------------------------------
# 7. Incohérences note / recommandation
# ---------------------------------------------------------------
incoh = ((avis["rating"] <= 2) & (avis["is_recommended"] == 1)) | \
        ((avis["rating"] == 5) & (avis["is_recommended"] == 0))
note("Incohérence note / recommandation (1-2★ recommandé ou 5★ non recommandé)", incoh.sum(), n0,
     "Conservés et signalés (ambiguïté réelle des clientes)")
avis["incoherence_reco"] = incoh.astype(int)

# ---------------------------------------------------------------
# 8. Marque différente entre l'avis et le catalogue
# ---------------------------------------------------------------
ref = produits.set_index("product_id")["brand_name"]
marque_cat = avis["product_id"].map(ref)
diff = marque_cat.notna() & (marque_cat.str.strip().str.lower() != avis["brand_name"].astype(str).str.strip().str.lower())
note("Marque différente entre avis et catalogue", diff.sum(), n0, "Marque du catalogue retenue (référentiel)")
avis.loc[marque_cat.notna(), "brand_name"] = marque_cat[marque_cat.notna()]

# ---------------------------------------------------------------
# 9. Mois avec très peu d'avis (séries temporelles peu fiables)
# ---------------------------------------------------------------
avis["mois"] = avis["date"].dt.to_period("M").astype(str)
par_mois = avis.groupby("mois").size()
petits = par_mois[par_mois < 1000]
note("Avis publiés lors de mois à moins de 1 000 avis", avis["mois"].isin(petits.index).sum(), n0,
     f"Conservés ; analyses temporelles à partir de {par_mois[par_mois >= 1000].index.min()}")
avis["mois_fiable"] = (~avis["mois"].isin(petits.index)).astype(int)

# ---------------------------------------------------------------
# 10. Catalogue : produits sans note, prix extrêmes
# ---------------------------------------------------------------
np_ = len(produits)
note("Produits sans note ni avis", produits["rating"].isna().sum(), np_,
     "Conservés pour l'analyse du catalogue, exclus des KPI de satisfaction")
q99 = produits["price_usd"].quantile(0.99)
note(f"Produits au prix > 99e centile ({q99:.0f} $)", (produits["price_usd"] > q99).sum(), np_,
     "Conservés (vrais produits de prestige) ; prix analysé en logarithme")

# ---------------------------------------------------------------
# Enrichissements pour l'analyse
# ---------------------------------------------------------------
avis["annee"] = avis["date"].dt.year
avis["avis_negatif"] = (avis["rating"] <= 2).astype(int)
avis["avis_positif"] = (avis["rating"] >= 4).astype(int)

# Segment de prix calculé DANS chaque catégorie (un sérum n'est comparé qu'aux sérums)
cat = produits["tertiary_category"].fillna(produits["secondary_category"]).fillna(produits["primary_category"])
produits["categorie_analyse"] = cat
produits["segment_prix"] = (
    produits.groupby("categorie_analyse")["price_usd"]
    .transform(lambda s: pd.qcut(s.rank(method="first"), 4,
                                 labels=["Entrée de gamme", "Milieu de gamme", "Premium", "Prestige"])
               if s.notna().sum() >= 4 else pd.Series("Non classé", index=s.index))
    .astype(str)
)

MAISONS_LUXE = ["dior", "chanel", "lancôme", "yves saint laurent", "guerlain", "givenchy", "la mer",
                "estée lauder", "clarins", "sisley-paris", "shiseido", "clé de peau beauté",
                "augustinus bader", "dr. barbara sturm", "natura bissé", "valentino", "armani beauty",
                "tom ford", "prada", "gucci", "hermès"]
produits["maison_luxe"] = produits["brand_name"].str.strip().str.lower().isin(MAISONS_LUXE).astype(int)

avis = avis.merge(produits[["product_id", "categorie_analyse", "segment_prix", "maison_luxe",
                            "limited_edition", "new", "sephora_exclusive", "online_only"]],
                  on="product_id", how="left")

# ---------------------------------------------------------------
# Sauvegarde
# ---------------------------------------------------------------
rapport = pd.DataFrame(controles)
rapport.to_sql("controles_qualite", conn, if_exists="replace", index=False)
rapport.to_csv("rapport_qualite.csv", index=False, encoding="utf-8-sig")
avis.drop(columns=["submission_time"]).assign(date=avis["date"].dt.strftime("%Y-%m-%d")) \
    .to_sql("avis_propres", conn, if_exists="replace", index=False)
produits.to_sql("produits_propres", conn, if_exists="replace", index=False)

pd.set_option("display.width", 200, "display.max_colwidth", 70)
print("=== Rapport de qualité ===")
print(rapport.to_string(index=False))
print(f"\nAvis conservés : {len(avis):,} sur {n0:,}".replace(",", " "))
print(f"Maisons de luxe repérées : {produits.loc[produits.maison_luxe == 1, 'brand_name'].nunique()} "
      f"({produits.maison_luxe.sum()} produits, {int(avis.maison_luxe.fillna(0).sum()):,} avis)".replace(",", " "))
print("\n=== Avis par année ===")
print(avis.groupby("annee").size().to_string())
print("\n=== Part d'avis négatifs selon le segment de prix ===")
print((avis.groupby("segment_prix")["avis_negatif"].mean() * 100).round(1).to_string())
conn.close()
