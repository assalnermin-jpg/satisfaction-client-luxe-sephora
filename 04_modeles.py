"""
Étape 4 – Modélisation : vérifier les résultats « toutes choses égales par ailleurs »

Questions :
  Q1. Les maisons de luxe déçoivent-elles vraiment moins, à catégorie, année et type de peau identiques ?
  Q2. Le « paradoxe du très haut prix » : la déception remonte-t-elle au-delà d'un certain prix ?
  Q3. L'effet « nouveauté » est-il réel, ou dû aux avis de produits reçus gratuitement ?
  Q4. L'exclusivité Sephora et l'édition limitée influencent-elles la satisfaction ?

Méthode :
  - Variable expliquée : avis négatif (1 ou 2 étoiles) = 1, sinon 0
  - Modèle de probabilité linéaire (coefficients = effets directs en points de %)
    avec effets fixes catégorie, année et type de peau, erreurs robustes regroupées par produit
  - Vérification de robustesse : régression logistique (effets marginaux moyens)
Pré-requis : pip3 install statsmodels
"""
import re
import sqlite3

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

conn = sqlite3.connect("sephora.db")
cols = ["product_id", "brand_name", "rating", "avis_negatif", "annee", "price_usd", "skin_type",
        "categorie_analyse", "maison_luxe", "new", "sephora_exclusive", "limited_edition",
        "online_only", "review_text"]
df = pd.read_sql(f"SELECT {', '.join(cols)} FROM avis_propres WHERE annee >= 2016", conn)

# ---------------------------------------------------------------
# Préparation
# ---------------------------------------------------------------
df = df.dropna(subset=["price_usd", "categorie_analyse", "maison_luxe"])
df["log_prix"] = np.log(df["price_usd"])
df["skin_type"] = df["skin_type"].fillna("Non renseigné")
df["tranche_prix"] = pd.cut(df["price_usd"], [0, 25, 50, 100, 200, np.inf],
                            labels=["<25$", "25-50$", "50-100$", "100-200$", ">200$"]).astype(str)
for c in ["maison_luxe", "new", "sephora_exclusive", "limited_edition", "online_only"]:
    df[c] = df[c].fillna(0).astype(int)

# Avis de produits reçus gratuitement (repérés dans le texte)
motif = re.compile(r"(?:received (?:this|it|the)(?: product)? (?:for free|free|complimentary)|complimentary|"
                   r"free (?:sample|product|of charge)|gifted|in exchange for|influenster|"
                   r"provided (?:by|to me)|sent (?:me )?(?:this|it) (?:for|to))", re.I)
df["recu_gratuit"] = df["review_text"].fillna("").str.contains(motif).astype(int)
df = df.drop(columns="review_text")

print(f"Avis analysés (2016-2023) : {len(df):,}".replace(",", " "))
print(f"Avis mentionnant un produit reçu gratuitement : {df.recu_gratuit.mean() * 100:.1f} %")
print(f"  dont parmi les nouveautés : {df.loc[df.new == 1, 'recu_gratuit'].mean() * 100:.1f} %  "
      f"| hors nouveautés : {df.loc[df.new == 0, 'recu_gratuit'].mean() * 100:.1f} %")

# Échantillon aléatoire (400 000 avis max) pour limiter le temps de calcul ; les résultats sont stables
ech = df.sample(n=min(len(df), 400_000), random_state=42).copy()
groupes = ech["product_id"].astype("category").cat.codes
controles = "C(categorie_analyse) + C(annee) + C(skin_type)"
resultats = []

def estimer(nom, formule, variables):
    m = smf.ols(formule, data=ech).fit(cov_type="cluster", cov_kwds={"groups": groupes})
    for v in variables:
        if v in m.params:
            ic = m.conf_int().loc[v]
            resultats.append({"modele": nom, "variable": v,
                              "effet_points": round(100 * m.params[v], 2),
                              "ic95_bas": round(100 * ic[0], 2), "ic95_haut": round(100 * ic[1], 2),
                              "p_value": round(m.pvalues[v], 4)})
    return m

# Q1 – Effet luxe (sans puis avec le prix)
estimer("Q1a Luxe (contrôles seuls)", f"avis_negatif ~ maison_luxe + {controles}", ["maison_luxe"])
estimer("Q1b Luxe + prix", f"avis_negatif ~ maison_luxe + log_prix + {controles}", ["maison_luxe", "log_prix"])

# Q2 – Paradoxe du très haut prix (tranches, référence : 25-50 $) et interaction avec le luxe
m2 = estimer("Q2 Tranches de prix",
             f"avis_negatif ~ C(tranche_prix, Treatment('25-50$')) + maison_luxe + {controles}",
             [f"C(tranche_prix, Treatment('25-50$'))[T.{t}]" for t in ["<25$", "50-100$", "100-200$", ">200$"]] + ["maison_luxe"])
estimer("Q2b Luxe très cher (> 200 $)",
        f"avis_negatif ~ maison_luxe * I(price_usd > 200) + {controles}",
        ["maison_luxe", "I(price_usd > 200)[T.True]", "maison_luxe:I(price_usd > 200)[T.True]"])

# Q3 + Q4 – Caractéristiques commerciales, avec contrôle des avis « produit reçu gratuitement »
attributs = ["new", "sephora_exclusive", "limited_edition", "online_only"]
estimer("Q3/Q4 Attributs (sans contrôle cadeau)",
        f"avis_negatif ~ {' + '.join(attributs)} + maison_luxe + log_prix + {controles}", attributs)
estimer("Q3/Q4 Attributs (avec contrôle cadeau)",
        f"avis_negatif ~ {' + '.join(attributs)} + recu_gratuit + maison_luxe + log_prix + {controles}",
        attributs + ["recu_gratuit"])

# Robustesse – régression logistique (effets marginaux moyens) sur 200 000 avis
ech_l = ech.sample(n=min(len(ech), 200_000), random_state=1)
try:
    lg = smf.logit(f"avis_negatif ~ maison_luxe + log_prix + {' + '.join(attributs)} + recu_gratuit + "
                   f"C(annee) + C(skin_type)", data=ech_l).fit(disp=0, maxiter=100)
    me = lg.get_margeff().summary_frame()
    for v in ["maison_luxe", "log_prix", "new", "sephora_exclusive", "recu_gratuit"]:
        if v in me.index:
            resultats.append({"modele": "Robustesse logit (effets marginaux)", "variable": v,
                              "effet_points": round(100 * me.loc[v, "dy/dx"], 2),
                              "ic95_bas": round(100 * me.loc[v, "Conf. Int. Low"], 2),
                              "ic95_haut": round(100 * me.loc[v, "Cont. Int. Hi."], 2),
                              "p_value": round(me.loc[v, "Pr(>|z|)"], 4)})
except Exception as e:
    print(f"(Robustesse logit non estimée : {e})")

res = pd.DataFrame(resultats)
res["significatif_5pct"] = np.where(res["p_value"] < 0.05, "oui", "non")
res.to_csv("resultats_modeles.csv", index=False, encoding="utf-8-sig")
res.to_csv("exports/resultats_modeles.csv", index=False, encoding="utf-8-sig")
res.to_sql("resultats_modeles", conn, if_exists="replace", index=False)

# Taux brut par tranche de prix (pour visualiser le paradoxe)
brut = (df.groupby(["tranche_prix", "maison_luxe"])["avis_negatif"].agg(["mean", "size"])
          .rename(columns={"mean": "pct_negatifs", "size": "nb_avis"}).reset_index())
brut["pct_negatifs"] = (100 * brut["pct_negatifs"]).round(2)
brut.to_csv("exports/negatifs_par_tranche_prix.csv", index=False, encoding="utf-8-sig")

# Alertes : suppression des doublons format normal / mini (avis partagés par Sephora)
surv = pd.read_sql("SELECT * FROM v_produits_a_surveiller", conn)
surv = surv.drop_duplicates(subset=["brand_name", "nb_avis_total", "pct_neg_historique", "pct_neg_recent"])
surv.to_csv("exports/v_produits_a_surveiller.csv", index=False, encoding="utf-8-sig")

pd.set_option("display.width", 220, "display.max_colwidth", 60)
print(f"\nÉchantillon de modélisation : {len(ech):,} avis".replace(",", " "))
print("\n=== Effets estimés (en points de pourcentage d'avis négatifs) ===")
print(res.to_string(index=False))
print("\n=== Part brute d'avis négatifs par tranche de prix (%) ===")
print(brut.pivot(index="tranche_prix", columns="maison_luxe", values="pct_negatifs")
          .rename(columns={0: "Reste du marché", 1: "Maisons de luxe"})
          .reindex(["<25$", "25-50$", "50-100$", "100-200$", ">200$"]).to_string())
print(f"\nProduits à surveiller après suppression des doublons : {len(surv)}")
conn.close()
