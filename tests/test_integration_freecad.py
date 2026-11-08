"""Essais de bout en bout : necessitent FreeCAD (avec CalculiX et Gmsh). Ignores s'il est absent."""
import csv
import os
import subprocess
import sys

import pytest

from freecad4parametricfea import Study, find_freecad

HERE = os.path.dirname(os.path.abspath(__file__))
EX = os.path.join(HERE, "..", "examples")

try:
    INSTALL = find_freecad()
except FileNotFoundError:
    INSTALL = None

pytestmark = [pytest.mark.freecad,
              pytest.mark.skipif(INSTALL is None, reason="FreeCAD introuvable")]


def build_model(script, name, tmp_path):
    """Execute un script de construction de modele dans FreeCAD et retourne le .FCStd produit."""
    src = os.path.join(EX, script)
    code = open(src, encoding="utf-8").read().replace(
        "here = os.path.dirname(os.path.abspath(__file__)) if \"__file__\" in globals() else os.getcwd()",
        "here = %r" % str(tmp_path))
    py = tmp_path / script
    py.write_text(code, encoding="utf-8")
    subprocess.run(list(INSTALL.command) + [str(py)], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=600)
    out = tmp_path / name
    assert out.exists(), "le modele n'a pas ete construit"
    return str(out)


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_cantilever_against_beam_theory(tmp_path):
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    cfg = {"model": model,
           "variables": {"L": "Sketch.L", "h": "Sketch.h", "b": "Pad.Length", "P": "ConstraintForce.Force"},
           "doe": {"type": "full", "levels": {"L": [80, 120], "h": [10], "b": [10], "P": [100]}},
           "outputs": {"global": {"fields": ["vonMises", "U"]},
                       "points": [{"name": "Pt", "xyz": ["L/2", "h", "b/2"], "fields": ["Sxx"]}],
                       "segments": [{"name": "S", "p1": ["L/2", "0", "b/2"], "p2": ["L/2", "h", "b/2"]}]},
           "run": {"output_dir": str(tmp_path / "RES"), "workers": 2}}
    st = Study(cfg)
    st.run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert len(rows) == 2 and all(r["status"].startswith("ok") for r in rows)
    E, nu = 210000.0, 0.3
    for r in rows:
        L, h, b, P = (float(r[k]) for k in ("L", "h", "b", "P"))
        defl = 4 * P * L ** 3 / (E * b * h ** 3) + 1.2 * P * L / (E / (2 * (1 + nu)) * b * h)
        assert float(r["U_max_mm"]) == pytest.approx(defl, rel=0.02)
        assert float(r["Pt_Sxx_MPa"]) == pytest.approx(3 * P * L / (b * h ** 2), rel=0.01)
        assert float(r["S_Pb_Tresca_MPa"]) == pytest.approx(3 * P * L / (b * h ** 2), rel=0.01)
        assert float(r["R_CONSTRAINTFIXED_Fy_N"]) == pytest.approx(P, rel=1e-3)


def test_lame_cylinder_linearization(tmp_path):
    model = build_model("make_cylinder_model.py", "cylinder.FCStd", tmp_path)
    cfg = {"model": model,
           "variables": {"Ri": "CylIn.Radius", "Re": "CylOut.Radius", "p": "ConstraintPressure.Pressure"},
           "doe": {"type": "full", "levels": {"Ri": [100], "Re": [110, 130], "p": [10]}},
           "mesh": {"size_factor": 0.7},
           "outputs": {"global": {"fields": ["vonMises"]},
                       "segments": [{"name": "S", "components": True,
                                     "p1": ["Ri*0.70710678", "Ri*0.70710678", "zmax/2"],
                                     "p2": ["Re*0.70710678", "Re*0.70710678", "zmax/2"]}]},
           "run": {"output_dir": str(tmp_path / "RES"), "workers": 2}}
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert len(rows) == 2 and all(r["status"].startswith("ok") for r in rows)
    for r in rows:
        ri, re, p = float(r["Ri"]), float(r["Re"]), float(r["p"])
        # equilibre exact : membrane circonferentielle = p ri / (re - ri)
        assert float(r["S_Pm_bb_MPa"]) == pytest.approx(p * ri / (re - ri), rel=0.01)
        A = p * ri ** 2 / (re ** 2 - ri ** 2)
        assert float(r["S_Pm_aa_MPa"]) == pytest.approx(2 * 0.3 * A, rel=0.01)


def test_failed_case_does_not_stop_the_study(tmp_path):
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    cfg = {"model": model, "variables": {"L": "Sketch.L"},
           "doe": {"type": "full", "levels": {"L": [100, 0.0]}},       # L = 0 : geometrie impossible
           "outputs": {"global": {"fields": ["vonMises"]}},
           "run": {"output_dir": str(tmp_path / "RES")}}
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert rows[0]["status"].startswith("ok") and rows[1]["status"] == "error" and rows[1]["error"]


def test_resume_skips_done_cases(tmp_path):
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    cfg = {"model": model, "variables": {"P": "ConstraintForce.Force"},
           "doe": {"type": "full", "levels": {"P": [100, 200]}},
           "outputs": {"global": {"fields": ["vonMises"]}},
           "run": {"output_dir": str(tmp_path / "RES")}}
    Study(cfg).run(progress=lambda m: None)
    msgs = []
    Study(cfg).run(progress=msgs.append)
    assert "2 deja calcules" in msgs[0]


def test_mesh_size_and_refine_size_as_expressions(tmp_path):
    """mesh.size et refine[].size peuvent etre des expressions des parametres (ici h)."""
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    base = {"model": model,
            "variables": {"L": "Sketch.L", "h": "Sketch.h", "b": "Pad.Length"},
            "doe": {"type": "full", "levels": {"L": [100], "h": [10, 20], "b": [10]}},
            "outputs": {"global": {"fields": ["vonMises"]}},
            "run": {"workers": 2}}
    cfg = dict(base, mesh={"size": "h/2", "refine": [
        {"segment": [["L/2", "0", "b/2"], ["L/2", "h", "b/2"]], "radius": "h", "size": "h/4"}]},
        run={"output_dir": str(tmp_path / "RES"), "workers": 2})
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert len(rows) == 2 and all(r["status"].startswith("ok") for r in rows)
    assert float(rows[0]["mesh_size_mm"]) == pytest.approx(5.0, rel=1e-6)
    assert float(rows[1]["mesh_size_mm"]) == pytest.approx(10.0, rel=1e-6)


def test_hook_after_recompute_can_rebuild_references(tmp_path):
    """Un crochet Python (`hook`) est execute dans FreeCAD apres chaque recalcul : ici il impose l'effort
    P = 10 b ; la reaction a l'encastrement doit le suivre."""
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    hook = tmp_path / "hook.py"
    hook.write_text("def after_recompute(App, doc, names):\n"
                    "    doc.getObject('ConstraintForce').Force = '%g N' % (10.0 * names['b'])\n",
                    encoding="utf-8")
    cfg = {"model": model, "hook": str(hook),
           "variables": {"b": "Pad.Length"},
           "doe": {"type": "full", "levels": {"b": [10, 20]}},
           "outputs": {"global": {"fields": ["vonMises"]}},
           "run": {"output_dir": str(tmp_path / "RES"), "workers": 2}}
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert all(r["status"].startswith("ok") for r in rows)
    for r in rows:
        assert float(r["R_CONSTRAINTFIXED_Fy_N"]) == pytest.approx(10.0 * float(r["b"]), rel=1e-3)


def test_hook_repairs_stale_references(tmp_path):
    """Les references FEM perimees apres un recalcul ne rendent pas le cas invalide si un crochet les repare."""
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    hook = tmp_path / "hook2.py"
    # le crochet reaffecte l'encastrement a la face situee en x = 0
    hook.write_text(
        "def after_recompute(App, doc, names):\n"
        "    pad = doc.getObject('Pad')\n"
        "    fx0 = [('Face%d' % i) for i, f in enumerate(pad.Shape.Faces, 1)\n"
        "           if abs(f.BoundBox.XMin) < 1e-6 and abs(f.BoundBox.XMax) < 1e-6]\n"
        "    for o in doc.Objects:\n"
        "        if o.TypeId == 'Fem::ConstraintFixed':\n"
        "            o.References = [(pad, f) for f in fx0]\n",
        encoding="utf-8")
    cfg = {"model": model, "hook": str(hook), "variables": {"L": "Sketch.L"},
           "doe": {"type": "full", "levels": {"L": [100, 140]}},
           "outputs": {"global": {"fields": ["vonMises"]}},
           "run": {"output_dir": str(tmp_path / "RES"), "workers": 2}}
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert all(r["status"].startswith("ok") for r in rows)


def test_mesh_gmsh_properties_passthrough(tmp_path):
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    cfg = {"model": model, "variables": {"L": "Sketch.L"},
           "doe": {"type": "full", "levels": {"L": [100]}},
           "mesh": {"gmsh": {"HighOrderOptimize": "Optimization", "Algorithm3D": "Delaunay"}},
           "outputs": {"global": {"fields": ["vonMises"]}},
           "run": {"output_dir": str(tmp_path / "RES")}}
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES"), "results.csv"))
    assert rows[0]["status"].startswith("ok")
    cfg["mesh"]["gmsh"] = {"PropriateInexistante": 1}
    cfg["run"]["output_dir"] = str(tmp_path / "RES2")
    Study(cfg).run(progress=lambda m: None)
    rows = read(os.path.join(str(tmp_path / "RES2"), "results.csv"))
    assert rows[0]["status"] == "error" and "propriete inconnue" in rows[0]["error"]


def test_max_elements_guard_counts_refined_zone(tmp_path):
    """Le plafond tient compte de la zone raffinee : estimation annoncee, puis controle du maillage reel ;
    `on_exceed: error` arrete le cas avant le solveur, `warn` le laisse calculer."""
    model = build_model("make_cantilever_model.py", "cantilever.FCStd", tmp_path)
    cfg = {"model": model, "variables": {"L": "Sketch.L"},
           "doe": {"type": "full", "levels": {"L": [100]}},
           "mesh": {"max_elements": 200,
                    "refine": [{"segment": [["L/2", "0", "5"], ["L/2", "10", "5"]], "radius": 3, "size": 0.8}]},
           "outputs": {"global": {"fields": ["vonMises"]}},
           "run": {"output_dir": str(tmp_path / "RES")}}
    Study(cfg).run(progress=lambda m: None)
    row = read(os.path.join(str(tmp_path / "RES"), "results.csv"))[0]
    assert row["status"] == "error" and "mesh.max_elements" in row["error"] and "zones raffinees" in row["warnings"]
    cfg["mesh"]["on_exceed"] = "warn"
    cfg["run"]["output_dir"] = str(tmp_path / "RES2")
    Study(cfg).run(progress=lambda m: None)
    row = read(os.path.join(str(tmp_path / "RES2"), "results.csv"))[0]
    assert row["status"].startswith("ok") and "mesh.max_elements" in row["warnings"]
