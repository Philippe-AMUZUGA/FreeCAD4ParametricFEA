"""Ligne de commande : `freecad4parametricfea` (alias `f4pfea`)."""
import argparse
import json
import os
import sys

from . import __version__
from .config import Config
from .locate import find_freecad, find_tool, candidates, probe_version
from .runner import Study, inspect_model

TEMPLATE = {
    "model": "modele.FCStd",
    "variables": {"L": "Sketch.L", "b": "Pad.Length", "P": "ConstraintForce.Force"},
    "doe": {"type": "full", "levels": {"L": [80, 100, 120], "b": [8, 10], "P": [100]}},
    "mesh": {"size": "auto"},
    "outputs": {
        "global": {"fields": ["vonMises", "Tresca", "U"]},
        "points": [{"name": "P1", "xyz": ["L/2", "0", "b/2"], "fields": ["vonMises", "Tresca"]}],
        "segments": [{"name": "SCL1", "p1": ["L/2", "0", "b/2"], "p2": ["L/2", "10", "b/2"], "n": 41}],
    },
    "run": {"output_dir": "RES", "workers": 1},
}


def cmd_doctor(a):
    print("freecad4parametricfea", __version__, "- Python", sys.version.split()[0])
    try:
        inst = find_freecad(a.freecad)
    except FileNotFoundError as e:
        print("FreeCAD : INTROUVABLE\n  " + str(e))
        return 1
    print("FreeCAD :", " ".join(inst.command), "(version %s, via %s)" % (inst.version, inst.origin))
    for t in ("ccx", "gmsh"):
        print("%-7s :" % t, find_tool(t, inst) or "introuvable (le calcul par CalculiX/Gmsh sera impossible)")
    missing = [t for t in ("ccx", "gmsh") if not find_tool(t, inst)]
    others = [c for c, o in candidates(None) if c != inst.command]
    if others:
        print("autres installations :", ", ".join(" ".join(c) for c in others))
    for mod in ("numpy", "openpyxl", "scipy", "matplotlib"):
        try:
            m = __import__(mod)
            print("%-10s %s" % (mod, getattr(m, "__version__", "ok")))
        except ImportError:
            print("%-10s absent%s" % (mod, "" if mod in ("scipy", "matplotlib") else "  (OBLIGATOIRE)"))
            if mod in ("numpy", "openpyxl"):
                missing.append(mod)
    return 1 if missing else 0


def cmd_init(a):
    d = a.directory
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "etude.json")
    if os.path.exists(p) and not a.force:
        print("existe deja : %s (--force pour ecraser)" % p)
        return 1
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(TEMPLATE, fh, indent=2, ensure_ascii=False)
    print("configuration modele ecrite :", p)
    return 0


def cmd_inspect(a):
    meta = inspect_model(a.model, find_freecad(a.freecad))
    if a.json:
        print(json.dumps(meta, indent=1, default=str))
        return 0
    print("FreeCAD %s - statut %s" % (meta.get("freecad_version"), meta.get("status")))
    if meta.get("error"):
        print(meta["error"])
        return 1
    print("\nParametres modifiables (cible = valeur courante) :")
    for p in meta.get("parameters", []):
        print("  %-34s %-14s %s" % (p["target"], p["value"], p["kind"]))
    fem = meta.get("fem", {})
    print("\nAnalyse FEM :", {k: v for k, v in fem.items() if k != "group"})
    return 0


def cmd_run(a):
    st = Study(a.config, freecad=find_freecad(a.freecad) if a.freecad else None)
    if a.no_resume:
        st.cfg["run"]["resume"] = False
    if a.workers:
        st.cfg["run"]["workers"] = a.workers
    st.run()
    bad = [r for r in st.results if not str(r.get("status")).startswith("ok")]
    return 0 if not bad else 2


def cmd_reextract(a):
    st = Study(a.config)
    st.reextract()
    return 2 if any(not str(r.get("status")).startswith("ok") for r in st.results) else 0


def cmd_converge(a):
    cfg = Config.from_any(a.config)
    cfg["doe"] = {"type": "full", "levels": {"mesh.size_factor": a.factors}}
    cfg["doe"] = dict(cfg["doe"], result_sheet="Convergence", file=None, in_place=False,
                      ignore_columns=[])
    cfg["run"]["output_dir"] = os.path.join(cfg["run"]["output_dir"], "convergence")
    st = Study(cfg)
    st.run()
    return 2 if any(not str(r.get("status")).startswith("ok") for r in st.results) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="freecad4parametricfea",
                                 description="Calculs par elements finis parametriques avec FreeCAD.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("doctor", help="verifie FreeCAD, CalculiX, Gmsh et les dependances")
    p.add_argument("--freecad")
    p.set_defaults(fn=cmd_doctor)
    p = sub.add_parser("init", help="ecrit une configuration modele")
    p.add_argument("directory", nargs="?", default=".")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("inspect", help="liste les parametres d'un modele .FCStd")
    p.add_argument("model")
    p.add_argument("--freecad")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_inspect)
    p = sub.add_parser("run", help="lance l'etude decrite par la configuration")
    p.add_argument("config")
    p.add_argument("--freecad")
    p.add_argument("--workers", type=int)
    p.add_argument("--no-resume", action="store_true", help="recalcule tous les cas")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("reextract", help="redefinit les sorties sans relancer les calculs")
    p.add_argument("config")
    p.set_defaults(fn=cmd_reextract)
    p = sub.add_parser("converge", help="etude de convergence au maillage du cas nominal")
    p.add_argument("config")
    p.add_argument("--factors", type=float, nargs="+", default=[2.0, 1.4, 1.0, 0.7, 0.5])
    p.set_defaults(fn=cmd_converge)
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 0
    try:
        return a.fn(a) or 0
    except (FileNotFoundError, ValueError, KeyError) as e:
        print("Erreur :", e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
