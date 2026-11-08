# freecad4parametricfea

**Calculs par éléments finis paramétriques pilotés depuis FreeCAD** — maillage pilotable, extraction des
champs en points, nœuds, entités et **segments d'appui avec linéarisation** (membrane / flexion / pic),
plans d'expériences complets ou **fournis dans un classeur Excel**, compatible avec les versions
actuelles de FreeCAD et de Python.

*English summary — Parametric finite-element studies driven from FreeCAD (CalculiX + Gmsh): controllable
mesh, results at user-defined points / nodes / faces / stress classification lines (membrane–bending–peak
linearization, optional azimuthal averaging), full-factorial or Excel-supplied design of experiments, re-extraction
of outputs without re-solving. Pure-Python driver (Python ≥ 3.8), one isolated FreeCAD process per case.
**Tested with FreeCAD 1.1.4 on Windows only.** Version 0.2.0 install: `pip install git+https://github.com/Philippe-AMUZUGA/FreeCAD4ParametricFEA`
(not yet on PyPI; a trusted-publisher release workflow is included and will be run by the author).
New in 0.2.0: `hook`, `mesh.gmsh`, expression-valued mesh sizes, mesh-size guard that accounts for refined zones and checks the real
element count, `reextract --out` with a reduced configuration, configurable `outputs.outside_tol`, optional profile files, azimuthal mean
of a segment, configuration number in `meta.json`, clearer solver-failure messages. See `CHANGELOG.md`.*

## Retour d'expérience

Le module a été éprouvé sur un projet réel : **504 calculs** par éléments finis (une pièce composée d'une virole,
d'une tubulure et d'un anneau, géométrie variable, maillage raffiné par zones), avec plusieurs séries de
réextractions de segments de linéarisation sans recalcul. Les frictions rencontrées (garde-fou de maillage, numéro de
configuration, seuil de matière figé, profils écrits dans les dossiers de cas, réextraction demandant la configuration complète)
ont donné les évolutions de la version 0.2.0.

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

Depuis le dépôt (disponible dès maintenant) :

```bash
pip install git+https://github.com/Philippe-AMUZUGA/FreeCAD4ParametricFEA
pip install "freecad4parametricfea[full] @ git+https://github.com/Philippe-AMUZUGA/FreeCAD4ParametricFEA"   # + scipy, matplotlib, pandas
```

Le paquet n'est pas encore publié sur PyPI : la publication est prévue (workflow `.github/workflows/publish.yml`) et
sera annoncée ici une fois faite par l'auteur ; la commande `pip install freecad4parametricfea` ne fonctionnera qu'à ce moment-là.

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
| `size` | `auto` | taille d'élément (mm), expression des paramètres (`"min(4*E,Di/10)"`) ou `auto` : `min(diagonale/20, plus petite dimension/3)` |
| `n_per_min_dim`, `n_diag` | 3, 20 | paramètres de la règle automatique |
| `size_factor` | 1 | multiplicateur (0,5 → maillage environ 8 fois plus lourd) |
| `min_size`, `max_size` | — | bornes |
| `order` | `2nd` | `1st` ou `2nd` |
| `max_elements` | 400000 | garde-fou : la taille globale est augmentée au-delà (estimation incluant les zones raffinées, avertissement sinon) ; le nombre réel d'éléments est contrôlé après le maillage |
| `on_exceed` | `error` | maillage réel au-delà de `max_elements` : `error` (cas en erreur, solveur non lancé, message explicite), `warn` (calcule quand même, avertissement) ou `ignore` |
| `gmsh` | `{}` | propriétés du maillage Gmsh du modèle à imposer, par ex. `{"HighOrderOptimize": "Optimization", "Algorithm3D": "HXT"}` (corrige les éléments d'ordre 2 à jacobien négatif des coques minces) |
| `n_curv` | 12 | règle auto : éléments par tour sur les petits rayons (trous, congés) ; les rayons inférieurs à diagonale/150 sont ignorés (`min_feature_ratio`) |
| `refine` | `[]` | `{"object":"Pad","subelement":"Face3","size":1}` ou `{"point":[x,y,z],"radius":r,"size":s}` ou `{"segment":[[..],[..]],"radius":r,"size":s}` ; `size` et `radius` peuvent être des expressions des paramètres (`"E/2"`). Le raffinement agit sur des faces entières : découper la pièce (faces séparées autour de la zone utile) pour qu'il reste local |

### `hook`
Chemin d'un fichier Python définissant `after_recompute(App, doc, names)`. Il est exécuté dans FreeCAD après chaque
recalcul de la géométrie (`names` : paramètres du cas et boîte englobante). Usage typique : retrouver les faces des
conditions aux limites et des charges par leur géométrie et réaffecter leurs `References`, quand la numérotation
`FaceN` change d'une configuration à l'autre. Le contenu du fichier entre dans la signature de reprise.

### `outputs`
* `global` : `fields` parmi `vonMises`, `Tresca`, `S1`, `S3`, `Sxx…Sxz`, `U`, `Ux/Uy/Uz`, `eps_vm` ; `location: true` ajoute les coordonnées du maximum. **Par défaut : maxima de tout le modèle.**
* `reactions` (vrai) : résultante des efforts sur chaque appui, lue dans la sortie du solveur (contrôle d'équilibre).
* `points` : `{"name","xyz":[expr,expr,expr],"fields","mode":"interpolate"|"nearest_node","tensor":bool}`.
* `nodes` : `{"name","ids":[...]}` — numéros du maillage (stables seulement si le maillage ne change pas).
* `entities` : `{"name","object","subelement":"Face2","reduce":"max|min|mean|absmax","fields"}`.
* `segments` : `{"name","p1","p2","n":41,"components":bool,"strain":bool,"ref_dir":[..]}` → linéarisation. Options : `outside_tol` (seuil du segment), `save_profile` (écrire ou non son CSV), `azimuth` (moyenne sur plusieurs azimuts, voir plus bas).
* `outside_tol` (0,02) : écart barycentrique toléré pour un point ou un segment ; au-delà, « hors de la matière » (le message donne le point en cause). À relever pour un maillage grossier sur paroi courbe quand le trajet est bien dans la matière.
* `save_profiles` (vrai) : `false` n'écrit pas les `linearization_*.csv` dans les dossiers de cas (les colonnes de sortie ne changent pas).

**Moyenne azimutale.** `"azimuth": {"axis": "z", "origin": [0,0,0], "angles_deg": [0, 90, 180, 270]}` (`axis` : `x`, `y`, `z`, ou deux points `[[..],[..]]`) fait tourner le segment autour de l'axe et moyenne chaque colonne de sortie (moyenne des valeurs, pas valeur du tenseur moyen) ; `NOM_n_azimuts` donne le nombre d'azimuts. Incompatible avec `components`.

Les coordonnées sont des **expressions** des paramètres et de la boîte englobante (`xmin xmax ymin ymax zmin zmax Lx Ly Lz`) :
`"L/2"`, `"ymax-0.5"`. Le segment suit donc la pièce quand sa géométrie varie.

### Colonnes d'un segment `NOM`
`NOM_Pm_vonMises_MPa`, `NOM_Pm_Tresca_MPa` (membrane), `NOM_Pb_…` (flexion, valeur au bord), `NOM_PmPb_start_…` / `_end_…`
(membrane + flexion aux deux extrémités), `NOM_PmPb_max_…`, `NOM_total_max_…`, `NOM_peak_start_vonMises_MPa`,
et avec `components: true` les composantes `Pm_tt, Pm_aa, Pm_bb, Pm_ta, Pm_ab, Pm_tb` dans le repère du segment
(`t` le long du segment). Le profil complet est écrit dans `RES/cases/case_XXXX/linearization_NOM.csv`.

### Numéro de configuration
Si le plan contient une colonne `Config` (`doe.config_column` pour un autre nom ; à lister dans `doe.ignore_columns`), sa valeur est écrite
dans `meta.json` (`config`), avec le rang `index` et la ligne du plan (`plan`), ainsi que dans `case.json` et `results.jsonl` :
on retrouve un dossier `case_NNNN` sans apparier par les valeurs des variables.

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
| `reextract etude.json` | redéfinit les sorties sans relancer le solveur (`--out DOSSIER` : tableaux écrits ailleurs, résultats d'origine intacts). Configuration réduite acceptée : `run.output_dir`, `outputs`, et `"doe": {"type": "from_cases"}` (plan relu dans les `case.json`) ou `doe` + `variables` ; `model` inutile |
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
* **Testé uniquement avec FreeCAD 1.1.4 sous Windows** (tests unitaires sans FreeCAD : Linux et Windows, Python 3.8 à 3.12 en intégration continue). Les replis pour FreeCAD 0.19–1.0 et pour Linux/macOS suivent les différences d'API connues mais n'ont pas été rejoués.
* Pas de commande de suivi (`status`), de relance automatique des échecs avec un autre maillage, de dry run de maillage ni de bascule de condition aux limites par cas : voir le journal des évolutions envisagées dans `CHANGELOG.md`.

## Licence

MIT — voir `LICENSE`.
