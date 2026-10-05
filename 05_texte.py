"""
Étape 5 – Analyse du texte des avis : POURQUOI les clientes sont déçues

Méthode transparente et explicable : chaque thème est repéré par une liste de mots-clés
(anglais, langue des avis). On mesure la part d'avis négatifs qui évoquent chaque thème,
selon l'univers : maisons de luxe <= 200 $, maisons de luxe > 200 $, reste du marché.
Puis on cherche les mots qui distinguent les avis négatifs du luxe très cher.
"""
import math
import re
import sqlite3
from collections import Counter

import pandas as pd
from scipy.stats import chi2_contingency

conn = sqlite3.connect("sephora.db")
df = pd.read_sql("""SELECT product_id, brand_name, rating, avis_negatif, annee, date, price_usd,
                           maison_luxe, review_text, review_title
                    FROM avis_propres WHERE annee >= 2016 AND texte_disponible = 1""", conn)
df["texte"] = (df["review_title"].fillna("") + " " + df["review_text"].fillna("")).str.lower()
df["univers"] = "Reste du marché"
df.loc[(df.maison_luxe == 1) & (df.price_usd <= 200), "univers"] = "Luxe <= 200 $"
df.loc[(df.maison_luxe == 1) & (df.price_usd > 200), "univers"] = "Luxe > 200 $"

# ---------------------------------------------------------------
# 1. Dictionnaire des thèmes
# ---------------------------------------------------------------
THEMES = {
    "Prix / rapport qualité-prix": r"\b(?:price|pricey|expensive|overpriced|not worth|worth the|money|waste|cost|\$\d+)",
    "Inefficacité / pas de résultat": r"(?:didn'?t (?:do|work|see|notice)|did nothing|does nothing|no (?:difference|results?|change)|not (?:see|notice) any|nothing special|no effect|underwhelm)",
    "Irritation / réaction": r"(?:burn|sting|rash|irritat|redness|red bumps|itch|allerg|reaction|hives|swell)",
    "Boutons / acné": r"(?:break ?outs?|breaks? me out|broke me out|breaking (?:me )?out|acne|pimple|clog|whitehead|blackhead|cystic)",
    "Texture / sensation": r"(?:greasy|sticky|oily|thick|heavy|tacky|pill(?:s|ing|ed)?\b|residue|film)",
    "Dessèchement": r"(?:dried|drying|dry(?:ing)? out|flak|tight(?:ness)?\b|not (?:moisturizing|hydrating))",
    "Odeur / parfum": r"(?:smell|scent|fragrance|odor|perfume)",
    "Emballage / format": r"(?:packag|pump|jar|bottle|leak|dispenser|cap\b|lid\b|tube)",
    "Quantité / taille": r"(?:tiny|so small|small amount|amount of product|runs out|ran out|last(?:s|ed)? (?:long|only))",
    "Reformulation": r"(?:reformulat|new formula|changed the formula|old formula|old version|formula change)",
}
for t, motif in THEMES.items():
    df[t] = df["texte"].str.contains(motif, regex=True).astype(int)

neg = df[df.avis_negatif == 1]
pos = df[df.rating >= 4]

# ---------------------------------------------------------------
# 2. Part des avis négatifs évoquant chaque thème, par univers
# ---------------------------------------------------------------
ordre = ["Luxe <= 200 $", "Luxe > 200 $", "Reste du marché"]
part = (neg.groupby("univers")[list(THEMES)].mean().T * 100).round(1)[ordre]
part["ecart_luxe_cher_vs_luxe_pts"] = (part["Luxe > 200 $"] - part["Luxe <= 200 $"]).round(1)

# Test du khi-deux : le thème est-il significativement plus fréquent dans le luxe > 200 $ ?
pv = {}
sous = neg[neg.univers.isin(["Luxe <= 200 $", "Luxe > 200 $"])]
for t in THEMES:
    tab = pd.crosstab(sous["univers"], sous[t])
    pv[t] = chi2_contingency(tab)[1] if tab.shape == (2, 2) else float("nan")
part["p_value"] = pd.Series(pv).round(4)
part = part.sort_values("ecart_luxe_cher_vs_luxe_pts", ascending=False)

# Thèmes propres aux avis négatifs (comparaison avec les avis positifs)
lift = pd.DataFrame({"pct_avis_negatifs": neg[list(THEMES)].mean() * 100,
                     "pct_avis_positifs": pos[list(THEMES)].mean() * 100})
lift["ratio_neg_vs_pos"] = (lift.pct_avis_negatifs / lift.pct_avis_positifs.replace(0, float("nan"))).round(1)
lift = lift.round(1).sort_values("pct_avis_negatifs", ascending=False)

# ---------------------------------------------------------------
# 3. Mots qui distinguent les avis négatifs du luxe très cher (log-odds lissé)
# ---------------------------------------------------------------
STOP = set("""a about after again all also am an and any are as at be because been before being but by can could
did do does doing don't down during each few for from had has have having he her here hers him his how i i'm i've
if in into is it it's its itself just me more most my myself no nor not now of off on once only or other our out over
own same she should so some such than that the their them then there these they this those through to too under until
up very was we were what when where which while who why will with would you your it’s i’m i’ve really product
products skin face use used using like one get got even much make made feel feels""".split())

def mots(textes):
    c = Counter()
    for t in textes:
        c.update(w for w in re.findall(r"[a-z']{3,}", t) if w not in STOP)
    return c

c_cher = mots(neg.loc[neg.univers == "Luxe > 200 $", "texte"])
c_autres = mots(neg.loc[neg.univers != "Luxe > 200 $", "texte"])
n1, n2 = sum(c_cher.values()), sum(c_autres.values())
distinctifs = []
for w, f1 in c_cher.items():
    if f1 < 15:
        continue
    f2 = c_autres.get(w, 0)
    lo = math.log((f1 + 1) / (n1 - f1 + 1)) - math.log((f2 + 1) / (n2 - f2 + 1))
    se = math.sqrt(1 / (f1 + 1) + 1 / (f2 + 1))
    distinctifs.append({"mot": w, "occurrences_luxe_cher": f1, "z_score": round(lo / se, 2)})
distinctifs = pd.DataFrame(distinctifs).sort_values("z_score", ascending=False).head(25) if distinctifs else pd.DataFrame()

# ---------------------------------------------------------------
# 4. Produits en alerte : la reformulation explique-t-elle la chute ?
# ---------------------------------------------------------------
alertes = pd.read_csv("exports/v_produits_a_surveiller.csv")
alertes = alertes.drop(columns=[c for c in alertes.columns if c.startswith("pct_neg_mention_reformulation")])
al = df[df.product_id.isin(alertes.product_id)].copy()
al["periode"] = (al["date"] >= "2022-01-01").map({True: "recente", False: "historique"})
reform = (al[al.avis_negatif == 1].groupby(["product_id", "periode"])["Reformulation"].mean().unstack() * 100).round(1)
reform = reform.reindex(columns=["historique", "recente"])
reform.columns = ["pct_neg_mention_reformulation_avant", "pct_neg_mention_reformulation_recent"]
alertes = alertes.merge(reform, left_on="product_id", right_index=True, how="left")
alertes.to_csv("exports/v_produits_a_surveiller.csv", index=False, encoding="utf-8-sig")

# ---------------------------------------------------------------
# 5. Exports et affichage
# ---------------------------------------------------------------
part.reset_index(names="theme").to_csv("exports/themes_negatifs_par_univers.csv", index=False, encoding="utf-8-sig")
lift.reset_index(names="theme").to_csv("exports/themes_negatifs_vs_positifs.csv", index=False, encoding="utf-8-sig")
if len(distinctifs):
    distinctifs.to_csv("exports/mots_distinctifs_luxe_cher.csv", index=False, encoding="utf-8-sig")
theme_annee = (neg.groupby("annee")[list(THEMES)].mean() * 100).round(1).reset_index()
theme_annee.to_csv("exports/themes_negatifs_par_annee.csv", index=False, encoding="utf-8-sig")

pd.set_option("display.width", 220)
print(f"Avis avec texte analysés : {len(df):,} dont {len(neg):,} négatifs".replace(",", " "))
print(f"Avis négatifs par univers : " + ", ".join(f"{u} {n:,}".replace(",", " ") for u, n in neg.univers.value_counts().items()))
print("\n=== Thèmes des avis NÉGATIFS : % qui évoquent chaque thème ===")
print(part.to_string())
print("\n=== Thèmes typiques des avis négatifs (vs avis positifs) ===")
print(lift.to_string())
if len(distinctifs):
    print("\n=== Mots qui distinguent les avis négatifs du luxe > 200 $ ===")
    print(distinctifs.to_string(index=False))
cols = ["brand_name", "product_name", "degradation_points", "pct_neg_mention_reformulation_avant", "pct_neg_mention_reformulation_recent"]
print("\n=== Alertes : mention d'une reformulation dans les avis négatifs (%) ===")
print(alertes[cols].head(12).to_string(index=False))
conn.close()
