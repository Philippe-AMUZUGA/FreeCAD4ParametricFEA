# -*- coding: utf-8 -*-
"""Script execute DANS FreeCAD (freecadcmd) : un cas = ouverture, parametres, maillage, calcul, export.

Il est volontairement autonome (bibliotheque standard + numpy fourni avec FreeCAD) : il ne doit
rien importer du paquet freecad4parametricfea, car l'interpreteur de FreeCAD n'a pas ce paquet.
Il est compatible FreeCAD 0.19 a 1.x (les differences d'API sont traitees par des replis explicites).

Entree  : variable d'environnement F4PFEA_JOB = chemin d'un fichier job.json
Sortie  : <case_dir>/meta.json (toujours ecrit) et <case_dir>/fields.npz (si le calcul a abouti)
"""
import ast
import json
import math
import os
import re
import shutil
import sys
import time
import traceback

MARK = "[f4pfea] "


def log(msg):
    sys.stdout.write(MARK + str(msg) + "\n")
    sys.stdout.flush()


# ----------------------------------------------------------------------------------------------
#  Evaluateur d'expressions numeriques sans danger (coordonnees, tailles) : "L/2", "b*0.5", ...
# ----------------------------------------------------------------------------------------------
_FUNCS = {"sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs,
          "min": min, "max": max, "pi": math.pi, "radians": math.radians, "atan2": math.atan2}


def safe_eval(expr, names):
    if isinstance(expr, (int, float)):
        return float(expr)
    tree = ast.parse(str(expr).strip(), mode="eval")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if hasattr(ast, "Num") and isinstance(n, getattr(ast, "Num")):
            return float(n.n)
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Add):
                return a + b
            if isinstance(n.op, ast.Sub):
                return a - b
            if isinstance(n.op, ast.Mult):
                return a * b
            if isinstance(n.op, ast.Div):
                return a / b
            if isinstance(n.op, ast.Pow):
                return a ** b
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Name):
            if n.id in names:
                return float(names[n.id])
            if n.id in _FUNCS and not callable(_FUNCS[n.id]):
                return _FUNCS[n.id]
            raise ValueError("nom inconnu dans l'expression : %s" % n.id)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS:
            return float(_FUNCS[n.func.id](*[ev(a) for a in n.args]))
        raise ValueError("expression non autorisee : %s" % expr)

    return ev(tree)


# ----------------------------------------------------------------------------------------------
#  Application des parametres
# ----------------------------------------------------------------------------------------------
_MAT_UNITS = {"YoungsModulus": "MPa", "Density": "kg/m^3", "ThermalConductivity": "W/m/K",
              "ThermalExpansionCoefficient": "um/m/K", "SpecificHeat": "J/kg/K",
              "YieldStrength": "MPa", "UltimateStrength": "MPa", "PoissonRatio": ""}


def get_obj(doc, name):
    o = doc.getObject(name)
    if o is None:
        found = doc.getObjectsByLabel(name)
        o = found[0] if found else None
    if o is None:
        raise KeyError("objet introuvable dans le document : %s" % name)
    return o


def _fixed_unit(App, cur):
    """Unite d'entree FIXE selon la dimension (mm, N, MPa, deg, kg), independante des preferences."""
    U = App.Units
    for name, unit in (("Length", "mm"), ("Force", "N"), ("Pressure", "MPa"), ("Angle", "deg"),
                       ("Mass", "kg"), ("Density", "kg/m^3")):
        u = getattr(U, name, None)
        if u is not None and cur.Unit == u:
            return unit
    return None


def _as_quantity_text(App, cur, value):
    """Texte avec unite pour une propriete Quantity, a partir d'un nombre (unite fixe par dimension)."""
    unit = _fixed_unit(App, cur)
    if unit is None:
        raise ValueError("dimension non prise en charge pour une valeur numerique : donner une "
                         "chaine avec unite, par exemple '12 mm' (propriete %s)" % cur.Unit)
    return "%r %s" % (float(value), unit)


def read_target(App, doc, target):
    """Valeur courante d'une cible en unites fixes (mm, N, MPa...), ou None si non numerique."""
    try:
        oname, key = target.split(".", 1)
        obj = get_obj(doc, oname)
        if obj.TypeId == "Sketcher::SketchObject":
            for c in obj.Constraints:
                if c.Name == key:
                    return float(c.Value) if c.Type != "Angle" else math.degrees(c.Value)
        cur = obj
        for part in key.split("."):
            cur = getattr(cur, part)
        if hasattr(cur, "Unit"):
            unit = _fixed_unit(App, cur)
            return float(cur.getValueAs(unit).Value) if unit else float(cur.Value)
        return float(cur)
    except Exception:
        return None


def set_target(App, doc, target, value, materials):
    """target : 'Objet.cle'  (cle = contrainte nommee d'esquisse, propriete, alias de feuille,
    cle de materiau, ou 'Material' = nom d'une fiche definie dans `materials`)."""
    if "." not in target:
        raise ValueError("cible mal formee (attendu Objet.cle) : %s" % target)
    oname, key = target.split(".", 1)
    obj = get_obj(doc, oname)
    tid = obj.TypeId
    # 1. esquisse : contrainte nommee
    if tid == "Sketcher::SketchObject":
        for c in obj.Constraints:
            if c.Name == key:
                unit = "deg" if c.Type == "Angle" else "mm"
                if isinstance(value, str):
                    obj.setDatum(key, App.Units.Quantity(value))
                    return
                if c.Type in ("Weight", "Diameter", "Radius", "Distance", "DistanceX", "DistanceY",
                              "Angle"):
                    q = App.Units.Quantity("%r %s" % (float(value), unit))
                    obj.setDatum(key, q)
                else:
                    obj.setDatum(key, float(value))
                return
    # 2. feuille de calcul : alias
    if tid == "Spreadsheet::Sheet":
        cell = obj.getCellFromAlias(key)
        if cell is None:
            raise KeyError("alias de feuille introuvable : %s" % target)
        obj.set(cell, str(value))
        return
    # 3. materiau
    if hasattr(obj, "Material") and isinstance(getattr(obj, "Material"), dict):
        mat = dict(obj.Material)
        if key == "Material":
            card = materials.get(str(value))
            if card is None:
                raise KeyError("fiche materiau inconnue : %s (declarer 'materials' dans la config)"
                               % value)
            for k, v in card.items():
                mat[k] = _mat_text(k, v)
            mat["Name"] = str(value)
        else:
            mat[key] = _mat_text(key, value)
        obj.Material = mat
        return
    # 4. propriete (chaine 'A.B' autorisee : Placement.Base.x)
    parts = key.split(".")
    if len(parts) > 1:
        # propriete imbriquee (Placement.Base.x) : on modifie une copie puis on reaffecte la racine
        root = getattr(obj, parts[0])
        holder = root
        for p in parts[1:-1]:
            holder = getattr(holder, p)
        setattr(holder, parts[-1], float(value))
        setattr(obj, parts[0], root)
        return
    holder = obj
    last = parts[-1]
    cur = getattr(holder, last)
    if isinstance(value, str):
        setattr(holder, last, value)
    elif hasattr(cur, "Unit") and hasattr(cur, "getUserPreferred"):
        setattr(holder, last, App.Units.Quantity(_as_quantity_text(App, cur, value)))
    elif isinstance(cur, bool):
        setattr(holder, last, bool(value))
    elif isinstance(cur, int):
        setattr(holder, last, int(round(float(value))))
    else:
        setattr(holder, last, float(value))


def _mat_text(key, v):
    if isinstance(v, str):
        return v
    unit = _MAT_UNITS.get(key, "")
    return ("%r %s" % (float(v), unit)).strip()


# ----------------------------------------------------------------------------------------------
#  FEM : recherche des objets, maillage, calcul
# ----------------------------------------------------------------------------------------------
def mesh_kind(o):
    """'gmsh', 'netgen' ou None. Le TypeId d'un maillage Gmsh varie selon la version de FreeCAD :
    on reconnait donc l'objet a ses proprietes."""
    tid = o.TypeId
    if "Netgen" in tid or hasattr(o, "MaxSize") and hasattr(o, "SecondOrder"):
        return "netgen"
    if "Gmsh" in tid or hasattr(o, "CharacteristicLengthMax"):
        return "gmsh"
    return None


def find_fem(doc, job):
    ana = None
    if job.get("analysis"):
        ana = get_obj(doc, job["analysis"])
    else:
        for o in doc.Objects:
            if o.TypeId == "Fem::FemAnalysis":
                ana = o
                break
    if ana is None:
        raise RuntimeError("aucune analyse FEM (Fem::FemAnalysis) dans le document")
    solver = None
    mesh = None
    for o in ana.Group:
        tid = o.TypeId
        if "Solver" in tid and solver is None:
            solver = o
        if mesh_kind(o) and mesh is None:
            mesh = o
    if job.get("solver"):
        solver = get_obj(doc, job["solver"])
    if solver is None:
        raise RuntimeError("aucun solveur dans l'analyse")
    return ana, solver, mesh


def shape_of(obj):
    sh = obj.Shape
    return sh.Shape if hasattr(sh, "Shape") else sh      # maillage : Shape = objet geometrique


def estimate_size(App, shape, cfg):
    """Taille d'element globale (mm) : adaptee aux dimensions de la piece, ou valeur imposee."""
    bb = shape.BoundBox
    dims = sorted([bb.XLength, bb.YLength, bb.ZLength])
    diag = bb.DiagonalLength
    dmin = max(dims[0], 1e-9)
    if dmin < 1e-3 * dims[2]:           # piece quasi plane : on prend la deuxieme dimension
        dmin = max(dims[1], dmin)
    s = cfg.get("size", "auto")
    info = {"bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]}
    if s in (None, "auto"):
        h = min(diag / float(cfg.get("n_diag", 20)), dmin / float(cfg.get("n_per_min_dim", 3)))
        # petits rayons (trous, conges) : n_curv elements par tour complet
        n_curv = float(cfg.get("n_curv", 12))
        if n_curv > 0:
            rmin = None
            for e in shape.Edges:
                try:
                    r = e.Curve.Radius
                except Exception:
                    continue
                if r and r >= diag * float(cfg.get("min_feature_ratio", 1.0 / 150.0)) and (
                        rmin is None or r < rmin):
                    rmin = r
            if rmin:
                h = min(h, 2.0 * math.pi * rmin / n_curv)
                info["min_radius"] = rmin
        h = max(h, diag / 400.0)               # plancher : evite un maillage hors de proportion
        info["rule"] = "auto"
    else:
        h = float(s)
        info["rule"] = "user"
    h *= float(cfg.get("size_factor", 1.0))
    if cfg.get("min_size"):
        h = max(h, float(cfg["min_size"]))
    if cfg.get("max_size"):
        h = min(h, float(cfg["max_size"]))
    # garde-fou : nombre d'elements estime (tetraedre regulier : volume = h^3 / 8.5)
    vol = shape.Volume if shape.Volume else (bb.XLength * bb.YLength * bb.ZLength)
    max_el = float(cfg.get("max_elements", 400000))
    est = vol / (h ** 3 / 8.5) if h > 0 else 0
    if est > max_el:
        h2 = (vol * 8.5 / max_el) ** (1.0 / 3.0)
        info["warning"] = "taille %.4g mm donnerait ~%d elements : portee a %.4g mm" % (h, est, h2)
        h = h2
    info["size"] = h
    info["est_elements"] = int(vol / (h ** 3 / 8.5)) if h > 0 else 0
    return h, info


def set_length(obj, prop, value_mm):
    """Affecte une longueur en mm, que la propriete soit une quantite (chaine) ou un flottant."""
    try:
        setattr(obj, prop, "%r mm" % float(value_mm))
    except (TypeError, ValueError):
        setattr(obj, prop, float(value_mm))


def configure_mesh(App, doc, ana, mesh_obj, cfg, names, info_out):
    import ObjectsFem
    engine = str(cfg.get("engine", "auto")).lower()
    kind0 = mesh_kind(mesh_obj) if mesh_obj is not None else None
    is_gmsh = kind0 == "gmsh"
    is_netgen = kind0 == "netgen"
    if mesh_obj is None or (engine == "gmsh" and not is_gmsh) or (engine == "netgen" and not is_netgen):
        if mesh_obj is not None:
            geom = mesh_obj.Shape
            ana.removeObject(mesh_obj)
        else:
            geom = None
            for o in doc.Objects:
                if o.TypeId.startswith("PartDesign::Body"):
                    geom = o
            if geom is None:
                for o in doc.Objects:
                    if o.isDerivedFrom("Part::Feature"):
                        geom = o
        if engine == "netgen" and hasattr(ObjectsFem, "makeMeshNetgen"):
            mesh_obj = ObjectsFem.makeMeshNetgen(doc, "F4PFEA_MeshNetgen")
            is_gmsh, is_netgen = False, True
        else:
            mesh_obj = ObjectsFem.makeMeshGmsh(doc, "F4PFEA_MeshGmsh")
            is_gmsh, is_netgen = True, False
        mesh_obj.Shape = geom
        ana.addObject(mesh_obj)
        info_out["mesh_object_created"] = mesh_obj.Name
    if cfg.get("engine", "auto") == "keep" or cfg.get("keep_model_mesh"):
        info_out["rule"] = "model"
        return mesh_obj, None
    shape = shape_of(mesh_obj)
    h, info = estimate_size(App, shape, cfg)
    info_out.update(info)
    order = str(cfg.get("order", "2nd"))
    if is_gmsh:
        set_length(mesh_obj, "CharacteristicLengthMax", h)
        set_length(mesh_obj, "CharacteristicLengthMin", float(cfg.get("min_length", 0.0)))
        mesh_obj.ElementOrder = order
        if float(cfg.get("n_curv", 12)) > 0 and hasattr(mesh_obj, "MeshSizeFromCurvature"):
            mesh_obj.MeshSizeFromCurvature = int(cfg.get("n_curv", 12))
        if cfg.get("element_dimension") and hasattr(mesh_obj, "ElementDimension"):
            mesh_obj.ElementDimension = cfg["element_dimension"]
    elif is_netgen:
        set_length(mesh_obj, "MaxSize", h)
        mesh_obj.SecondOrder = (order == "2nd")
    # raffinements locaux
    n_ref = 0
    for i, r in enumerate(cfg.get("refine") or []):
        n_ref += add_refinement(App, doc, mesh_obj, shape, r, names, h, i)
    info_out["n_refinements"] = n_ref
    return mesh_obj, h


def add_refinement(App, doc, mesh_obj, shape, r, names, h_global, idx):
    import ObjectsFem
    import Part
    if mesh_kind(mesh_obj) != "gmsh":
        raise RuntimeError("le raffinement local demande le moteur Gmsh")
    size = float(r.get("size", h_global / 2.0))
    refs = []
    geo = mesh_obj.Shape
    if r.get("subelement"):
        tgt = get_obj(doc, r["object"]) if r.get("object") else geo
        for sub in ([r["subelement"]] if isinstance(r["subelement"], str) else r["subelement"]):
            refs.append((tgt, sub))
    else:
        radius = float(safe_eval(r.get("radius", 0), names))
        if r.get("point") is not None:
            p = [safe_eval(c, names) for c in r["point"]]
            probe = Part.Vertex(App.Vector(*p))
        elif r.get("segment") is not None:
            p1 = [safe_eval(c, names) for c in r["segment"][0]]
            p2 = [safe_eval(c, names) for c in r["segment"][1]]
            probe = Part.makeLine(App.Vector(*p1), App.Vector(*p2))
        else:
            raise ValueError("raffinement : donner subelement, point ou segment")
        for k, f in enumerate(shape.Faces, 1):
            if f.distToShape(probe)[0] <= radius:
                refs.append((geo, "Face%d" % k))
    if not refs:
        return 0
    nm = "F4PFEA_Refine%d" % idx
    if hasattr(ObjectsFem, "makeMeshRegion"):            # FreeCAD >= 1.0
        try:
            ref = ObjectsFem.makeMeshRegion(doc, mesh_obj, element_length=size, name=nm)
        except TypeError:
            ref = ObjectsFem.makeMeshRegion(doc, nm)
    else:                                                # FreeCAD 0.19 - 0.21
        ref = ObjectsFem.makeMeshRefinement(doc, nm)
    set_length(ref, "CharacteristicLength", size)
    ref.References = refs
    if hasattr(mesh_obj, "Group") and ref not in mesh_obj.Group:
        mesh_obj.addObject(ref)                          # anciennes versions : region enfant du maillage
    return len(refs)


def generate_mesh(App, doc, mesh_obj, keep=False):
    if keep:
        fm = mesh_obj.FemMesh
        if fm.NodeCount == 0:
            raise RuntimeError("mesh.engine = keep : le modele ne contient aucun maillage")
        return fm
    if mesh_kind(mesh_obj) == "gmsh":
        from femmesh.gmshtools import GmshTools
        err = GmshTools(mesh_obj).create_mesh()
        if err:
            raise RuntimeError("Gmsh : %s" % err)
    doc.recompute()
    fm = mesh_obj.FemMesh
    if fm.NodeCount == 0 or (fm.VolumeCount == 0 and fm.FaceCount == 0):
        mesh_obj.touch()
        doc.recompute()
        fm = mesh_obj.FemMesh
    if fm.NodeCount == 0:
        raise RuntimeError("maillage vide")
    return fm


def run_ccx(App, doc, ana, solver, workdir, threads):
    os.environ["OMP_NUM_THREADS"] = str(int(threads))
    os.environ["CCX_NPROC_EQUATIONS"] = str(int(threads))
    from femtools import ccxtools
    fea = ccxtools.FemToolsCcx(analysis=ana, solver=solver)
    fea.update_objects()
    fea.setup_working_dir(workdir)
    msg = fea.check_prerequisites()
    if msg:
        raise RuntimeError("prerequis du calcul non satisfaits : %s" % msg)
    fea.setup_ccx()
    fea.purge_results()
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()
    res = None
    for o in ana.Group:
        if o.TypeId == "Fem::FemResultObjectPython":
            res = o
    if res is None:
        raise RuntimeError("le solveur n'a produit aucun resultat")
    return res


def parse_reactions(workdir):
    out = {}
    for fn in os.listdir(workdir):
        if not fn.lower().endswith(".dat"):
            continue
        txt = open(os.path.join(workdir, fn), "r", errors="ignore").read()
        pat = re.compile(r"total force \(fx,fy,fz\) for set (\S+) and time\s+\S+\s+"
                         r"([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)")
        for m in pat.finditer(txt):
            out[m.group(1)] = [float(m.group(2)), float(m.group(3)), float(m.group(4))]
    return out


# ----------------------------------------------------------------------------------------------
#  Export des champs
# ----------------------------------------------------------------------------------------------
def dump_fields(App, doc, res, mesh_obj, entities, path):
    import numpy as np
    ids = list(res.NodeNumbers)
    idx = {nid: i for i, nid in enumerate(ids)}
    fm = res.Mesh.FemMesh if getattr(res, "Mesh", None) is not None else mesh_obj.FemMesh
    nodes = fm.Nodes
    xyz = np.array([[nodes[n].x, nodes[n].y, nodes[n].z] for n in ids], dtype=float)
    disp = np.array([[v.x, v.y, v.z] for v in res.DisplacementVectors], dtype=float)

    def tensor(prefix):
        names = ["XX", "YY", "ZZ", "XY", "YZ", "XZ"]
        arrs = [list(getattr(res, prefix + n)) for n in names]
        if not arrs[0] or len(arrs[0]) != len(ids):
            return None
        return np.array(arrs, dtype=float).T

    stress = tensor("NodeStress")
    strain = tensor("NodeStrain")
    data = {"node_ids": np.array(ids, dtype=np.int64), "xyz": xyz, "disp": disp}
    if stress is not None:
        data["stress"] = stress
    if strain is not None:
        data["strain"] = strain
    data["vonMises_ccx"] = np.array(list(res.vonMises), dtype=float)
    vols = list(fm.Volumes)
    kind = "volume"
    elems = vols
    if not vols:
        elems = list(fm.Faces)
        kind = "face"
    if elems:
        conn = [[idx[n] for n in fm.getElementNodes(e) if n in idx] for e in elems]
        width = max(len(c) for c in conn)
        if any(len(c) != width for c in conn):
            raise RuntimeError("maillage mixte ou incomplet : types d'elements non pris en charge")
        data["conn"] = np.array(conn, dtype=np.int64)
    data["element_kind"] = np.array(kind)
    # groupes de noeuds d'entites demandees par l'utilisateur (face, arete, sommet)
    meta_ent = {}
    mfm = mesh_obj.FemMesh
    for i, ent in enumerate(entities or []):
        try:
            o = get_obj(doc, ent["object"])
            sub = ent["subelement"]
            el = o.Shape.getElement(sub)
            if sub.startswith("Face"):
                ns = mfm.getNodesByFace(el)
            elif sub.startswith("Edge"):
                ns = mfm.getNodesByEdge(el)
            elif sub.startswith("Vertex"):
                ns = mfm.getNodesByVertex(el)
            else:
                ns = ids
            miss = [n for n in ns if n not in idx]
            if miss:
                raise RuntimeError("%d noeuds de l'entite absents du maillage de resultat" % len(miss))
            for n in list(ns)[:50]:
                a, b = mfm.Nodes[n], nodes[n]
                if abs(a.x - b.x) + abs(a.y - b.y) + abs(a.z - b.z) > 1e-6:
                    raise RuntimeError("numerotation des noeuds differente entre maillage et resultat")
            sel = sorted(idx[n] for n in ns)
            data["entity_%d" % i] = np.array(sel, dtype=np.int64)
            meta_ent[ent["name"]] = "entity_%d" % i
        except Exception as exc:                      # entite invalide : signalee, pas fatale
            meta_ent[ent["name"]] = "ERREUR: %s" % exc
    for k in ("xyz", "disp", "stress", "strain"):
        if k in data and not np.all(np.isfinite(data[k])):
            raise RuntimeError("valeurs non finies dans le champ %s : calcul non fiable" % k)
    if len(set(ids)) != len(ids):
        raise RuntimeError("numeros de noeuds en double dans le resultat")
    tmp = path + ".tmp.npz"
    np.savez_compressed(tmp, **data)
    os.replace(tmp, path)
    return meta_ent, kind


def material_props(doc, ana):
    E, nu = None, None
    for o in ana.Group:
        if o.TypeId.startswith("App::MaterialObject") and hasattr(o, "Material"):
            m = o.Material
            try:
                q = App_Quantity(m.get("YoungsModulus", "0 MPa")).getValueAs("MPa")
                E = float(getattr(q, "Value", q))
                nu = float(m.get("PoissonRatio", "0.3").split()[0])
            except Exception:
                pass
            break
    return E, nu


def App_Quantity(text):
    import FreeCAD as App
    return App.Units.Quantity(text)


# ----------------------------------------------------------------------------------------------
#  Programme principal
# ----------------------------------------------------------------------------------------------
def _ustr(q):
    """Quantite lisible (unite usuelle) : '100 N' plutot que l'ecriture en unites de base."""
    return getattr(q, "UserString", str(q))


def inspect_model(App, doc, job):
    out = {"objects": [], "parameters": [], "fem": {}}
    for o in doc.Objects:
        out["objects"].append({"name": o.Name, "label": o.Label, "type": o.TypeId})
        if o.TypeId == "Sketcher::SketchObject":
            for c in o.Constraints:
                if c.Name:
                    out["parameters"].append({"target": "%s.%s" % (o.Name, c.Name),
                                              "value": c.Value, "kind": "contrainte d'esquisse"})
        elif o.TypeId == "Spreadsheet::Sheet":
            for cell in o.getUsedCells() if hasattr(o, "getUsedCells") else []:
                al = o.getAlias(cell)
                if al:
                    out["parameters"].append({"target": "%s.%s" % (o.Name, al),
                                              "value": str(o.get(cell)), "kind": "alias de feuille"})
        elif o.TypeId.startswith("PartDesign::") and hasattr(o, "Length"):
            out["parameters"].append({"target": "%s.Length" % o.Name, "value": _ustr(o.Length),
                                      "kind": "propriete"})
        elif "ConstraintForce" in o.TypeId:
            out["parameters"].append({"target": "%s.Force" % o.Name, "value": _ustr(o.Force),
                                      "kind": "propriete"})
        elif "ConstraintPressure" in o.TypeId:
            out["parameters"].append({"target": "%s.Pressure" % o.Name, "value": _ustr(o.Pressure),
                                      "kind": "propriete"})
        elif hasattr(o, "Material") and isinstance(getattr(o, "Material"), dict):
            for k in ("YoungsModulus", "PoissonRatio", "Density"):
                if k in o.Material:
                    out["parameters"].append({"target": "%s.%s" % (o.Name, k),
                                              "value": o.Material[k], "kind": "materiau"})
    try:
        ana, solver, mesh = find_fem(doc, job)
        out["fem"] = {"analysis": ana.Name, "solver": solver.Name, "solver_type": solver.TypeId,
                      "mesh": mesh.Name if mesh else None,
                      "mesh_type": mesh.TypeId if mesh else None,
                      "group": [(o.Name, o.TypeId) for o in ana.Group]}
        if mesh is not None:
            sh = shape_of(mesh)
            bb = sh.BoundBox
            out["fem"]["bbox"] = [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]
            out["fem"]["volume"] = sh.Volume
            out["fem"]["faces"] = len(sh.Faces)
    except Exception as exc:
        out["fem"] = {"error": str(exc)}
    return out


def main():
    job_path = os.environ.get("F4PFEA_JOB")
    if not job_path:
        raise SystemExit("variable F4PFEA_JOB absente")
    with open(job_path, "r") as fh:
        job = json.load(fh)
    case_dir = job["case_dir"]
    os.makedirs(case_dir, exist_ok=True)
    meta = {"status": "error", "case_id": job.get("case_id"), "warnings": []}
    t0 = time.time()
    try:
        import FreeCAD as App
        meta["freecad_version"] = ".".join(App.Version()[:3])
        doc = App.openDocument(job["model"])
        if job.get("mode") == "inspect":
            meta.update(inspect_model(App, doc, job))
            meta["status"] = "ok"
        else:
            run_case(App, doc, job, meta, case_dir)
    except Exception as exc:
        meta["status"] = "error"
        meta["error"] = "%s: %s" % (type(exc).__name__, exc)
        meta["traceback"] = traceback.format_exc()
        log("ERREUR " + meta["error"])
    meta["time_total_s"] = time.time() - t0
    tmpm = os.path.join(case_dir, "meta.json.tmp")
    with open(tmpm, "w") as fh:
        json.dump(meta, fh, indent=1, default=str)
    os.replace(tmpm, os.path.join(case_dir, "meta.json"))
    log("FIN %s" % meta["status"])


def run_case(App, doc, job, meta, case_dir):
    t = time.time()
    materials = job.get("materials") or {}
    values = job.get("values") or {}                  # alias -> valeur numerique (pour les expressions)
    for target, value in (job.get("params") or {}).items():
        set_target(App, doc, target, value, materials)
    doc.recompute()
    bad = [o.Name for o in doc.Objects if "Invalid" in o.State]
    if bad:
        raise RuntimeError("geometrie invalide apres recalcul : %s" % ", ".join(bad))
    meta["time_geometry_s"] = time.time() - t
    ana, solver, mesh_obj = find_fem(doc, job)
    # noms utilisables dans les expressions (coordonnees, rayons)
    names = dict(values)
    for alias, target in (job.get("variables") or {}).items():
        if alias not in names:
            v = read_target(App, doc, target)
            if v is not None:
                names[alias] = v
    if mesh_obj is not None:
        bb = shape_of(mesh_obj).BoundBox
        names.update({"xmin": bb.XMin, "xmax": bb.XMax, "ymin": bb.YMin, "ymax": bb.YMax,
                      "zmin": bb.ZMin, "zmax": bb.ZMax, "Lx": bb.XLength, "Ly": bb.YLength,
                      "Lz": bb.ZLength})
    meta["names"] = names
    t = time.time()
    minfo = {}
    mesh_obj, h = configure_mesh(App, doc, ana, mesh_obj, job.get("mesh") or {}, names, minfo)
    keep = str((job.get("mesh") or {}).get("engine", "auto")).lower() == "keep"
    fm = generate_mesh(App, doc, mesh_obj, keep)
    minfo.update({"nodes": fm.NodeCount, "volumes": fm.VolumeCount, "faces": fm.FaceCount,
                  "mesh_object": mesh_obj.Name})
    meta["mesh"] = minfo
    if minfo.get("warning"):
        meta["warnings"].append(minfo["warning"])
    if (job.get("mesh") or {}).get("refine") and not minfo.get("n_refinements"):
        meta["warnings"].append("raffinement demande mais aucune face selectionnee")
    meta["time_mesh_s"] = time.time() - t
    t = time.time()
    wd = os.path.join(case_dir, "ccx")
    shutil.rmtree(wd, ignore_errors=True)             # jamais de resultats d'un calcul precedent
    os.makedirs(wd)
    res = run_ccx(App, doc, ana, solver, wd, job.get("ccx_threads", 1))
    meta["time_solve_s"] = time.time() - t
    meta["reactions"] = parse_reactions(wd)
    E, nu = material_props(doc, ana)
    meta["E"], meta["nu"] = E, nu
    entities = job.get("entities") or []
    ent, kind = dump_fields(App, doc, res, mesh_obj, entities, os.path.join(case_dir, "fields.npz"))
    meta["entities"] = ent
    meta["element_kind"] = kind
    if job.get("save_model"):
        doc.saveAs(os.path.join(case_dir, "model_case.FCStd"))
    meta["status"] = "ok"


main()
