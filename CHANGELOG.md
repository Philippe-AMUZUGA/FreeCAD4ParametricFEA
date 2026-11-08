# Journal des versions

## 0.2.0 (2026-11-08)

Version issue d'un usage sur un projet réel (504 calculs sur une pièce virole + tubulure + anneau, plusieurs séries de réextractions).

### Nouveautés
* `hook` : fichier Python exécuté dans FreeCAD après chaque recalcul (`after_recompute(App, doc, names)`), pour réaffecter les faces des conditions aux limites par la géométrie.
* `mesh.gmsh` : propriétés du maillage Gmsh imposées par l'étude (ex. `HighOrderOptimize`).
* `mesh.size` et `mesh.refine[].size` acceptent une expression des paramètres.
* `reextract --out DOSSIER` (et `Study.reextract(out_dir=...)`) : tableaux écrits dans un autre dossier, sur une copie du classeur du plan ; résultats et classeur d'origine intacts.
* `reextract` n'exige plus qu'une configuration réduite : `model` facultatif (aucun modèle n'est ouvert), `run.output_dir` + `outputs`, et soit `doe`/`variables`, soit `"doe": {"type": "from_cases"}` qui relit le plan et les paramètres enregistrés dans chaque `case.json` (Python : `Study(config, reextract_only=True)`).
* `mesh.on_exceed` (`error` par défaut, `warn`, `ignore`) : le nombre réel d'éléments, zones raffinées comprises, est contrôlé après le maillage et avant le solveur ; au-delà de `mesh.max_elements`, le cas s'arrête avec un message explicite (nombre d'éléments, remèdes). `meta.json` donne aussi `est_elements_refined` (estimation avec zones raffinées) et la colonne `warnings` un avertissement si elle dépasse le plafond.
* `outputs.outside_tol` (0,02 par défaut) : seuil de « hors de la matière » des points et segments, réglable aussi par point ou par segment (`outside_tol`). Le message d'erreur d'un segment donne le point en cause (rang et coordonnées).
* `outputs.save_profiles` (vrai par défaut) et `save_profile` par segment : permettent de ne pas écrire les `linearization_*.csv` dans les dossiers de cas.
* Segment avec `azimuth` : `{"axis": "z"|"x"|"y"|[[p],[p]], "origin": [..], "angles_deg": [0, 90, 180, 270]}` ; le segment est tourné autour de l'axe pour chaque angle et chaque colonne de sortie est la moyenne arithmétique des valeurs obtenues (colonne `NOM_n_azimuts`). Incompatible avec `components` (le repère local change avec l'azimut). Les profils CSV sont ceux du premier azimut.
* Numéro de configuration : `meta.json` reçoit `index` (rang dans le plan), `config` (valeur de la colonne `doe.config_column`, `Config` par défaut, sinon `null`) et `plan` (ligne du plan) ; `case.json` et `results.jsonl` portent aussi `config`.
* `doctor` indique l'interpréteur Python utilisé et la commande à employer quand `python` n'est pas dans le PATH.

### Corrections
* Mode `in_place` : les sauvegardes successives remplacent la feuille de résultats écrite par le paquet (feuille marquée par une couleur d'onglet) au lieu d'en ajouter une à chaque fois.
* Avec un crochet, les contraintes FEM aux références périmées ne rendent plus le cas invalide avant que le crochet ne les ait réparées.
* `reextract` sans `--out` conservait seulement les nouvelles colonnes de sortie et perdait celles d'origine ; l'écriture dans un autre dossier règle ce cas.
* Échec de CalculiX (« aucun résultat ») : le message donne la taille du maillage, les causes probables (mémoire, trop d'éléments, maillage invalide) et les dernières lignes de la sortie du solveur.
* Le garde-fou `mesh.max_elements` ignorait la zone raffinée : l'estimation l'inclut désormais et le maillage réel est contrôlé (voir `mesh.on_exceed`).

### Compatibilité
* Python ≥ 3.8 ; FreeCAD : testé uniquement avec **FreeCAD 1.1.4 sous Windows** (les replis pour 0.19 à 1.0 et pour Linux/macOS n'ont pas été rejoués).
* Changement de comportement : avec `mesh.on_exceed = "error"` (défaut), un maillage réel dépassant `mesh.max_elements` met le cas en erreur au lieu de le calculer. Pour retrouver le comportement de 0.1, mettre `"on_exceed": "warn"` ou relever `max_elements`.
* Les reprises (`resume`) d'études lancées en 0.1.x ne sont pas reconnues : la signature des cas contient la version et les nouvelles clés de configuration ; les cas sont recalculés (ou réextraits avec `reextract`, qui ne dépend pas de cette signature).
* Les fichiers `case.json`, `meta.json` et `results.jsonl` gagnent des clés (`config`, `index`, `plan`) ; aucune clé n'est supprimée ou renommée.
* Nouveau fichier du paquet : `_meshguard.py` (chargé par le script exécuté dans FreeCAD).

### Pistes non traitées (à l'étude)
Commande `status` (cas faits, échecs, mémoire) ; relance des échecs avec un autre maillage (`--retry-failed --set mf=...`) ; dry run de maillage (`mesh_only`) ; mesure de mémoire par tentative ; bascule de contrainte par étude (`constraints.disable`) ; classeur de sortie distinct en mode `in_place` ; repère cylindrique pour les composantes d'un segment ; comptage des éléments traversés par un segment ; ordonnancement des cas lourds (`run.max_heavy`) ; une seule ligne par cas dans `results.jsonl` ; champ `U_max_mm` à vérifier sur des modèles à mouvement de corps rigide.

## 0.1.0
Première version publique : pilote Python pur, un processus FreeCAD par cas, maillage automatique ou imposé
avec raffinements locaux, extraction en points/nœuds/entités/segments, linéarisation membrane-flexion-pic,
plan complet ou plan Excel (feuille `Resultats` ajoutée), reprise, parallélisme, réextraction sans recalcul,
étude de convergence. Validé par deux solutions analytiques (console, virole de Lamé).
