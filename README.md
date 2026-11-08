# freecad4parametricfea

**Calculs par éléments finis paramétriques pilotés depuis FreeCAD** — maillage pilotable, extraction des
champs en points, nœuds, entités et **segments d'appui avec linéarisation** (membrane / flexion / pic),
plans d'expériences complets ou **fournis dans un classeur Excel**, compatible avec les versions
actuelles de FreeCAD et de Python.

*English summary — Parametric finite-element studies driven from FreeCAD (CalculiX + Gmsh): controllable
mesh, results at user-defined points / nodes / faces / stress classification lines (membrane–bending–peak
linearization), full-factorial or Excel-supplied design of experiments, runs on current FreeCAD
(validated on 1.1) and Python ≥ 3.8. Pure-Python driver, one isolated FreeCAD process per case.*

## Ce que ça apporte

| Besoin | Réponse |
|---|---|
| Maillage adapté à la pièce | Taille d'élément **automatique** selon les dimensions (boîte englobante, plus petite dimension), ou imposée ; facteur de grossissement, ordre 1/2, raffinement local par entité ou des faces proches d'un point/segment, garde-fou sur le nombre d'éléments |
| Lire les champs où l'on veut | Maximum de tout le modèle (défaut), **points** (coordonnées ou expressions des paramètres), **nœuds**, **entités** CAO (face, arête, sommet), **segments** |
| Linéarisation (ESP, tuyauterie) | Sur un segment donné par deux points : membrane `Pm`, flexion `Pb`, pic, équivalents von Mises et Tresca, composantes dans le repère du segment, profil exporté en CSV et figure |
| Plan d'expériences | Plan complet par défaut ; **ou votre plan Excel** : le classeur est repris, une feuille `Resultats` est ajoutée (colonnes du plan + colonnes de sortie) |
| Versions | Pilote Python pur ; FreeCAD localisé automatiquement ; API FreeCAD traitée avec replis (testé sur FreeCAD 1.1.4) |
| Robustesse | Un processus FreeCAD par cas : un échec n'arrête pas l'étude ; reprise automatique ; calculs en parallèle ; réextraction des sorties **sans recalcul** |

## Installation

```bash
pip install freecad4parametricfea            # noyau : numpy, openpyxl
pip install "freecad4parametricfea[full]"    # + scipy, matplotlib (figures), pandas
```

Il faut aussi **FreeCAD** (0.19 ou plus récent, avec CalculiX et Gmsh, livrés avec les versions officielles).
Le programme le cherche seul (variable `F4PFEA_FREECADCMD`, PATH, dossiers d'installation usuels). Vérification :

```bash
freecad4parametricfea doctor
```

Sans installation par pip (développeurs, utilisation autonome) : télécharger le dépôt puis

```bash
cd freecad4parametricfea
pip install -e .            # ou : PYTHONPATH=src python -m freecad4parametricfea ...
```

## Démarrage en cinq minutes

1. Dans FreeCAD : une pièce paramétrique **avec son analyse FEM** (matériau, appuis, charges, maillage).
   Nommez les contraintes de l'esquisse à faire varier (`L`, `h`, …).
2. Lister ce qui est modifiable :
   ```bash
   freecad4parametricfea inspect modele.FCStd
   ```
3. Écrire `etude.json` (toutes les clés sauf `model` sont facultatives) :
   ```json
   {
     "model": "modele.FCStd",
     "variables": {"L": "Sketch.L", "b": "Pad.Length", "P": "ConstraintForce.Force"},
     "doe": {"type": "full", "levels": {"L": [80, 100, 120], "b": [8, 10], "P": [100]}},
     "outputs": {
       "points":   [{"name": "Pt", "xyz": ["L/2", "h", "b/2"], "fields": ["Sxx", "vonMises"]}],
       "segments": [{"name": "SCL", "p1": ["L/2", "0", "b/2"], "p2": ["L/2", "h", "b/2"]}]
     }
   }
   ```
4. Lancer :
   ```bash
   freecad4parametricfea run etude.json
   ```
   Résultats : `RES/results.csv` et `RES/plan_resultats.xlsx`.

En Python :

```python
from freecad4parametricfea import run
rows = run("etude.json")        # liste de dictionnaires, une ligne par cas
```

## Référence de configuration

### `variables` et cibles
`alias → "Objet.clé"`. La clé peut être : une **contrainte nommée d'esquisse** (`Sketch.L`), une
**propriété** (`Pad.Length`, `ConstraintForce.Force`, `Placement.Base.x` en chaîne `Obj.Placement.Base.x`),
un **alias de feuille de calcul** (`Params.epaisseur`), une **propriété de matériau**
(`MaterialSolid.YoungsModulus`), ou `MaterialSolid.Material` avec un nom de fiche déclaré dans `materials`.
Un nombre est interprété dans l'unité usuelle de la propriété (mm, N, MPa, degrés pour un angle) ; une chaîne avec
unité (`"250 N"`) est transmise telle quelle.

### `doe` — plan d'expériences
* `"type": "full"` (défaut) : produit cartésien de `levels` (`[1,2,3]`, `"debut:fin:n"`, `{"start":..,"stop":..,"num":..}`).
* `"type": "excel"` : `file`, `sheet` (facultatif). La première ligne non vide donne les en-têtes ; chaque en-tête est
  un alias de `variables`, ou directement une cible `Objet.clé`. Les autres colonnes (`ignore_columns`, ou commençant
  par `#` ou `_`) sont **recopiées** sans être appliquées. Une colonne `mesh.size` ou `mesh.size_factor` fait varier le
  maillage d'une ligne à l'autre. Le classeur d'origine n'est pas modifié (copie dans `RES/`) sauf `"in_place": true`.
* `"type": "none"` : un seul calcul, modèle inchangé.

### `mesh`
| Clé | Défaut | Rôle |
|---|---|---|
| `engine` | `auto` | moteur du modèle ; `gmsh`, `netgen`, ou `keep` (maillage du modèle inchangé) |
| `size` | `auto` | taille d'élément (mm) ou `auto` : `min(diagonale/20, plus petite dimension/3)` |
| `n_per_min_dim`, `n_diag` | 3, 20 | paramètres de la règle automatique |
| `size_factor` | 1 | multiplicateur (0,5 → maillage environ 8 fois plus lourd) |
| `min_size`, `max_size` | — | bornes |
| `order` | `2nd` | `1st` ou `2nd` |
| `max_elements` | 400000 | garde-fou : la taille est augmentée au-delà |
| `n_curv` | 12 | règle auto : éléments par tour sur les petits rayons (trous, congés) ; les rayons inférieurs à diagonale/150 sont ignorés (`min_feature_ratio`) |
| `refine` | `[]` | `{"object":"Pad","subelement":"Face3","size":1}` ou `{"point":[x,y,z],"radius":r,"size":s}` ou `{"segment":[[..],[..]],"radius":r,"size":s}` |

### `outputs`
* `global` : `fields` parmi `vonMises`, `Tresca`, `S1`, `S3`, `Sxx…Sxz`, `U`, `Ux/Uy/Uz`, `eps_vm` ; `location: true` ajoute les coordonnées du maximum. **Par défaut : maxima de tout le modèle.**
* `reactions` (vrai) : résultante des efforts sur chaque appui, lue dans la sortie du solveur (contrôle d'équilibre).
* `points` : `{"name","xyz":[expr,expr,expr],"fields","mode":"interpolate"|"nearest_node","tensor":bool}`.
* `nodes` : `{"name","ids":[...]}` — numéros du maillage (stables seulement si le maillage ne change pas).
* `entities` : `{"name","object","subelement":"Face2","reduce":"max|min|mean|absmax","fields"}`.
* `segments` : `{"name","p1","p2","n":41,"components":bool,"strain":bool,"ref_dir":[..]}` → linéarisation.

Les coordonnées sont des **expressions** des paramètres et de la boîte englobante (`xmin xmax ymin ymax zmin zmax Lx Ly Lz`) :
`"L/2"`, `"ymax-0.5"`. Le segment suit donc la pièce quand sa géométrie varie.

### Colonnes d'un segment `NOM`
`NOM_Pm_vonMises_MPa`, `NOM_Pm_Tresca_MPa` (membrane), `NOM_Pb_…` (flexion, valeur au bord), `NOM_PmPb_start_…` / `_end_…`
(membrane + flexion aux deux extrémités), `NOM_PmPb_max_…`, `NOM_total_max_…`, `NOM_peak_start_vonMises_MPa`,
et avec `components: true` les composantes `Pm_tt, Pm_aa, Pm_bb, Pm_ta, Pm_ab, Pm_tb` dans le repère du segment
(`t` le long du segment). Le profil complet est écrit dans `RES/cases/case_XXXX/linearization_NOM.csv`.

### `run`
`output_dir`, `workers` (cas simultanés), `ccx_threads`, `timeout_s`, `resume`, `save_every`, `keep_fields`
(garde `fields.npz` pour `reextract`), `keep_solver_files`, `save_model`, `plots`.

## Commandes

| Commande | Rôle |
|---|---|
| `doctor` | FreeCAD, CalculiX, Gmsh, dépendances |
| `init` | écrit une configuration modèle |
| `inspect modele.FCStd` | liste cibles modifiables et objets FEM |
| `run etude.json` | exécute l'étude (`--workers N`, `--no-resume`) |
| `reextract etude.json` | redéfinit les sorties sans relancer le solveur |
| `converge etude.json --factors 2 1 0.5` | étude de convergence au maillage du cas nominal |

## Validité vérifiée

Deux cas à solution analytique, joués avec le programme (`examples/`, `tests/`) :

* **Console** (poutre encastrée, effort en bout) : flèche à −0,5 % de la théorie avec cisaillement, contrainte de flexion
  en demi-longueur à 0,0 %, flexion linéarisée à 0,1 %, réaction à l'encastrement égale à l'effort.
* **Virole sous pression** (cas de Lamé, déformation plane) : membrane circonférentielle `p·Ri/(Re−Ri)` à 0,02 %,
  équivalents de Tresca membrane et membrane + flexion à 0,05 % (écart maximal toutes grandeurs : 0,16 %), pour trois épaisseurs (la géométrie varie, les appuis suivent).

```bash
python examples/validate_cantilever.py RES_full/results.csv
python examples/validate_cylinder.py  RES_cyl/results.csv
pytest                      # tests unitaires ; les essais FreeCAD sont joués si FreeCAD est trouvé
```

## Limites connues

* Statique linéaire (solveur CalculiX via l'atelier FEM). Contact, non-linéaire, dynamique : non traités.
* Les références des conditions aux limites sont celles du modèle FreeCAD : si une variation de paramètre
  change la topologie (apparition ou disparition de faces), les noms `FaceN` peuvent se décaler (problème
  classique de nommage topologique). Un cas invalide est signalé par un statut d'erreur, sans arrêter l'étude.
* La linéarisation et l'interpolation en un point demandent un maillage volumique tétraédrique (TET4/TET10) ;
  pour une coque, utiliser `nearest_node` ou les entités.
* Les linéarisations suivent la décomposition membrane / flexion / pic usuelle (composante par composante, intégration exacte sur le profil échantillonné) ; elles ne remplacent pas la classification réglementaire primaire/secondaire, qui reste à la charge de l'ingénieur.
* Un point ou un segment qui sort de la matière fait échouer l'extraction concernée (statut `partial`), sans arrêter l'étude.
* Les contraintes lues sont celles lissées aux nœuds par CalculiX ; près des singularités (appuis rigides,
  arêtes vives) les maxima dépendent du maillage — utiliser `converge` et les segments d'appui.
* Testé sur FreeCAD 1.1.4 (Windows). Les replis pour 0.19–1.0 suivent les différences d'API connues mais n'ont pas été rejoués ici.

## Licence

MIT — voir `LICENSE`.
