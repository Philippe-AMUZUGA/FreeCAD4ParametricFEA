"""Configuration d'une etude : valeurs par defaut, lecture JSON / TOML / YAML, controle.

Toute cle est facultative sauf `model`. Les chemins relatifs sont relatifs au fichier de configuration.
"""
import copy
import json
import os

DEFAULTS = {
    "model": None,                       # chemin du .FCStd (obligatoire)
    "freecad": None,                     # chemin de freecadcmd / du dossier d'installation (auto sinon)
    "analysis": None,                    # nom de l'analyse FEM (premiere trouvee sinon)
    "solver": None,                      # nom du solveur (premier de l'analyse sinon)
    "variables": {},                     # alias -> cible "Objet.cle"
    "materials": {},                     # nom de fiche -> {YoungsModulus, PoissonRatio, Density}
    "hook": None,                        # fichier Python avec after_recompute(App, doc, names) : execute dans FreeCAD apres
                                         # chaque recalcul (ex. : reattribuer les faces des conditions aux limites par la geometrie)
    "doe": {                             # plan d'experiences
        "type": "full",                  # "full" (plan complet) | "excel" | "none" (un seul calcul)
        "levels": {},                    # pour "full" : alias -> liste | "debut:fin:n" | {start, stop, num}
        "file": None,                    # pour "excel"
        "sheet": None,                   # feuille du plan (premiere si absente)
        "result_sheet": "Resultats",     # nom de la feuille ajoutee
        "in_place": False,               # True : ecrit la feuille dans le fichier d'origine
        "ignore_columns": [],            # colonnes recopiees mais jamais appliquees au modele
        "config_column": "Config",       # colonne du plan donnant le numero de configuration (ecrit dans meta.json)
    },
    "mesh": {
        "engine": "auto",                # auto (celui du modele) | gmsh | netgen | keep (ne pas toucher)
        "size": "auto",                  # "auto" ou taille d'element en mm
        "n_per_min_dim": 3,              # regle auto : elements dans la plus petite dimension
        "n_diag": 20,                    # regle auto : elements sur la diagonale de la boite englobante
        "min_feature_ratio": 1.0 / 150.0,  # rayons plus petits que diagonale*ratio ignores par la regle auto
        "n_curv": 12,                    # regle auto : elements par tour complet sur les petits rayons (0 = inactif)
        "size_factor": 1.0,              # multiplicateur (2 = maillage 2x plus grossier)
        "min_size": None, "max_size": None,
        "order": "2nd",                  # "1st" | "2nd"
        "max_elements": 400000,          # garde-fou : la taille est augmentee au-dela ; le maillage reel est controle ensuite
        "on_exceed": "error",            # maillage reel > max_elements : "error" (cas en echec, solveur non lance) | "warn" | "ignore"
        "refine": [],                    # raffinements locaux (voir documentation)
    },
    "outputs": {
        "global": {"fields": ["vonMises", "Tresca", "S1", "U", "eps_vm"], "location": False},
        "outside_tol": 0.02,             # ecart barycentrique tolere pour un point / segment (hors matiere au-dela)
        "save_profiles": True,           # ecrit linearization_<segment>.csv dans le dossier de chaque cas
        "reactions": True,
        "points": [], "nodes": [], "entities": [], "segments": [],
    },
    "run": {
        "output_dir": "RES",
        "workers": 1,                    # calculs simultanes
        "ccx_threads": 1,                # fils du solveur par calcul
        "timeout_s": 3600,
        "save_every": 5,                 # sauvegarde intermediaire du classeur tous les N cas
        "resume": True,                  # reprend les cas deja calcules
        "keep_fields": True,             # conserve fields.npz (reextraction sans recalcul)
        "keep_solver_files": False,      # conserve le dossier du solveur
        "save_model": False,             # enregistre le .FCStd de chaque cas
        "plots": False,                  # figures de linearisation par cas
        "batch_size": 1,
    },
}

FIELD_ALIASES = {"U": "U", "disp": "U", "displacement": "U"}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k not in ("variables", "materials"):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_file(path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        raw = fh.read()
    if ext in (".json", ""):
        return json.loads(raw.decode("utf-8-sig"))
    if ext == ".toml":
        try:
            import tomllib as toml
        except ImportError:
            try:
                import tomli as toml
            except ImportError:
                raise ImportError("lecture TOML : Python >= 3.11 ou `pip install tomli`")
        return toml.loads(raw.decode("utf-8"))
    if ext in (".yml", ".yaml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("lecture YAML : `pip install pyyaml`")
        return yaml.safe_load(raw.decode("utf-8"))
    raise ValueError("format de configuration non reconnu : %s" % ext)


class Config(dict):
    """Dictionnaire de configuration complete (valeurs par defaut incluses)."""

    @classmethod
    def from_any(cls, source, base_dir=None, require_model=True):
        """require_model=False : `model` facultatif (reextraction, qui n'ouvre aucun modele)."""
        if isinstance(source, Config):
            return source
        if isinstance(source, (str, os.PathLike)):
            path = os.path.abspath(str(source))
            data = load_file(path)
            base_dir = os.path.dirname(path)
        else:
            data = dict(source)
        cfg = cls(_merge(DEFAULTS, data))
        cfg.base_dir = os.path.abspath(base_dir or os.getcwd())
        cfg.validate(require_model)
        return cfg

    base_dir = os.getcwd()

    def path(self, p):
        """Chemin absolu d'un chemin de configuration."""
        if p is None:
            return None
        p = os.path.expanduser(str(p))
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self.base_dir, p))

    def validate(self, require_model=True):
        if require_model and not self.get("model"):
            raise ValueError("configuration : la cle `model` (fichier .FCStd) est obligatoire")
        doe = self["doe"]
        if doe["type"] not in ("full", "excel", "none", "from_cases"):
            raise ValueError("doe.type doit valoir full, excel, none ou from_cases")
        if doe["type"] == "from_cases" and require_model:
            raise ValueError("doe.type = from_cases ne sert qu'a `reextract` (cas deja calcules)")
        if self["mesh"].get("on_exceed", "error") not in ("error", "warn", "ignore"):
            raise ValueError("mesh.on_exceed doit valoir error, warn ou ignore")
        tol = self["outputs"].get("outside_tol", 0.02)
        if not isinstance(tol, (int, float)) or isinstance(tol, bool) or tol < 0:
            raise ValueError("outputs.outside_tol doit etre un nombre >= 0")
        if doe["type"] == "excel" and not doe.get("file"):
            raise ValueError("doe.type = excel demande doe.file")
        if self["mesh"]["order"] not in ("1st", "2nd"):
            raise ValueError("mesh.order doit valoir 1st ou 2nd")
        if self["mesh"]["engine"] not in ("auto", "gmsh", "netgen", "keep"):
            raise ValueError("mesh.engine doit valoir auto, gmsh, netgen ou keep")
        names = set()
        for kind in ("points", "nodes", "entities", "segments"):
            for item in self["outputs"].get(kind) or []:
                n = item.get("name")
                if not n:
                    raise ValueError("outputs.%s : chaque element demande un `name`" % kind)
                if n in names:
                    raise ValueError("nom d'extraction en double : %s" % n)
                names.add(n)
        for s in self["outputs"].get("segments") or []:
            if "p1" not in s or "p2" not in s:
                raise ValueError("segment %s : p1 et p2 sont obligatoires" % s["name"])
            az = s.get("azimuth")
            if az is not None:
                if not isinstance(az, dict) or not az.get("angles_deg"):
                    raise ValueError("segment %s : azimuth demande {\"axis\": ..., \"angles_deg\": [...]}" % s["name"])
                if s.get("components"):
                    raise ValueError("segment %s : `components` et `azimuth` sont incompatibles "
                                     "(le repere local change avec l'azimut)" % s["name"])
        if self["run"]["workers"] < 1:
            raise ValueError("run.workers >= 1")
        return self
