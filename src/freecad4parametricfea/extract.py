"""Extraction des sorties d'un cas calcule : maxima globaux, points, noeuds, entites, segments.

Travaille uniquement sur `fields.npz` et `meta.json` ecrits par le worker : aucune installation de
FreeCAD n'est requise ici, et les sorties peuvent etre redefinies apres coup sans relancer le solveur.
"""
import csv
import json
import os

import numpy as np

from . import expr, fields as F, linearization as L
from .sampling import TetSampler

UNIT = {"vonMises": "MPa", "Tresca": "MPa", "S1": "MPa", "S3": "MPa", "U": "mm", "eps_vm": ""}
DEFAULT_FIELDS = ["vonMises", "Tresca", "S1", "U", "eps_vm"]
OUTSIDE_TOL = 0.02       # coordonnee barycentrique negative tolerable (arrondis de geometrie)


def _unit_suffix(name):
    if name in UNIT:
        u = UNIT[name]
    elif name[:1] == "S":
        u = "MPa"
    elif name[:1] == "U":
        u = "mm"
    else:
        u = ""
    return "_" + u if u else ""


class CaseFields(object):
    """Champs nodaux d'un cas et acces aux grandeurs scalaires."""

    def __init__(self, case_dir):
        self.case_dir = case_dir
        self.d = dict(np.load(os.path.join(case_dir, "fields.npz"), allow_pickle=False))
        with open(os.path.join(case_dir, "meta.json")) as fh:
            self.meta = json.load(fh)
        self.xyz = self.d["xyz"]
        self.stress = self.d.get("stress")
        self.strain = self.d.get("strain")
        nu = self.meta.get("nu")
        self.nu = 0.3 if nu is None else float(nu)
        self.young = self.meta.get("E")
        self.finite_check()
        if self.strain is None and self.stress is not None and self.young:
            self.strain = F.stress_to_strain(self.stress, float(self.young), self.nu)
        self._sampler = None

    def finite_check(self):
        for k in ("xyz", "disp", "stress", "strain"):
            if k in self.d and not np.all(np.isfinite(self.d[k])):
                raise ValueError("champ %s non fini" % k)

    def node_scalar(self, name):
        """Champ scalaire nodal (n,) pour une grandeur nommee."""
        if name in ("U", "disp", "displacement"):
            return np.linalg.norm(self.d["disp"], axis=1)
        if name in ("Ux", "Uy", "Uz"):
            return self.d["disp"][:, "xyz".index(name[1])]
        if name == "eps_vm" or name.startswith("e"):
            if self.strain is None:
                raise KeyError("deformations indisponibles")
            return F.scalar_field(name, self.strain, self.nu)
        if self.stress is None:
            raise KeyError("contraintes indisponibles")
        return F.scalar_field(name, self.stress, self.nu)

    def sampler(self):
        if self._sampler is None:
            if "conn" not in self.d or str(self.d["element_kind"]) != "volume":
                raise ValueError("echantillonnage et linearisation : maillage volumique requis")
            self._sampler = TetSampler(self.xyz, self.d["conn"])
        return self._sampler

    def at_points(self, pts, with_strain=True):
        flds = {"stress": self.stress, "disp": self.d["disp"]}
        if with_strain and self.strain is not None:
            flds["strain"] = self.strain
        return self.sampler().sample(pts, flds)


def _scalar_from_sample(name, smp, nu):
    if name in ("U", "disp", "displacement"):
        return np.linalg.norm(smp["disp"], axis=1)
    if name in ("Ux", "Uy", "Uz"):
        return smp["disp"][:, "xyz".index(name[1])]
    if name == "eps_vm" or name.startswith("e"):
        return F.scalar_field(name, smp["strain"], nu)
    return F.scalar_field(name, smp["stress"], nu)


def _reduce(vals, how):
    how = (how or "max").lower()
    if how == "max":
        return float(np.max(vals))
    if how == "min":
        return float(np.min(vals))
    if how in ("mean", "avg"):
        return float(np.mean(vals))
    if how == "absmax":
        return float(np.max(np.abs(vals)))
    raise ValueError("reduction inconnue : %s" % how)


def extract_case(case_dir, outputs, values=None):
    """Retourne (OrderedDict colonnes -> valeurs, avertissements)."""
    cf = CaseFields(case_dir)
    warns = []
    out = {}
    names = dict(cf.meta.get("names", {}))
    names.update(values or {})
    tol = float(outputs.get("outside_tol", OUTSIDE_TOL))
    save_profiles = bool(outputs.get("save_profiles", True))
    # 1. maxima de tout le modele (comportement par defaut)
    g = outputs.get("global") or {}
    for f in g.get("fields", DEFAULT_FIELDS):
        try:
            v = cf.node_scalar(f)
        except KeyError as e:
            warns.append("global %s : %s" % (f, e))
            continue
        i = int(np.argmax(v))
        out["%s_max%s" % (f, _unit_suffix(f))] = float(v[i])
        if g.get("location"):
            for k, c in zip("xyz", cf.xyz[i]):
                out["%s_max_loc_%s_mm" % (f, k)] = float(c)
    # 2. reactions aux appuis
    if outputs.get("reactions", True):
        for setname, fxyz in (cf.meta.get("reactions") or {}).items():
            for k, c in zip("xyz", fxyz):
                out["R_%s_F%s_N" % (setname, k)] = float(c)
    # 3. points
    for p in outputs.get("points") or []:
        try:
            xyz = np.array(expr.point(p["xyz"], names))
            fl = p.get("fields", DEFAULT_FIELDS)
            if p.get("mode", "interpolate") == "nearest_node":
                i = int(np.argmin(np.linalg.norm(cf.xyz - xyz, axis=1)))
                for f in fl:
                    out["%s_%s%s" % (p["name"], f, _unit_suffix(f))] = float(cf.node_scalar(f)[i])
                out["%s_snap_distance_mm" % p["name"]] = float(np.linalg.norm(cf.xyz[i] - xyz))
            else:
                smp, gap = cf.at_points(xyz[None, :])
                for f in fl:
                    out["%s_%s%s" % (p["name"], f, _unit_suffix(f))] = float(
                        _scalar_from_sample(f, smp, cf.nu)[0])
                if gap[0] > p.get("outside_tol", tol):
                    raise ValueError("point hors de la matiere (ecart %.2g > outside_tol %.2g)"
                                     % (gap[0], p.get("outside_tol", tol)))
            if p.get("tensor"):
                for k, c in zip(F.COMPONENTS, (smp["stress"][0] if p.get("mode", "interpolate") != "nearest_node"
                                               else cf.stress[i])):
                    out["%s_S%s_MPa" % (p["name"], k)] = float(c)
        except Exception as e:
            warns.append("point %s : %s" % (p["name"], e))
    # 4. noeuds par numero (numerotation du maillage : stable seulement si le maillage ne change pas)
    ids = list(cf.d["node_ids"])
    for nd in outputs.get("nodes") or []:
        for nid in nd.get("ids", []):
            if nid not in ids:
                warns.append("noeud %s absent du maillage" % nid)
                continue
            i = ids.index(nid)
            for f in nd.get("fields", DEFAULT_FIELDS):
                out["%s_%d_%s%s" % (nd["name"], nid, f, _unit_suffix(f))] = float(cf.node_scalar(f)[i])
    # 5. entites (face, arete, sommet de la CAO)
    for ent in outputs.get("entities") or []:
        key = (cf.meta.get("entities") or {}).get(ent["name"])
        if not key or key.startswith("ERREUR"):
            warns.append("entite %s : %s" % (ent["name"], key))
            continue
        sel = cf.d[key]
        if len(sel) == 0:
            warns.append("entite %s : aucun noeud" % ent["name"])
            continue
        for f in ent.get("fields", DEFAULT_FIELDS):
            v = cf.node_scalar(f)[sel]
            out["%s_%s_%s%s" % (ent["name"], f, ent.get("reduce", "max"), _unit_suffix(f))] = _reduce(
                v, ent.get("reduce", "max"))
    # 6. segments d'appui : linearisation
    for seg in outputs.get("segments") or []:
        try:
            cols = linearize_segment(cf, seg, names, case_dir, tol=tol,
                                     save=seg.get("save_profile", save_profiles))
            out.update(cols)
        except Exception as e:
            warns.append("segment %s : %s" % (seg["name"], e))
    return out, warns


def rotate_about_axis(p, a0, a1, angle_deg):
    """Rotation du point p autour de l'axe (a0 -> a1) d'un angle en degres (formule de Rodrigues)."""
    k = np.asarray(a1, float) - np.asarray(a0, float)
    nk = np.linalg.norm(k)
    if nk == 0:
        raise ValueError("axe d'azimut de longueur nulle")
    k = k / nk
    th = np.radians(float(angle_deg))
    v = np.asarray(p, float) - np.asarray(a0, float)
    r = v * np.cos(th) + np.cross(k, v) * np.sin(th) + k * np.dot(k, v) * (1.0 - np.cos(th))
    return np.asarray(a0, float) + r


def _azimuth_axis(az, names):
    ax = az.get("axis", "z")
    if isinstance(ax, str):
        d = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}.get(ax.lower())
        if d is None:
            raise ValueError("azimuth.axis : x, y, z ou deux points [[..],[..]]")
        a0 = np.array(expr.point(az.get("origin", [0, 0, 0]), names))
        return a0, a0 + np.array(d, float)
    return np.array(expr.point(ax[0], names)), np.array(expr.point(ax[1], names))


def linearize_segment(cf, seg, names, case_dir, tol=None, save=True):
    """Linearise un segment ; avec `azimuth` {axis, origin, angles_deg}, le segment est tourne autour de l'axe
    pour chaque angle (angle 0 = segment tel que donne) et chaque colonne de sortie est la MOYENNE arithmetique
    des valeurs obtenues aux differents azimuts (colonne `<nom>_n_azimuts` : nombre d'azimuts)."""
    tol = OUTSIDE_TOL if tol is None else tol
    tol = seg.get("outside_tol", tol)
    p1 = np.array(expr.point(seg["p1"], names))
    p2 = np.array(expr.point(seg["p2"], names))
    az = seg.get("azimuth")
    if not az:
        return _linearize_one(cf, seg, p1, p2, tol, case_dir, save)
    a0, a1 = _azimuth_axis(az, names)
    angles = [float(a) for a in az["angles_deg"]]
    acc = {}
    for k, ang in enumerate(angles):
        q1, q2 = rotate_about_axis(p1, a0, a1, ang), rotate_about_axis(p2, a0, a1, ang)
        try:
            cols = _linearize_one(cf, seg, q1, q2, tol, case_dir, save and k == 0)
        except ValueError as e:
            raise ValueError("azimut %g deg : %s" % (ang, e))
        for key, v in cols.items():
            acc.setdefault(key, []).append(v)
    out = {key: float(np.mean(v)) for key, v in acc.items()}
    out["%s_n_azimuts" % seg["name"]] = len(angles)
    return out


def _linearize_one(cf, seg, p1, p2, tol, case_dir, save):
    n = int(seg.get("n", 41))
    if n < 3:
        raise ValueError("au moins 3 points de lecture")
    t = np.linalg.norm(p2 - p1)
    s = np.linspace(0.0, t, n)
    pts = p1[None, :] + (p2 - p1)[None, :] * (s / t)[:, None]
    smp, gap = cf.at_points(pts)
    if gap.max() > tol:
        w = int(np.argmax(gap))
        raise ValueError("le segment sort de la matiere (ecart %.2g > outside_tol %.2g au point %d/%d, "
                         "xyz = %.4g, %.4g, %.4g) : verifier p1 et p2, ou augmenter outputs.outside_tol"
                         % (gap.max(), tol, w + 1, n, pts[w, 0], pts[w, 1], pts[w, 2]))
    lin = L.linearize(s, smp["stress"])
    name = seg["name"]
    out = {}
    summ = L.summary(lin)
    unit = "_MPa"
    wanted = seg.get("fields")
    for k, v in summ.items():
        if wanted and not any(k.endswith(w) for w in wanted):
            continue
        out["%s_%s%s" % (name, k, unit)] = v
    out["%s_length_mm" % name] = float(t)
    et, ea, eb = L.local_frame(p1, p2, seg.get("ref_dir"))
    if seg.get("components", False):
        for lab, tens in (("Pm", lin["Sm"]), ("Pb", lin["Sb0"])):
            comp = L.rotate(tens, (et, ea, eb))
            for cn, c in zip(("tt", "aa", "bb", "ta", "ab", "tb"), comp):
                out["%s_%s_%s_MPa" % (name, lab, cn)] = float(c)
    if seg.get("strain", False) and "strain" in smp:
        lin_e = L.linearize(s, smp["strain"])
        out["%s_eps_total_max" % name] = float(F.equivalent_strain(lin_e["total"], cf.nu).max())
        out["%s_eps_membrane" % name] = float(F.equivalent_strain(lin_e["Sm"], cf.nu))
        out["%s_eps_membrane_bending_max" % name] = float(max(
            F.equivalent_strain(lin_e["Sm_Sb_start"], cf.nu),
            F.equivalent_strain(lin_e["Sm_Sb_end"], cf.nu)))
    if save:
        save_profile(case_dir, name, lin, pts, smp, cf.nu)
    return out


def save_profile(case_dir, name, lin, pts, smp, nu):
    """Profil le long du segment (CSV) pour tracer ou verifier : s, xyz, contraintes, composantes."""
    path = os.path.join(case_dir, "linearization_%s.csv" % name)
    head = (["s_mm", "x", "y", "z"] + ["S" + c for c in F.COMPONENTS]
            + ["Sm_vonMises", "SmSb_vonMises", "total_vonMises", "peak_vonMises",
               "total_Tresca", "SmSb_Tresca", "Sm_Tresca"])
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        smsb = lin["Sm"][None, :] + lin["Sb"]
        for i, s in enumerate(lin["s"]):
            w.writerow([s] + list(pts[i]) + list(lin["total"][i])
                       + [float(F.von_mises(lin["Sm"])), float(F.von_mises(smsb[i])),
                          float(F.von_mises(lin["total"][i])), float(F.von_mises(lin["peak"][i])),
                          float(F.tresca(lin["total"][i])), float(F.tresca(smsb[i])),
                          float(F.tresca(lin["Sm"]))])
    return path
