"""
Projet : Pilotage de la performance produits et de la satisfaction client
         dans la beauté de luxe (données Sephora)
Étape 1 – Chargement des données dans une base SQLite et premier aperçu

Source : « Sephora Products and Skincare Reviews » (Nady Inky, Kaggle, 2023),
licence CC BY 4.0.
Avant de lancer : décompresser le téléchargement Kaggle dans le dossier data/
(product_info.csv + les fichiers reviews_*.csv).
"""
import glob
import hashlib
import sqlite3
from pathlib import Path

import pandas as pd

DOSSIER = Path("data")
BASE = "sephora.db"

fichier_produits = DOSSIER / "product_info.csv"
fichiers_avis = sorted(glob.glob(str(DOSSIER / "reviews_*.csv")))
if not fichier_produits.exists() or not fichiers_avis:
    raise SystemExit("Fichiers introuvables : mets product_info.csv et les reviews_*.csv dans data/.")

conn = sqlite3.connect(BASE)

# ---------------------------------------------------------------
# 1. Table des produits
# ---------------------------------------------------------------
produits = pd.read_csv(fichier_produits)
produits.to_sql("produits", conn, if_exists="replace", index=False)
print(f"Produits : {len(produits):,} lignes, {produits.shape[1]} colonnes".replace(",", " "))

# ---------------------------------------------------------------
# 2. Table des avis (plusieurs fichiers -> une seule table)
#    L'identifiant de l'autrice est pseudonymisé (hachage) :
#    on garde la possibilité de repérer les doublons sans conserver l'identifiant d'origine.
# ---------------------------------------------------------------
conn.execute("DROP TABLE IF EXISTS avis")
total = 0
for f in fichiers_avis:
    avis = pd.read_csv(f, low_memory=False)
    avis = avis.loc[:, ~avis.columns.str.startswith("Unnamed")]
    if "author_id" in avis.columns:
        avis["author_id"] = avis["author_id"].astype(str).map(
            lambda x: hashlib.sha256(x.encode()).hexdigest()[:12])
    avis["fichier_source"] = Path(f).name
    avis.to_sql("avis", conn, if_exists="append", index=False)
    total += len(avis)
    print(f"  {Path(f).name} : {len(avis):,} avis".replace(",", " "))
print(f"Avis : {total:,} lignes au total".replace(",", " "))

# ---------------------------------------------------------------
# 3. Premier aperçu
# ---------------------------------------------------------------
avis = pd.read_sql("SELECT * FROM avis", conn)

print("\n=== Colonnes des produits ===")
print(", ".join(produits.columns))
print("\n=== Colonnes des avis ===")
print(", ".join(avis.columns))

print("\n=== Valeurs manquantes – produits (%) ===")
m = (produits.isna().mean() * 100).round(1)
print(m[m > 0].sort_values(ascending=False).to_string())
print("\n=== Valeurs manquantes – avis (%) ===")
m = (avis.isna().mean() * 100).round(1)
print(m[m > 0].sort_values(ascending=False).to_string())

if "submission_time" in avis.columns:
    dates = pd.to_datetime(avis["submission_time"], errors="coerce")
    print(f"\nPériode des avis : {dates.min():%d/%m/%Y} -> {dates.max():%d/%m/%Y}")

if "rating" in avis.columns:
    print("\n=== Répartition des notes (%) ===")
    print((avis["rating"].value_counts(normalize=True).sort_index() * 100).round(1).to_string())
if "is_recommended" in avis.columns:
    print(f"\nTaux de recommandation : {avis['is_recommended'].mean() * 100:.1f} %")

print("\n=== Top 15 marques par nombre d'avis ===")
print(avis["brand_name"].value_counts().head(15).to_string())

maisons = ["Dior", "CHANEL", "Lancôme", "Yves Saint Laurent", "Guerlain", "Givenchy",
           "La Mer", "Fresh", "Sisley-Paris", "Tatcha", "Clarins", "Estée Lauder"]
print("\n=== Présence des maisons de luxe (avis / produits) ===")
for mq in maisons:
    na = (avis["brand_name"].str.lower() == mq.lower()).sum()
    npr = (produits["brand_name"].str.lower() == mq.lower()).sum()
    if na or npr:
        print(f"  {mq:<20} {na:>8,} avis   {npr:>4} produits".replace(",", " "))

print("\n=== Prix des produits (USD) ===")
print(produits["price_usd"].describe().round(1).to_string())

for col in ["limited_edition", "new", "sephora_exclusive", "online_only", "out_of_stock"]:
    if col in produits.columns:
        print(f"Part {col:<18}: {produits[col].mean() * 100:5.1f} %")

conn.close()
