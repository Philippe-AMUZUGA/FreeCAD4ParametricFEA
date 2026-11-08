"""Nouveautes 0.2.0 : essais sans FreeCAD (champs synthetiques sur un cube maille en tetraedres)."""
import csv
import json
import os
import re

import numpy as np
import pytest

from freecad4parametricfea import _meshguard as MG
from freecad4parametricfea import cli, extract as EX, runner
from freecad4parametricfea.config import Config
from freecad4parametricfea.locate import FreeCADInstall
from freecad4parametricfea.runner import Study
from test_sampling import cube_tets

HERE = os.path.dirname(os.path.abspath(__file__))
SIDE = 10.0


def make_case(case_dir, index=0, plan=None, params=None, config=None):
    """Dossier de cas synthetique : cube de 10 mm, contrainte szz = x + 2 y (lineaire)."""
    os.makedirs(case_dir, exist_ok=True)
    xyz, conn = cube_tets(4, 1)
    xyz = xyz * SIDE
    stress = np.zeros((len(xyz), 6))
    stress[:, 2] = xyz[:, 0] + 2.0 * xyz[:, 1]
    np.savez(os.path.join(case_dir, "fields.npz"), xyz=xyz, conn=conn, disp=np.zeros((len(xyz), 3)),
             stress=stress, node_ids=np.arange(1, len(xyz) + 1), element_kind=np.array("volume"))
    with open(os.path.join(case_dir, "meta.json"), "w") as fh:
        json.dump({"status": "ok", "E": 210000.0, "nu": 0.3, "names": {}, "reactions": {}}, fh)
    with open(os.path.join(case_dir, "case.json"), "w") as fh:
        json.dump({"index": index, "config": config, "row": {"status": "ok", "time_s": 1.0, "n_elements": 1},
                   "params": params or {}, "plan": plan or {}}, fh)
    return case_dir


def seg(name="S", p2=("5", "5", "9"), **kw):
    d = {"name": name, "p1": ["5", "5", "1"], "p2": list(p2)}
    d.update(kw)
    return d


# ------------------------------------------------------------------ garde-fou du maillage (sans FreeCAD)
def test_refined_zone_adds_elements_to_the_estimate():
    h = 10.0
    base = MG.estimate_elements(1.0e6, h)
    assert base == int(1.0e6 / (h ** 3 / 8.5))
    extra = MG.refined_extra_elements(area=2000.0, size_refined=2.0, h_global=h)
    assert extra > 0
    assert MG.refined_extra_elements(2000.0, 12.0, h) == 0          # raffinement plus grossier que le global : rien
    assert MG.refined_extra_elements(4000.0, 2.0, h) > extra         # croit avec l'aire
    assert MG.refined_extra_elements(2000.0, 1.0, h) > extra         # croit quand la taille diminue


def test_real_mesh_above_cap_fails_before_solver():
    assert MG.check_mesh_size(250000, 250000) is None
    with pytest.raises(MG.MeshTooLarge) as e:
        MG.check_mesh_size(257644, 250000)
    assert "257644" in str(e.value) and "max_elements" in str(e.value)
    assert "257644" in MG.check_mesh_size(257644, 250000, "warn")
    assert MG.check_mesh_size(257644, 250000, "ignore") is None


def test_solver_failure_message_is_explicit():
    m = MG.solver_failure_message(400000, 275351, ["*ERROR in e_c3d", "Killed"])
    assert "275351" in m and "memoire" in m and "Killed" in m
    assert "aucun resultat" in MG.solver_failure_message()


def test_worker_and_meshguard_are_side_by_side():
    pkg = os.path.join(HERE, "..", "src", "freecad4parametricfea")
    assert os.path.isfile(os.path.join(pkg, "_meshguard.py")) and os.path.isfile(os.path.join(pkg, "_worker.py"))
    assert "_meshguard.py" in open(os.path.join(pkg, "_worker.py"), encoding="utf-8").read()


def test_mesh_on_exceed_is_validated():
    assert Config.from_any({"model": "m"})["mesh"]["on_exceed"] == "error"
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "mesh": {"on_exceed": "peut-etre"}})


# ------------------------------------------------------------------------ seuil de matiere configurable
def test_outside_tol_is_configurable_and_error_names_the_point(tmp_path):
    case = make_case(str(tmp_path / "c"))
    outputs = {"global": {"fields": []}, "reactions": False, "segments": [seg(p2=("5", "5", "10.6"))]}
    out, warns = EX.extract_case(case, outputs)
    assert len(warns) == 1 and "outside_tol" in warns[0] and "xyz =" in warns[0] and "point" in warns[0]
    out, warns = EX.extract_case(case, dict(outputs, outside_tol=5.0))
    assert not warns and "S_length_mm" in out
    # seuil propre au segment
    out, warns = EX.extract_case(case, dict(outputs, segments=[seg(p2=("5", "5", "10.6"), outside_tol=5.0)]))
    assert not warns
    assert Config.from_any({"model": "m"})["outputs"]["outside_tol"] == 0.02
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "outputs": {"outside_tol": -1}})


# ------------------------------------------------------------- profils de linearisation facultatifs
def test_save_profiles_option(tmp_path):
    case = make_case(str(tmp_path / "c"))
    base = {"global": {"fields": []}, "reactions": False}
    EX.extract_case(case, dict(base, segments=[seg()]))
    assert os.path.exists(os.path.join(case, "linearization_S.csv"))        # defaut : ecrit (comme en 0.1)
    os.remove(os.path.join(case, "linearization_S.csv"))
    out, warns = EX.extract_case(case, dict(base, save_profiles=False, segments=[seg()]))
    assert not warns and "S_length_mm" in out
    assert not os.path.exists(os.path.join(case, "linearization_S.csv"))
    EX.extract_case(case, dict(base, save_profiles=False, segments=[seg(save_profile=True)]))
    assert os.path.exists(os.path.join(case, "linearization_S.csv"))        # le segment l'emporte


# ------------------------------------------------------------------------------- moyenne azimutale
def test_azimuth_mean_equals_mean_of_individual_segments(tmp_path):
    case = make_case(str(tmp_path / "c"))
    segs = [seg("S%d" % k, p2=p2) for k, p2 in enumerate(
        [("9", "5", "5"), ("5", "9", "5"), ("1", "5", "5"), ("5", "1", "5")])]
    for s in segs:
        s["p1"] = ["5", "5", "5"]
    az = {"name": "A", "p1": ["5", "5", "5"], "p2": ["9", "5", "5"],
          "azimuth": {"axis": "z", "origin": ["5", "5", "0"], "angles_deg": [0, 90, 180, 270]}}
    out, warns = EX.extract_case(case, {"global": {"fields": []}, "reactions": False,
                                        "save_profiles": False, "segments": segs + [az]})
    assert not warns, warns
    assert out["A_n_azimuts"] == 4
    keys = [k for k in out if k.startswith("S0_")]
    assert keys
    for k in keys:
        mean = np.mean([out["S%d_%s" % (i, k[3:])] for i in range(4)])
        assert out["A_" + k[3:]] == pytest.approx(mean, rel=1e-9, abs=1e-9)
    # szz = x + 2y : les quatre segments ne donnent pas la meme valeur, la moyenne est bien distincte
    vals = [out["S%d_Pm_vonMises_MPa" % i] for i in range(4)]
    assert max(vals) - min(vals) > 1.0


def test_azimuth_validation():
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "outputs": {"segments": [
            {"name": "s", "p1": [0, 0, 0], "p2": [1, 0, 0], "azimuth": {"angles_deg": []}}]}})
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "outputs": {"segments": [
            {"name": "s", "p1": [0, 0, 0], "p2": [1, 0, 0], "components": True,
             "azimuth": {"angles_deg": [0, 90]}}]}})
    p = EX.rotate_about_axis([1, 0, 0], [0, 0, 0], [0, 0, 1], 90)
    assert np.allclose(p, [0, 1, 0], atol=1e-12)


# ---------------------------------------------- reextraction avec une configuration reduite (sans modele)
def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_reextract_with_reduced_config_and_no_model(tmp_path):
    res = tmp_path / "RES"
    for i, L in enumerate((100, 120)):
        make_case(str(res / "cases" / ("case_%04d" % i)), index=i, plan={"L": L},
                  params={"Sketch.L": L}, config=i + 1)
    outputs = {"global": {"fields": []}, "reactions": False, "save_profiles": False,
               "segments": [seg()]}
    reduced = {"variables": {"L": "Sketch.L"}, "doe": {"type": "full", "levels": {"L": [100, 120]}},
               "outputs": outputs, "run": {"output_dir": str(res)}}                # pas de `model`
    with pytest.raises(ValueError):
        Study(reduced)                                                              # `run` exige le modele
    st = Study(reduced, reextract_only=True)
    out = tmp_path / "EXTRACT"
    st.reextract(progress=lambda m: None, out_dir=str(out))
    rows = _read_csv(str(out / "results.csv"))
    assert [r["L"] for r in rows] == ["100", "120"] and all(r["status"] == "ok" for r in rows)
    assert "S_length_mm" in rows[0]
    assert not (res / "results.csv").exists()                                       # resultats d'origine intacts
    with pytest.raises(RuntimeError):
        st.run()


def test_reextract_from_cases_needs_no_plan_nor_variables(tmp_path):
    res = tmp_path / "RES"
    for i in range(3):
        make_case(str(res / "cases" / ("case_%04d" % i)), index=i, plan={"L": 100 + i, "Config": 10 + i},
                  params={"Sketch.L": 100 + i}, config=10 + i)
    cfg = {"doe": {"type": "from_cases"}, "run": {"output_dir": str(res)},
           "outputs": {"global": {"fields": ["vonMises"]}, "reactions": False}}
    st = Study(cfg, reextract_only=True)
    st.reextract(progress=lambda m: None, out_dir=str(tmp_path / "X"))
    rows = _read_csv(str(tmp_path / "X" / "results.csv"))
    assert [r["Config"] for r in rows] == ["10", "11", "12"] and "vonMises_max_MPa" in rows[0]
    with pytest.raises(ValueError):
        Config.from_any({"model": "m", "doe": {"type": "from_cases"}})              # `run` ne l'accepte pas
    with pytest.raises(ValueError):
        Study({"doe": {"type": "from_cases"}, "run": {"output_dir": str(tmp_path / "vide")}},
              reextract_only=True).build_cases()


def test_cli_reextract_accepts_config_without_model(tmp_path, capsys):
    res = tmp_path / "RES"
    make_case(str(res / "cases" / "case_0000"), plan={"L": 1}, params={})
    cfg = tmp_path / "e.json"
    cfg.write_text(json.dumps({"doe": {"type": "from_cases"}, "run": {"output_dir": str(res)},
                               "outputs": {"global": {"fields": ["vonMises"]}, "reactions": False}}))
    assert cli.main(["reextract", str(cfg), "--out", str(tmp_path / "OUT")]) == 0
    assert (tmp_path / "OUT" / "results.csv").exists()


# ------------------------------------------------------------------ numero de configuration dans meta.json
def test_config_number_written_to_meta_and_results(tmp_path, monkeypatch):
    model = tmp_path / "m.FCStd"
    model.write_bytes(b"x")

    def fake_launch(self, job, job_path, log_path):
        with open(os.path.join(job["case_dir"], "meta.json"), "w") as fh:
            json.dump({"status": "error", "error": "simule"}, fh)
        return 0

    monkeypatch.setattr(Study, "_launch", fake_launch)
    cfg = {"model": str(model), "doe": {"type": "full", "levels": {"Config": [7, 8]},
                                        "ignore_columns": ["Config"]},
           "run": {"output_dir": str(tmp_path / "RES")}}
    st = Study(cfg, freecad=FreeCADInstall(["x"], "0", "test"))
    st.run(progress=lambda m: None)
    for i, n in enumerate((7, 8)):
        meta = json.load(open(str(tmp_path / "RES" / "cases" / ("case_%04d" % i) / "meta.json")))
        assert meta["index"] == i and meta["config"] == n
        case = json.load(open(str(tmp_path / "RES" / "cases" / ("case_%04d" % i) / "case.json")))
        assert case["config"] == n
    lines = [json.loads(l) for l in open(str(tmp_path / "RES" / "results.jsonl"))]
    assert [l["config"] for l in lines] == [7, 8]
    # sans colonne `Config` : index seul, config = None
    cfg2 = {"model": str(model), "doe": {"type": "none"}, "run": {"output_dir": str(tmp_path / "R2")}}
    Study(cfg2, freecad=FreeCADInstall(["x"], "0", "test")).run(progress=lambda m: None)
    meta = json.load(open(str(tmp_path / "R2" / "cases" / "case_0000" / "meta.json")))
    assert meta["index"] == 0 and meta["config"] is None


# --------------------------------------------------------------------------------------------- doctor
def test_doctor_reports_interpreter_and_missing_python_in_path(monkeypatch, capsys):
    import sys

    def no_freecad(hint=None):
        raise FileNotFoundError("absent")

    monkeypatch.setattr(cli, "find_freecad", no_freecad)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert sys.executable in out and "PATH" in out and "-m freecad4parametricfea" in out


# ------------------------------------------------------------------------------------------ version
def test_versions_agree():
    import freecad4parametricfea as pkg
    pyproject = open(os.path.join(HERE, "..", "pyproject.toml"), encoding="utf-8").read()
    v = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
    assert pkg.__version__ == runner.__version__ == v == "0.2.0"
