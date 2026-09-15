# MANUEL D'UTILISATION — AI ENGINEER

*Plateforme d'ingénierie agentique : du cahier des charges aux livrables AutoCAD.*

---

## 1. Ce que fait ce logiciel

Vous donnez un **cahier des charges** en français (ex. : « transporter 500 kg à 20 m/min sous 400 V triphasé »). Le système :

1. **extrait les exigences** (valeurs, unités, normalisation SI) ;
2. **calcule** avec des moteurs déterministes (jamais le LLM) : puissance, efforts, durées de vie roulements, transmissions, fléchissement, chute de tension ;
3. **planifie** le travail en tâches avec dépendances (DAG) ;
4. **vérifie** chaque résultat avec un moteur indépendant (6 règles électriques : fusibles, capacité, chute de tension, masse, bilan de puissance, démarrage) ;
5. **conçoit en 3D** un tracteur paramétrique de 38 pièces avec son **circuit électrique 12 V complet routé à l'intérieur** ;
6. **produit un dossier de livrables organisé par dimension** (3D / 2D / 1D), prêt pour AutoCAD et Excel ;
7. **trace tout** : calculs, sources, hypothèses, versions, événements.

**Règle d'honnêteté** : une information inconnue reste **INCONNU**, une hypothèse est marquée **HYPOTHÈSE**, un résultat non vérifié est marqué **À VÉRIFIER**. Le LLM ne calcule jamais et n'invente jamais un chiffre.

---

## 2. Démarrage

```bash
# 1) Backend (API + orchestrateur) — http://127.0.0.1:8000/docs
.venv/Scripts/python -m uvicorn apps.api.main:app --port 8000

# 2) Console React — http://localhost:5173
cd frontend && npm run dev
```

Les deux serveurs doivent tourner en même temps. La documentation interactive de l'API est sur `http://127.0.0.1:8000/docs`.

---

## 3. La console (http://localhost:5173)

| Zone | Contenu |
|---|---|
| **En haut** | Badge « WS connecté » (vert = flux temps réel OK) + bouton **« Nouveau projet + Exécuter »** |
| **Colonne gauche** | Cahier des charges, exigences extraites, tâches, vérifications, rapport technique, panneau **Tracteur 3D** |
| **Colonne droite** | **Historique des projets** (cliquer = rouvrir une exécution passée) + **flux d'événements temps réel** |

### 3.1 Lancer une exécution complète
1. Vérifiez le cahier des charges dans la zone de texte (modifiable).
2. Cliquez **« Nouveau projet + Exécuter »**.
3. Observez en direct : exigences → tâches → calculs → recherche web (si activée) → vérifications.
4. Cliquez **« Voir le rapport technique »** pour le rapport Markdown complet.

### 3.2 Concevoir le tracteur 3D
1. Après (ou depuis) une exécution, cliquez **« Concevoir le tracteur 3D (pièces + circuit) »**.
2. La **visionneuse 3D** s'affiche : **glisser = tourner, molette = zoomer**.
3. Dans la légende, cliquez **« Capot (corps) »** pour **masquer le capot** et voir le **circuit électrique complet à l'intérieur** (faisceau magenta, composants rouge).
4. Plus bas : tableau des 38 pièces, tableau de dimensionnement électrique (10 circuits), schéma, tableau des 17 fils, badges de vérification.
5. Panneau **« Livrables AutoCAD »** : liens de téléchargement direct (DXF 3D ensemble, nomenclature, cablage CSV, **ZIP complet**).

### 3.3 Concevoir la voiture aéro EV
Cliquez **« Concevoir la voiture aéro EV (3D + circuits) »**. Le système exécute l'ingénierie EV complète de façon déterministe :
1. **Scénario** : traînée/puissance aéro (Cd 0,19), 0–100 km/h, marge moteur (480 kW installés), batterie 95 kWh → autonomie ~805 km.
2. **Réseau HT 800 V** : liaison batterie→onduleur (conducteurs parallèles par pôle, fusible réalisable, réseau IT isolé du châssis) + liaison onduleur→moteur + DC-DC.
3. **Réseau BT 12 V** : éclairage LED, HVAC, info-divertissement, pompes, alimentation DC-DC 3 kW (câble 185 mm², fusible MEGA 350 A).
4. **3D** : corps monovolume goutte d'eau à queue Kamm (coque carbone 3 mm), roues carénées, longerons caisson, pack traction DANS le plancher, faisceaux HT (orange) et BT routés — **32 pièces, 1 543 kg**.
5. **Vérifications indépendantes** : 9 règles (isolation IT, capacité HT, ΔU HT, fusibles HT, fusibles BT, capacité BT, ΔU BT, chemin de masse, bilan de puissance).
6. **Livrables** dans `workspace/<ID>/cad/car/deliverables/` : VOITURE_3D_ENSEMBLE.dxf + 32 pièces 3D + 33 feuilles 2D + 5 CSV + ZIP.

### 3.4 Demander en langage naturel (Assistant IA)
Dans le champ **Assistant IA** d'un projet ouvert :
- « *dessine un tracteur avec ses pièces* » → le système **exécute réellement la conception** (pas le LLM) et régénère le dossier de livrables ;
- « *dessine une voiture hyper aérodynamique* » → pipeline EV complet (scénario + HT/BT + 3D + livrables) ;
- « *quelle est la masse totale ?* » → le LLM (NVIDIA) répond **uniquement à partir des données enregistrées** du projet.

### 3.5 Historique
Chaque exécution est archivée. Cliquez un projet dans le panneau droit pour **rouvrir** résultats, rapport, 3D et livrables sans rien recalculer.

---

## 4. Le dossier de livrables (livraison d'ingénieur)

Emplacement : `workspace/<ID_PROJET>/cad/tractor/deliverables/` — également télégeable en un clic via **LIVRABLES_COMPLETS.zip**.

```
deliverables/
├── 3D_MODELES/                      ← À OUVRIR DANS AUTOCAD (3D)
│   ├── TRACTEUR_3D_ENSEMBLE.dxf       machine complète, 14 908 faces 3D, unités mm
│   │                                  1 couche par groupe, couleurs AutoCAD :
│   │                                  carrosserie=vert, structure=gris, roues=bleu,
│   │                                  moteur=jaune, électrique=rouge, cabine=cyan,
│   │                                  faisceau=magenta
│   └── PIECES/                        34 fichiers PIECE_*.dxf : chaque pièce SEULE en 3D
├── 2D_PLANS/                        ← FEUILLES 2D (AutoCAD)
│   ├── PLANS_ENSEMBLE_ET_PIECES.dxf   TOUTES les feuilles 2D dans UN fichier (grille A3)
│   ├── SCHEMA-01.dxf                  schéma électrique 12 V (calques fonctionnels)
│   └── CABLAGE-01.dxf                 plan de cablage
├── 1D_DONNEES/                      ← TABLEAUX (Excel / import AutoCAD)
│   ├── NOMENCLATURE.csv               BOM : 38 pièces, matière, groupe, masse kg
│   ├── CABLAGE_COMPLET.csv            17 fils : de → vers, section mm², couleur, fusible
│   ├── CIRCUITS_ELECTRIQUES.csv       dimensionnement par circuit (I, section, ΔU %, fusible)
│   ├── VERIFICATIONS.csv              résultats du moteur de vérification indépendant
│   └── INDEX_LIVRABLES.csv            ce que contient chaque fichier du dossier
├── LISEZ-MOI.txt                    guide de lecture + notes d'honnêteté
└── LIVRABLES_COMPLETS.zip           tout le dossier en un téléchargement
```

Les feuilles 2D individuelles (DXF + aperçu SVG) restent aussi disponibles dans `cad/tractor/drawings/` et dans la console.

---

## 5. Ouvrir les fichiers

| Fichier | Logiciel | Comment |
|---|---|---|
| `3D_MODELES/*.dxf` | **AutoCAD** | `FICHIER → OUVRIR` → le 3D apparaît ; vue isométrique recommandée ; chaque groupe est sur son calque (couleur) — geler/éteindre un calque pour inspecter l'intérieur |
| `3D_MODELES/*.dxf` | QCAD / LibreCAD | ouverture directe (vue filaire) |
| `TRACTEUR_3D_ENSEMBLE.dxf` | AutoCAD | pour **inspecter le câblage** : éteindre les calques `body` (carrosserie) et `cabin` → le faisceau et les composants restent visibles |
| `2D_PLANS/*.dxf` | AutoCAD | plans cotés : ensemble + chaque pièce (vues de face/dessus/droite, échelle normalisée, cartouche) ; schéma : calques PUISSANCE (rouge), ECLAIRAGE (jaune), SIGNALISATION (vert), COMMANDE (cyan), MASSE (gris) |
| `tractor_*.stl` (dans `cad/tractor/`) | **Visionneuse 3D Windows** | double-clic — pas besoin d'AutoCAD |
| `electrical_schematic.svg` | navigateur | schéma électrique lisible |
| `1D_DONNEES/*.csv` | **Excel** | double-clic (séparateur `;`, encodage compatible) — importable aussi en tableau AutoCAD |

---

## 6. Ce que contient chaque vérification (VERIFICATIONS.csv)

| Contrôle | Règle |
|---|---|
| `electrical_fusing` | tout consommateur a un fusible normalisé ≥ 1,35·I (sauf démarreur : convention solénoïde, signalée) |
| `electrical_wire_capacity` | capacité du fil ≥ 1,25·I sur chaque circuit |
| `electrical_voltage_drop` | chute de tension ≤ 3 % recalculée avec des constantes indépendantes |
| `electrical_ground_path` | chaque circuit a un retour masse châssis |
| `electrical_power_balance` | alternateur (75 % de rendement continu) ≥ charges permanentes |
| `battery_cranking_capacity` | CCA batterie (~4×Ah) ≥ 1,25×courant démarreur |

Le moteur de vérification **recalcule tout lui-même** avec ses propres constantes et peut **FAIL** une conception défaillante (démontré par des contre-exemples testés). Un FAIL = retour à la conception, jamais une livraison.

---

## 7. Honnêteté technique (à lire avant d'inspecter)

1. Le **3D DXF est facetté** (3DFACE) : ouvrable, cotable, inspectable dans AutoCAD, mais ce n'est **pas du B-Rep volumique** (pas de NURBS, pas d'opération booléenne).
2. La géométrie est une **synthèse paramétrique** : formes et encombrements réalistes, **cotes fonctionnelles à confirmer** par un ingénieur avant toute fabrication (marqué sur chaque cartouche : « À VALIDER avant fabrication »).
3. Les puissances, capacités batterie/alternateur sont des **HYPOTHÈSES** configurables (paramètres `battery_ah`, `alternator_max_a` dans `POST /projects/{id}/tractor`).
4. Les masses viennent de **densités matériaux explicites** (acier 7850, fonte 7200, caoutchouc 1100 kg/m³...) — ce sont des estimations de synthèse, pas des pièces fabricables telles quelles.
5. Le calcul est **reproductible** : chaque valeur → formule, entrées, unités, résultat, hypothèses (via le moteur de calcul, jamais le LLM).

---

## 8. Dépannage

| Symptôme | Cause / solution |
|---|---|
| Badge « WS déconnecté » | backend arrêté → relancer uvicorn ; la console se reconnecte seule (~2 s) |
| « LLM non configuré » dans l'Assistant | clé NVIDIA absente du `.env` → les questions renvoient 400 ; la **conception** fonctionne sans LLM (moteurs déterministes) |
| « web research disabled » | `config.yaml` → `search.enabled: true` (DuckDuckGo sans clé) ou `SERPER_API_KEY` dans `.env` |
| Le 3D ne s'affiche pas | attendez la fin de la conception (~10 s) ; le canvas apparaît avec « Masse totale estimée » |
| DXF illisible dans AutoCAD | vérifiez la version (R12/AC1009 = universel) ; QCAD/LibreCAD pour contrôle croisé |
| Caractères bizarres dans la console | accents mal rendus dans certains logs Windows — sans effet sur les fichiers |

---

## 9. Rappels d'architecture (pour aller plus loin)

- **Le LLM ne calcule jamais** : `ModelRouter` refuse de router un calcul vers le LLM.
- **Les agents ne touchent jamais l'OS** : tout fichier passe par la boîte à outils (sandbox, chemins confinés au workspace, `../` refusé).
- **Événement sourcing** : chaque action (projet créé, calcul, vérification, CAO) est journalisée et visible dans le flux temps réel + `GET /projects/{id}/events`.
- **Versionnage** : chaque conception crée une version (V1, V2…) consultable dans l'historique.
- **Extensible** : fournisseurs CAO/EDA/LLM/simulation interchangeables (`config.yaml`) — SolidWorks, KiCad et STEP s'ajoutent sans refonte quand les outils seront disponibles.

*Manuel généré pour AI ENGINEER — plate-forme d'ingénierie agentique. Toute production réelle exige une validation humaine et/ou réglementaire.*
