"""Linearisation des contraintes le long d'un segment d'appui (membrane, flexion, pic)
selon la decomposition usuelle des recueils de dimensionnement (ASME VIII-2 5.2.2, EN 13445-3 annexe C).

Le segment va du point A (s = 0) au point B (s = t). Pour chaque composante du tenseur :
    membrane   Sm = (1/t) * integrale(S ds)
    flexion    Sb(s) = Sb0 * (1 - 2 s / t),   Sb0 = (6 / t^2) * integrale(S (t/2 - s) ds)
    pic        Sp(s) = S(s) - Sm - Sb(s)
La decomposition est lineaire : elle est identique composante par composante dans tout repere ;
les equivalents (von Mises, Tresca) sont calcules sur les tenseurs reconstruits.
"""
import numpy as np
from . import fields as F


def _integrate(y, s):
    fn = getattr(np, "trapezoid", None) or np.trapz
    return fn(y, s, axis=0)


def _integrate_weighted(y, s, t):
    """Integrale de y(s) * (t/2 - s) pour y lineaire par morceaux : Simpson par intervalle (exact)."""
    w = t / 2.0 - s
    h = np.diff(s)[:, None]
    f0 = y[:-1] * w[:-1, None]
    f1 = y[1:] * w[1:, None]
    fm = 0.5 * (y[:-1] + y[1:]) * (0.5 * (w[:-1] + w[1:]))[:, None]
    return (h / 6.0 * (f0 + 4.0 * fm + f1)).sum(axis=0)


def linearize(s, tensors):
    """s : (n,) abscisses croissantes ; tensors : (n, 6). Retourne un dict de tenseurs."""
    s = np.asarray(s, dtype=float)
    T = np.asarray(tensors, dtype=float)
    s = s - s[0]
    t = s[-1]
    if t <= 0:
        raise ValueError("segment de longueur nulle")
    sm = _integrate(T, s) / t
    sb0 = 6.0 / t ** 2 * _integrate_weighted(T, s, t)
    sb = sb0[None, :] * (1.0 - 2.0 * s / t)[:, None]
    peak = T - sm[None, :] - sb
    return {"length": t, "s": s, "total": T, "Sm": sm, "Sb0": sb0, "Sb": sb, "peak": peak,
            "Sm_Sb_start": sm + sb0, "Sm_Sb_end": sm - sb0}


def local_frame(p1, p2, ref=None):
    """Repere orthonorme direct (e_t le long du segment, e_a, e_b) ; `ref` oriente e_a."""
    et = np.asarray(p2, float) - np.asarray(p1, float)
    et = et / np.linalg.norm(et)
    if ref is None:
        k = int(np.argmin(np.abs(et)))
        ref = np.zeros(3)
        ref[k] = 1.0
    ref = np.asarray(ref, float)
    ea = ref - ref.dot(et) * et
    n = np.linalg.norm(ea)
    if n < 1e-12:
        raise ValueError("direction de reference colineaire au segment")
    ea /= n
    eb = np.cross(et, ea)
    return et, ea, eb


def rotate(t6, frame):
    """Composantes du tenseur dans le repere `frame` -> (tt, aa, bb, ta, ab, tb)."""
    R = np.array(frame)
    M = F.to_matrix(np.asarray(t6))
    L = R @ M @ R.T
    return np.array([L[0, 0], L[1, 1], L[2, 2], L[0, 1], L[1, 2], L[0, 2]])


def summary(lin):
    """Valeurs scalaires (equivalents von Mises et Tresca) d'une linearisation."""
    out = {}
    pairs = (("Pm", lin["Sm"]), ("Pb", lin["Sb0"]),
             ("PmPb_start", lin["Sm_Sb_start"]), ("PmPb_end", lin["Sm_Sb_end"]),
             ("total_start", lin["total"][0]), ("total_end", lin["total"][-1]))
    for name, t in pairs:
        out[name + "_vonMises"] = float(F.von_mises(t))
        out[name + "_Tresca"] = float(F.tresca(t))
    out["PmPb_max_vonMises"] = max(out["PmPb_start_vonMises"], out["PmPb_end_vonMises"])
    out["PmPb_max_Tresca"] = max(out["PmPb_start_Tresca"], out["PmPb_end_Tresca"])
    out["total_max_vonMises"] = float(F.von_mises(lin["total"]).max())
    out["total_max_Tresca"] = float(F.tresca(lin["total"]).max())
    out["peak_start_vonMises"] = float(F.von_mises(lin["peak"][0]))
    out["peak_end_vonMises"] = float(F.von_mises(lin["peak"][-1]))
    return out
